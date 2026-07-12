import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from account_store import AccountConfigurationError, AccountDatabaseError, AccountStore
import main
from player_state import (
    ACCOUNT_SESSION_STORAGE_KEY,
    ACCOUNT_SYNC_ERROR_STORAGE_KEY,
    ACCOUNT_USERNAME_STORAGE_KEY,
    PLAYER_STATE_KEY,
    default_player_state,
    mark_account_session_verified,
    update_basic_tutorial_stage,
    update_selected_symbol,
)


class UiRouteTests(unittest.TestCase):
    def test_login_path_restores_saved_icon_and_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AccountStore(sqlite_path=Path(directory) / "accounts.sqlite3")
            state = default_player_state()
            symbol_id = state["collection"]["unlocked_symbols"][-1]
            state = update_selected_symbol(state, symbol_id)
            state = update_basic_tutorial_stage(state, 5)
            account = store.register(
                "ui_restore", "password123", "復元プレイヤー", state
            )
            storage: dict[str, object] = {}
            try:
                with patch.object(main, "get_default_account_store", return_value=store):
                    restored = main.establish_account_session(
                        account.username, storage=storage
                    )
            finally:
                store.close()

        self.assertEqual(restored["profile"]["selected_symbol"], symbol_id)
        self.assertEqual(restored["tutorials"]["basic_stage"], 5)
        self.assertEqual(
            storage[PLAYER_STATE_KEY]["profile"]["selected_symbol"], symbol_id
        )
        self.assertEqual(storage[ACCOUNT_USERNAME_STORAGE_KEY], "ui_restore")
        self.assertIn(ACCOUNT_SESSION_STORAGE_KEY, storage)

    def test_explicit_local_recovery_uploads_pending_same_account_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AccountStore(sqlite_path=Path(directory) / "accounts.sqlite3")
            remote_state = update_basic_tutorial_stage(default_player_state(), 2)
            account = store.register(
                "pending_restore", "password123", "復旧プレイヤー", remote_state
            )
            pending_state = update_selected_symbol(
                remote_state,
                remote_state["collection"]["unlocked_symbols"][-1],
            )
            pending_state = update_basic_tutorial_stage(pending_state, 6)
            storage: dict[str, object] = {
                PLAYER_STATE_KEY: pending_state,
                ACCOUNT_USERNAME_STORAGE_KEY: account.username,
                ACCOUNT_SESSION_STORAGE_KEY: "expired-session-token",
                ACCOUNT_SYNC_ERROR_STORAGE_KEY: "session expired before save",
            }
            try:
                with patch.object(
                    main, "get_default_account_store", return_value=store
                ), patch(
                    "account_store.get_default_account_store", return_value=store
                ):
                    restored = main.establish_account_session(
                        account.username,
                        prefer_local_pending=True,
                        storage=storage,
                    )
                database_copy = store.load_player_state(account.username)
            finally:
                store.close()

        self.assertEqual(restored["tutorials"]["basic_stage"], 6)
        self.assertEqual(
            restored["profile"]["selected_symbol"],
            pending_state["profile"]["selected_symbol"],
        )
        self.assertEqual(database_copy, restored)
        self.assertNotIn(ACCOUNT_SYNC_ERROR_STORAGE_KEY, storage)

    def test_database_choice_keeps_remote_state_instead_of_stale_pending(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AccountStore(sqlite_path=Path(directory) / "accounts.sqlite3")
            remote_state = update_basic_tutorial_stage(default_player_state(), 3)
            account = store.register(
                "remote_restore", "password123", "DBプレイヤー", remote_state
            )
            pending_state = update_basic_tutorial_stage(remote_state, 7)
            storage: dict[str, object] = {
                PLAYER_STATE_KEY: pending_state,
                ACCOUNT_USERNAME_STORAGE_KEY: account.username,
                ACCOUNT_SESSION_STORAGE_KEY: "expired-session-token",
                ACCOUNT_SYNC_ERROR_STORAGE_KEY: "old local failure",
            }
            try:
                with patch.object(
                    main, "get_default_account_store", return_value=store
                ):
                    restored = main.establish_account_session(
                        account.username,
                        prefer_local_pending=False,
                        storage=storage,
                    )
                database_copy = store.load_player_state(account.username)
            finally:
                store.close()

        self.assertEqual(restored["tutorials"]["basic_stage"], 3)
        self.assertEqual(database_copy, remote_state)
        self.assertNotIn(ACCOUNT_SYNC_ERROR_STORAGE_KEY, storage)

    def test_logout_failure_keeps_the_only_current_copy_and_session(self) -> None:
        state = default_player_state()
        state = update_selected_symbol(
            state, state["collection"]["unlocked_symbols"][-1]
        )
        storage: dict[str, object] = {
            PLAYER_STATE_KEY: state,
            ACCOUNT_USERNAME_STORAGE_KEY: "field.fox",
            ACCOUNT_SESSION_STORAGE_KEY: "current-session-token",
            ACCOUNT_SYNC_ERROR_STORAGE_KEY: "temporary failure",
        }
        before = dict(storage)

        with patch.object(main, "flush_account_state", return_value=False), patch.object(
            main,
            "get_default_account_store",
            side_effect=AssertionError("failed flush must stop before session deletion"),
        ):
            self.assertFalse(main.log_out_account(storage))

        self.assertEqual(storage, before)

    def test_session_revocation_failure_aborts_logout(self) -> None:
        state = update_selected_symbol(
            default_player_state(),
            default_player_state()["collection"]["unlocked_symbols"][-1],
        )
        storage: dict[str, object] = {
            PLAYER_STATE_KEY: state,
            ACCOUNT_USERNAME_STORAGE_KEY: "field.fox",
            ACCOUNT_SESSION_STORAGE_KEY: "current-session-token",
        }
        store = Mock()
        store.delete_session.side_effect = AccountDatabaseError(
            "temporary revocation failure"
        )

        with patch.object(main, "flush_account_state", return_value=True), patch.object(
            main, "get_default_account_store", return_value=store
        ):
            self.assertFalse(main.log_out_account(storage))

        self.assertEqual(storage[PLAYER_STATE_KEY], state)
        self.assertEqual(storage[ACCOUNT_USERNAME_STORAGE_KEY], "field.fox")
        self.assertEqual(
            storage[ACCOUNT_SESSION_STORAGE_KEY], "current-session-token"
        )
        self.assertIn("ログイン状態は保持", storage[ACCOUNT_SYNC_ERROR_STORAGE_KEY])

    def test_successful_logout_flushes_then_clears_account_scoped_state(self) -> None:
        storage: dict[str, object] = {
            PLAYER_STATE_KEY: default_player_state(),
            ACCOUNT_USERNAME_STORAGE_KEY: "field.fox",
            ACCOUNT_SESSION_STORAGE_KEY: "current-session-token",
            ACCOUNT_SYNC_ERROR_STORAGE_KEY: "old failure",
            "active_match": {"game": "old"},
            "card_tutorial_match": {"game": "old"},
            "battle_selection": {"selected": "infantry_1"},
            main.SIMULATION_MATCH_STORAGE_KEY: {"game": "old"},
            main.SIMULATION_RECORDED_STORAGE_KEY: "old",
            main.SIMULATION_REWARDS_STORAGE_KEY: {"cards": ["old"]},
            main.PLAYER_TOKEN_KEY: "A" * 32,
            main.CLAIMED_MATCHES_KEY: ["old-match"],
            "pvp_selection": {"selected": "infantry_1"},
            "last_pvp_rewards": {"cards": ["old"]},
        }
        store = Mock()

        with (
            patch.object(main, "flush_account_state", return_value=True),
            patch.object(main, "get_default_account_store", return_value=store),
            patch.object(
                main, "poll_multiplayer", return_value={"status": "playing"}
            ) as poll_online,
            patch.object(main, "leave_multiplayer") as leave_online,
            patch.object(main, "close_multiplayer_session") as close_online,
        ):
            self.assertTrue(main.log_out_account(storage))

        poll_online.assert_called_once_with(storage)
        leave_online.assert_called_once_with(storage)
        close_online.assert_called_once_with(storage)
        store.delete_session.assert_called_once_with("current-session-token")
        self.assertNotIn(ACCOUNT_USERNAME_STORAGE_KEY, storage)
        self.assertNotIn(ACCOUNT_SESSION_STORAGE_KEY, storage)
        self.assertNotIn(ACCOUNT_SYNC_ERROR_STORAGE_KEY, storage)
        self.assertNotIn("active_match", storage)
        self.assertNotIn("card_tutorial_match", storage)
        self.assertNotIn("battle_selection", storage)
        self.assertNotIn(main.SIMULATION_MATCH_STORAGE_KEY, storage)
        self.assertNotIn(main.SIMULATION_RECORDED_STORAGE_KEY, storage)
        self.assertNotIn(main.SIMULATION_REWARDS_STORAGE_KEY, storage)
        self.assertNotIn(main.PLAYER_TOKEN_KEY, storage)
        self.assertNotIn(main.CLAIMED_MATCHES_KEY, storage)
        self.assertNotIn("pvp_selection", storage)
        self.assertNotIn("last_pvp_rewards", storage)
        self.assertEqual(storage[PLAYER_STATE_KEY], default_player_state())

    def test_signed_in_username_uses_fresh_session_cache(self) -> None:
        storage: dict[str, object] = {
            ACCOUNT_USERNAME_STORAGE_KEY: "field.fox",
            ACCOUNT_SESSION_STORAGE_KEY: "cached-session-token",
        }
        mark_account_session_verified(
            storage,
            "field.fox",
            "cached-session-token",
            verified_at=1_000.0,
        )

        with patch.object(
            main,
            "get_default_account_store",
            side_effect=AssertionError("fresh page navigation must not query the DB"),
        ):
            self.assertEqual(
                main.signed_in_username(storage, now=1_100.0),
                "field.fox",
            )

    def test_signed_in_username_refreshes_a_stale_session_cache(self) -> None:
        storage: dict[str, object] = {
            ACCOUNT_USERNAME_STORAGE_KEY: "field.fox",
            ACCOUNT_SESSION_STORAGE_KEY: "stale-session-token",
        }
        mark_account_session_verified(
            storage,
            "field.fox",
            "stale-session-token",
            verified_at=1_000.0,
        )
        store = Mock()
        store.resolve_session.return_value = SimpleNamespace(username="field.fox")

        with patch.object(main, "get_default_account_store", return_value=store):
            self.assertEqual(
                main.signed_in_username(storage, now=1_301.0),
                "field.fox",
            )

        store.resolve_session.assert_called_once_with("stale-session-token")

    def test_required_pages_are_registered(self) -> None:
        paths = {
            getattr(route, "path", "")
            for route in main.app.routes
            if getattr(route, "path", "")
        }
        self.assertTrue(
            {
                "/",
                "/home",
                "/learn",
                "/tutorials",
                "/tutorials/basic",
                "/tutorials/card/{card_id}",
                "/cards",
                "/symbols",
                "/deck",
                "/lobby",
                "/online",
                "/friend",
                "/battle",
                "/pvp",
                "/simulation",
                "/simulation-deck",
                "/account",
                "/profile",
                "/settings",
                "/healthz",
            }.issubset(paths)
        )
        self.assertNotIn("/legacy-home", paths)
        self.assertNotIn("/legacy-battle", paths)

    def test_health_check_payload(self) -> None:
        with patch.object(
            main,
            "get_default_account_store",
            side_effect=AssertionError("health check must not wait for the database"),
        ):
            self.assertEqual(main.healthz(), {"status": "ok"})

    def test_account_error_messages_distinguish_database_configuration(self) -> None:
        missing = main.account_store_error_message(
            AccountConfigurationError(
                "DATABASE_URL is required for persistent account storage."
            )
        )
        malformed = main.account_store_error_message(
            AccountConfigurationError(
                "DATABASE_URL must be a PostgreSQL URL on Render."
            )
        )

        self.assertIn("DATABASE_URL", missing)
        self.assertIn("未設定", missing)
        self.assertIn("形式", malformed)
        self.assertNotEqual(missing, malformed)

    def test_account_error_messages_hide_database_secrets(self) -> None:
        secret_url = "postgresql://secret-user:secret-password@example.invalid/db"

        configuration_message = main.account_store_error_message(
            AccountConfigurationError(f"Unsupported account database URL: {secret_url}")
        )
        connection_message = main.account_store_error_message(
            AccountDatabaseError(f"Connection failed for {secret_url}")
        )

        self.assertNotIn(secret_url, configuration_message)
        self.assertNotIn("secret-password", configuration_message)
        self.assertNotIn(secret_url, connection_message)
        self.assertNotIn("secret-password", connection_message)
        self.assertIn("接続できません", connection_message)

    def test_account_backend_label_uses_shared_safe_error_message(self) -> None:
        error = AccountConfigurationError(
            "DATABASE_URL is required for persistent account storage."
        )
        with patch.object(main, "get_default_account_store", side_effect=error):
            label = main.account_backend_label()

        self.assertEqual(label, main.account_store_error_message(error))

    def test_every_card_face_uses_the_same_four_primary_combat_stats(self) -> None:
        expected_labels = ["制圧", "支援", "偵察", "補給"]
        for card in (*main.CARDS, *main.ADVANCED_CARDS):
            with self.subTest(card=card.id):
                stats = main.primary_card_stats(card)
                self.assertEqual([label for label, _ in stats], expected_labels)
                self.assertEqual(len(stats), 4)
                self.assertTrue(stats[-1][1].startswith(("+", "-")))
                self.assertEqual(
                    [value for _, value in stats],
                    [
                        str(card.control),
                        str(card.support),
                        str(card.recon),
                        f"{card.supply:+d}",
                    ],
                )

    def test_card_detail_dialog_is_created_only_on_first_open(self) -> None:
        card = main.CARDS[0]
        dialog = Mock()

        with patch.object(main, "card_detail_dialog", return_value=dialog) as create:
            open_detail = main.lazy_card_detail_opener(card)
            create.assert_not_called()

            open_detail()
            open_detail()

        create.assert_called_once_with(card)
        self.assertEqual(dialog.open.call_count, 2)

    def test_unit_card_with_custom_action_never_prepares_a_dialog(self) -> None:
        action = Mock()
        with patch.object(
            main,
            "lazy_card_detail_opener",
            side_effect=AssertionError("custom actions must not prepare a dialog"),
        ):
            main.unit_card(main.CARDS[0], action=action)


if __name__ == "__main__":
    unittest.main()

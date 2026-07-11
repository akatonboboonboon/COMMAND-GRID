import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from account_store import AccountStore
from advanced_game_data import ADVANCED_CARDS, ADVANCED_STARTER_DECK
from game_data import CARDS, STARTER_DECK
from player_state import (
    ACCOUNT_SESSION_STORAGE_KEY,
    ACCOUNT_SYNC_ERROR_STORAGE_KEY,
    ACCOUNT_USERNAME_STORAGE_KEY,
    MAX_BATTLE_HISTORY,
    PLAYER_STATE_KEY,
    PREFERENCE_DEFAULTS,
    complete_basic_tutorial,
    complete_card_tutorial,
    default_player_state,
    ensure_player_state,
    normalize_player_state,
    record_result,
    store_player_state,
    unlock_collection,
    update_deck,
    update_advanced_deck,
    update_basic_tutorial_stage,
    update_card_tutorial_stage,
    update_formation,
    update_mode,
    update_preference,
    update_profile,
    update_selected_symbol,
)


class PlayerStateTests(unittest.TestCase):
    def test_default_state_is_detached_and_json_serializable(self) -> None:
        first = default_player_state()
        second = default_player_state()
        first["preferences"]["beginner_mode"] = False
        first["deck"].clear()

        self.assertTrue(second["preferences"]["beginner_mode"])
        self.assertEqual(second["deck"], list(STARTER_DECK))
        self.assertEqual(second["profile"]["display_name"], "COMMANDER")
        self.assertEqual(second["profile"]["tagline"], "偵察から覚えています")
        self.assertEqual(
            second["profile"]["selected_symbol"],
            second["collection"]["unlocked_symbols"][0],
        )
        self.assertEqual(
            second["tutorials"],
            {
                "basic_stage": 0,
                "basic_completed": False,
                "card_stages": {},
                "completed_cards": [],
                "unlocked_official_decks": [],
            },
        )
        json.dumps(second)

    def test_account_sync_requires_a_valid_matching_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AccountStore(sqlite_path=Path(directory) / "accounts.sqlite3")
            original = default_player_state()
            account = store.register("sync_user", "password123", "同期ユーザー", original)
            token = store.create_session(account.username)
            storage: dict[str, object] = {
                ACCOUNT_USERNAME_STORAGE_KEY: account.username,
                ACCOUNT_SESSION_STORAGE_KEY: token,
            }

            with patch("account_store.get_default_account_store", return_value=store):
                changed = update_profile(original, tagline="データベースへ同期")
                store_player_state(storage, changed)
                self.assertEqual(
                    store.load_player_state(account.username)["profile"]["tagline"],
                    "データベースへ同期",
                )
                self.assertNotIn(ACCOUNT_SYNC_ERROR_STORAGE_KEY, storage)

                storage[ACCOUNT_SESSION_STORAGE_KEY] = "invalid-session"
                rejected = update_profile(changed, tagline="保存してはいけない")
                store_player_state(storage, rejected)
                self.assertIn(ACCOUNT_SYNC_ERROR_STORAGE_KEY, storage)
                self.assertEqual(
                    store.load_player_state(account.username)["profile"]["tagline"],
                    "データベースへ同期",
                )
            store.close()

    def test_advanced_simulation_unlocks_only_after_all_core_cards(self) -> None:
        state = default_player_state()
        self.assertFalse(state["progression"]["simulation_unlocked"])
        self.assertEqual(
            state["progression"]["advanced_deck"], list(ADVANCED_STARTER_DECK)
        )
        with self.assertRaises(ValueError):
            update_mode(state, "simulation")

        locked_ids = [
            card.id for card in CARDS
            if card.id not in state["collection"]["owned_cards"]
        ]
        unlocked = unlock_collection(state, cards=locked_ids)
        self.assertTrue(unlocked["progression"]["simulation_unlocked"])
        self.assertFalse(unlocked["preferences"]["beginner_mode"])
        selected = update_mode(unlocked, "本格シミュレーション")
        self.assertEqual(selected["selected_mode"], "simulation")
        with self.assertRaises(ValueError):
            update_preference(selected, "beginner_mode", True)

    def test_advanced_deck_validation_and_corrupt_progress_repair(self) -> None:
        all_cards_state = unlock_collection(
            default_player_state(), cards=[card.id for card in CARDS]
        )
        chosen = [card.id for card in ADVANCED_CARDS[:12]]
        updated = update_advanced_deck(all_cards_state, chosen)
        self.assertEqual(updated["progression"]["advanced_deck"], chosen)

        for bad_deck in (
            chosen[:11],
            [*chosen, chosen[0]],
            [*chosen[:11], "missing"],
        ):
            with self.subTest(deck=bad_deck):
                with self.assertRaises(ValueError):
                    update_advanced_deck(all_cards_state, bad_deck)

        repaired = normalize_player_state(
            {
                "progression": {
                    "simulation_unlocked": True,
                    "advanced_deck": ["missing"],
                }
            }
        )
        self.assertFalse(repaired["progression"]["simulation_unlocked"])
        self.assertEqual(
            repaired["progression"]["advanced_deck"], list(ADVANCED_STARTER_DECK)
        )

    def test_tutorial_progress_normalizes_corrupt_and_legacy_values(self) -> None:
        state = normalize_player_state(
            {
                "tutorials": {
                    "basic": {"stage": "6", "completed": "yes"},
                    "card_stages": {
                        "infantry_1": "3",
                        "infantry_2": -5,
                        "armor_1": {"progress": "4", "completed": "true"},
                        "infantry_3": 7,
                        "not_a_card": 9,
                        3: 2,
                    },
                    "completed_cards": [
                        "infantry_1",
                        "infantry_3",
                        "not_a_card",
                        4,
                    ],
                    "unlocked_official_decks": [
                        "official.infantry-1",
                        "space deck",
                        "",
                        7,
                        "official.infantry-1",
                    ],
                }
            }
        )

        self.assertEqual(state["tutorials"]["basic_stage"], 6)
        self.assertTrue(state["tutorials"]["basic_completed"])
        self.assertEqual(
            state["tutorials"]["card_stages"],
            {"infantry_1": 3, "infantry_2": 0, "armor_1": 4},
        )
        self.assertEqual(
            state["tutorials"]["completed_cards"],
            ["armor_1", "infantry_1"],
        )
        self.assertEqual(
            state["tutorials"]["unlocked_official_decks"],
            ["official.infantry-1"],
        )
        self.assertNotIn("infantry_3", state["tutorials"]["card_stages"])
        json.dumps(state)

        legacy = normalize_player_state(
            {
                "basic_tutorial_stage": "2",
                "basic_tutorial_completed": 0,
                "card_tutorial_stages": {"recon_1": "1"},
                "completed_tutorial_cards": ["recon_1"],
                "unlocked_official_decks": ["recon_1"],
            }
        )
        self.assertEqual(legacy["tutorials"]["basic_stage"], 2)
        self.assertFalse(legacy["tutorials"]["basic_completed"])
        self.assertEqual(legacy["tutorials"]["card_stages"], {"recon_1": 1})
        self.assertEqual(legacy["tutorials"]["completed_cards"], ["recon_1"])
        self.assertEqual(
            legacy["tutorials"]["unlocked_official_decks"], ["recon_1"]
        )

    def test_tutorial_updates_are_monotonic_and_detached(self) -> None:
        original = default_player_state()
        basic = update_basic_tutorial_stage(original, 3)
        basic = update_basic_tutorial_stage(basic, 1)
        basic = complete_basic_tutorial(basic, final_stage=8)

        self.assertEqual(original["tutorials"]["basic_stage"], 0)
        self.assertEqual(basic["tutorials"]["basic_stage"], 8)
        self.assertTrue(basic["tutorials"]["basic_completed"])

        card = update_card_tutorial_stage(basic, "infantry_1", 2)
        card = update_card_tutorial_stage(card, "infantry_1", 1)
        card = complete_card_tutorial(
            card,
            "infantry_1",
            official_deck_id="official.infantry-1",
            final_stage=5,
        )
        card = complete_card_tutorial(
            card,
            "infantry_1",
            official_deck_id="official.infantry-1",
            final_stage=4,
        )

        self.assertEqual(card["tutorials"]["card_stages"]["infantry_1"], 5)
        self.assertEqual(card["tutorials"]["completed_cards"], ["infantry_1"])
        self.assertEqual(
            card["tutorials"]["unlocked_official_decks"],
            ["official.infantry-1"],
        )
        self.assertNotIn("infantry_1", basic["tutorials"]["card_stages"])
        json.dumps(card)

        storage: dict[str, object] = {}
        persisted = store_player_state(storage, card)
        reloaded = ensure_player_state(storage)
        self.assertEqual(reloaded["tutorials"], persisted["tutorials"])

    def test_card_tutorial_requires_owned_card_and_valid_progress(self) -> None:
        state = default_player_state()
        with self.assertRaises(ValueError):
            update_card_tutorial_stage(state, "infantry_3", 1)
        with self.assertRaises(ValueError):
            complete_card_tutorial(state, "infantry_3")
        with self.assertRaises(ValueError):
            update_card_tutorial_stage(state, "not_a_card", 1)
        with self.assertRaises(ValueError):
            update_basic_tutorial_stage(state, -1)
        with self.assertRaises(ValueError):
            update_basic_tutorial_stage(state, True)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            update_card_tutorial_stage(state, "infantry_1", "2")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            complete_card_tutorial(
                state, "infantry_1", official_deck_id="contains spaces"
            )

        owned = unlock_collection(state, cards=["infantry_3"])
        completed = complete_card_tutorial(owned, "infantry_3", final_stage=4)
        self.assertIn("infantry_3", completed["tutorials"]["completed_cards"])
        self.assertIn(
            "infantry_3", completed["tutorials"]["unlocked_official_decks"]
        )

    def test_profile_normalizes_nested_and_legacy_root_values(self) -> None:
        legacy = normalize_player_state(
            {
                "player_name": "  Field   Fox  ",
                "tagline": "  補給から   覚えています  ",
            }
        )
        self.assertEqual(legacy["profile"]["display_name"], "Field Fox")
        self.assertEqual(legacy["profile"]["tagline"], "補給から 覚えています")

        nested = normalize_player_state(
            {
                "display_name": "Legacy Name",
                "tagline": "legacy",
                "profile": {"display_name": "SCOUT", "tagline": "索敵担当"},
            }
        )
        self.assertEqual(nested["profile"]["display_name"], "SCOUT")
        self.assertEqual(nested["profile"]["tagline"], "索敵担当")

        repaired = normalize_player_state(
            {
                "profile": {
                    "display_name": "X",
                    "tagline": "長" * 61,
                }
            }
        )
        self.assertEqual(repaired["profile"]["display_name"], "COMMANDER")
        self.assertEqual(repaired["profile"]["tagline"], "偵察から覚えています")
        json.dumps(repaired)

    def test_selected_symbol_is_normalized_to_an_unlocked_symbol(self) -> None:
        baseline = default_player_state()
        fallback = baseline["collection"]["unlocked_symbols"][0]
        locked_symbol = "infantry_09"
        self.assertNotIn(locked_symbol, baseline["collection"]["unlocked_symbols"])

        unknown = normalize_player_state(
            {"profile": {"selected_symbol": "not_a_symbol"}}
        )
        locked = normalize_player_state(
            {"profile": {"selected_symbol": locked_symbol}}
        )
        self.assertEqual(unknown["profile"]["selected_symbol"], fallback)
        self.assertEqual(locked["profile"]["selected_symbol"], fallback)

        migrated = normalize_player_state({"selected_symbol": fallback})
        self.assertEqual(migrated["profile"]["selected_symbol"], fallback)

    def test_malformed_legacy_state_is_safely_normalized(self) -> None:
        raw = {
            "schema_version": "old",
            "preferences": {
                "beginner_mode": "false",
                "text_size": "large",
                "reduce_motion": "yes",
                "profile_visibility": "everyone",
                "unknown_setting": True,
            },
            "collection": {
                "cards": {
                    "infantry_1": {"copies": 2},
                    "not_a_card": True,
                },
                "unlocked_symbols": ["infantry_01", "not_a_symbol", 4],
                "unlocked_formations": ["師団", "space_army"],
            },
            "deck": ["infantry_1", "infantry_1", "not_a_card", 7],
            "formation": "師団",
            "mode": "ランク対戦",
            "history": [
                {
                    "result": "勝利",
                    "points": "4",
                    "turns": "6",
                    "deck": ["infantry_1", "not_a_card"],
                },
                "broken",
                {"result": "unknown"},
            ],
            "stats": {"played": -12, "wins": "bad", "mission_points": -1},
        }

        state = normalize_player_state(raw)

        self.assertFalse(state["preferences"]["beginner_mode"])
        self.assertEqual(state["preferences"]["font_size"], "large")
        self.assertTrue(state["preferences"]["reduce_motion"])
        self.assertEqual(state["preferences"]["profile_visibility"], "friends")
        self.assertEqual(set(state["preferences"]), set(PREFERENCE_DEFAULTS))
        self.assertEqual(state["deck"], ["infantry_1"])
        self.assertEqual(state["selected_formation"], "division")
        self.assertEqual(state["selected_mode"], "ranked")
        self.assertEqual(len(state["battle_history"]), 1)
        self.assertEqual(state["battle_history"][0]["mission_points_for"], 4)
        self.assertEqual(state["stats"]["battles_played"], 1)
        self.assertEqual(state["stats"]["wins"], 1)
        self.assertEqual(state["stats"]["mission_points_earned"], 4)
        json.dumps(state)

    def test_storage_helper_migrates_legacy_root_keys_and_persists(self) -> None:
        storage = {
            "deck": ["infantry_1", "recon_1"],
            "beginner_mode": False,
            "mode": "casual",
        }

        loaded = ensure_player_state(storage)

        self.assertIn(PLAYER_STATE_KEY, storage)
        self.assertEqual(loaded["deck"], ["infantry_1", "recon_1"])
        self.assertFalse(loaded["preferences"]["beginner_mode"])
        self.assertEqual(loaded["selected_mode"], "casual")
        loaded["deck"].clear()
        self.assertEqual(
            storage[PLAYER_STATE_KEY]["deck"], ["infantry_1", "recon_1"]
        )

        persisted = store_player_state(storage, {"mode": "friend", "deck": []})
        self.assertEqual(persisted["selected_mode"], "friend")
        self.assertEqual(storage[PLAYER_STATE_KEY], persisted)

    def test_update_helpers_validate_inputs_without_mutating_source(self) -> None:
        original = default_player_state()
        changed = update_preference(original, "high_contrast", True)
        changed = update_mode(changed, "フレンド対戦")
        changed = update_formation(changed, "師団")
        changed = update_deck(changed, ["infantry_1", "recon_1"])

        self.assertFalse(original["preferences"]["high_contrast"])
        self.assertEqual(original["selected_mode"], "training")
        self.assertEqual(original["selected_formation"], "native")
        self.assertTrue(changed["preferences"]["high_contrast"])
        self.assertEqual(changed["selected_mode"], "friend")
        self.assertEqual(changed["selected_formation"], "division")
        self.assertEqual(changed["deck"], ["infantry_1", "recon_1"])

        with self.assertRaises(ValueError):
            update_preference(original, "does_not_exist", True)
        with self.assertRaises(ValueError):
            update_preference(original, "high_contrast", "yes")
        with self.assertRaises(ValueError):
            update_preference(original, "font_size", "huge")
        with self.assertRaises(ValueError):
            update_mode(original, "battle_royale")
        with self.assertRaises(ValueError):
            update_formation(original, "army_group")
        with self.assertRaises(ValueError):
            update_deck(original, ["not_a_card"])
        with self.assertRaises(ValueError):
            update_deck(original, ["infantry_1", "infantry_1"])

    def test_update_profile_supports_partial_updates_and_validation(self) -> None:
        original = default_player_state()
        renamed = update_profile(original, display_name="  AOI  17 ")
        updated = update_profile(renamed, tagline="")

        self.assertEqual(original["profile"]["display_name"], "COMMANDER")
        self.assertEqual(renamed["profile"]["display_name"], "AOI 17")
        self.assertEqual(renamed["profile"]["tagline"], "偵察から覚えています")
        self.assertEqual(updated["profile"]["tagline"], "")

        with self.assertRaises(ValueError):
            update_profile(original, display_name="A")
        with self.assertRaises(ValueError):
            update_profile(original, display_name="X" * 21)
        with self.assertRaises(ValueError):
            update_profile(original, tagline="長" * 61)
        with self.assertRaises(ValueError):
            update_profile(original, display_name=3)  # type: ignore[arg-type]

    def test_selected_symbol_requires_unlock_and_survives_later_unlocks(self) -> None:
        state = default_player_state()
        available = state["collection"]["unlocked_symbols"]
        selected = available[-1]
        state = update_selected_symbol(state, selected)
        state = unlock_collection(
            state,
            cards=["infantry_3"],
            symbols=["infantry_09"],
        )

        self.assertEqual(state["profile"]["selected_symbol"], selected)
        self.assertIn("infantry_09", state["collection"]["unlocked_symbols"])
        state = update_selected_symbol(state, "infantry_09")
        self.assertEqual(state["profile"]["selected_symbol"], "infantry_09")

        with self.assertRaises(ValueError):
            update_selected_symbol(default_player_state(), "infantry_09")
        with self.assertRaises(ValueError):
            update_selected_symbol(default_player_state(), "not_a_symbol")
        with self.assertRaises(ValueError):
            update_selected_symbol(default_player_state(), 3)  # type: ignore[arg-type]

    def test_unlock_collection_adds_known_items_and_rejects_unknowns(self) -> None:
        original = default_player_state()
        unlocked = unlock_collection(
            original,
            cards=["infantry_3"],
            symbols=["infantry_09"],
            formations=["division"],
        )

        self.assertNotIn("infantry_3", original["collection"]["owned_cards"])
        self.assertIn("infantry_3", unlocked["collection"]["owned_cards"])
        self.assertIn("infantry_09", unlocked["collection"]["unlocked_symbols"])

        with self.assertRaises(ValueError):
            unlock_collection(original, cards=["missing"])
        with self.assertRaises(ValueError):
            unlock_collection(original, symbols="infantry_01")

    def test_record_result_updates_history_stats_streak_and_rewards(self) -> None:
        state = default_player_state()
        played_at = datetime(2026, 7, 10, 12, 30, tzinfo=timezone.utc)
        won = record_result(
            state,
            "勝利",
            mode="casual",
            opponent=" Aoi-17 ",
            mission_points_for=5,
            mission_points_against=2,
            turns=6,
            played_at=played_at,
            summary="中央と右翼を確保",
            unlocked_cards=["infantry_3"],
            unlocked_symbols=["infantry_09"],
        )

        self.assertEqual(state["stats"]["battles_played"], 0)
        self.assertEqual(won["stats"]["battles_played"], 1)
        self.assertEqual(won["stats"]["wins"], 1)
        self.assertEqual(won["stats"]["current_win_streak"], 1)
        self.assertEqual(won["stats"]["best_win_streak"], 1)
        self.assertEqual(won["stats"]["mission_points_earned"], 5)
        self.assertEqual(won["battle_history"][0]["opponent"], "Aoi-17")
        self.assertEqual(
            won["battle_history"][0]["played_at"], "2026-07-10T12:30:00+00:00"
        )
        self.assertIn("infantry_3", won["collection"]["owned_cards"])

        lost = record_result(won, "loss", mission_points_for=1)
        self.assertEqual(lost["stats"]["battles_played"], 2)
        self.assertEqual(lost["stats"]["losses"], 1)
        self.assertEqual(lost["stats"]["current_win_streak"], 0)
        self.assertEqual(lost["battle_history"][0]["result"], "loss")
        self.assertEqual(lost["battle_history"][1]["result"], "win")
        json.dumps(lost)

    def test_record_result_rejects_invalid_values_and_caps_history(self) -> None:
        state = default_player_state()
        with self.assertRaises(ValueError):
            record_result(state, "abandoned")
        with self.assertRaises(ValueError):
            record_result(state, "win", mission_points_for=-1)
        with self.assertRaises(ValueError):
            record_result(state, "win", turns=0)
        with self.assertRaises(ValueError):
            record_result(state, "win", played_at="yesterday")

        for index in range(MAX_BATTLE_HISTORY + 3):
            state = record_result(
                state,
                "draw",
                opponent=f"opponent-{index}",
                played_at="2026-07-10T00:00:00+00:00",
            )
        self.assertEqual(len(state["battle_history"]), MAX_BATTLE_HISTORY)
        self.assertEqual(state["stats"]["battles_played"], MAX_BATTLE_HISTORY + 3)


if __name__ == "__main__":
    unittest.main()

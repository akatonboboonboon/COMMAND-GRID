from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from account_store import (
    PBKDF2_ITERATIONS,
    SESSION_LIFETIME,
    AccountConfigurationError,
    AccountDatabaseError,
    AccountNotFoundError,
    AccountStore,
    AccountValidationError,
    AuthenticationError,
    DuplicateUsernameError,
)


class AccountStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "accounts.sqlite3"
        self.store = AccountStore(sqlite_path=self.database_path)

    def tearDown(self) -> None:
        self.store.close()
        self.temporary_directory.cleanup()

    def register_alice(self) -> None:
        self.store.register(
            "Alice_7",
            "correct horse battery staple",
            "Alice Commander",
            {"deck": ["infantry"], "profile": {"level": 2}},
        )

    def test_register_normalizes_username_and_persists_across_instances(self) -> None:
        account = self.store.register(
            "  Field.Fox  ",
            "a secure password",
            "  Field   Fox  ",
            {"wins": 2, "message": "前進"},
        )

        self.assertEqual(account.username, "field.fox")
        self.assertEqual(account.display_name, "Field Fox")
        self.store.close()
        reopened = AccountStore(sqlite_path=self.database_path)
        try:
            self.assertEqual(
                reopened.load_player_state("FIELD.FOX"),
                {"wins": 2, "message": "前進"},
            )
        finally:
            reopened.close()

    def test_username_is_unique_without_regard_to_case(self) -> None:
        self.store.register("Scout-One", "long enough password", "Scout One")

        with self.assertRaises(DuplicateUsernameError):
            self.store.register("SCOUT-ONE", "another good password", "Other Name")

    def test_japanese_username_can_register_authenticate_and_restore_state(self) -> None:
        expected_state = {
            "deck": ["infantry", "recon"],
            "profile": {"display_name": "赤豚司令官"},
        }
        account = self.store.register(
            "  赤豚司令官01  ",
            "日本語も使える安全なパスワード",
            "赤豚司令官",
            expected_state,
        )

        self.assertEqual(account.username, "赤豚司令官01")
        changed_state = {
            **expected_state,
            "profile": {"display_name": "保存確認済み"},
        }
        self.store.save_player_state(account.username, changed_state)
        self.store.close()
        self.store = AccountStore(sqlite_path=self.database_path)
        authenticated = self.store.authenticate(
            "赤豚司令官01", "日本語も使える安全なパスワード"
        )
        self.assertEqual(authenticated.username, account.username)
        self.assertEqual(self.store.load_player_state(account.username), changed_state)

    def test_two_character_japanese_username_is_allowed(self) -> None:
        account = self.store.register("赤豚", "long enough password", "赤豚")

        self.assertEqual(account.username, "赤豚")

    def test_username_nfkc_normalization_prevents_compatibility_duplicates(self) -> None:
        self.store.register("Ａｌｉｃｅ", "long enough password", "Alice")

        with self.assertRaises(DuplicateUsernameError):
            self.store.register("alice", "another good password", "Other Name")

        self.store.register("Straße", "long enough password", "Straße")
        with self.assertRaises(DuplicateUsernameError):
            self.store.register("STRASSE", "another good password", "Other Name")

    def test_username_validation_rejects_wrong_length_or_characters(self) -> None:
        invalid_names = (
            "a",
            "ß",
            "x" * 25,
            "two words",
            "名前/",
            "a/b",
            "a@b",
            "司令官😀",
            "---",
        )
        for username in invalid_names:
            with self.subTest(username=username):
                with self.assertRaises(AccountValidationError):
                    self.store.register(username, "long enough password", "Valid Name")

    def test_password_and_display_name_are_validated(self) -> None:
        with self.assertRaises(AccountValidationError):
            self.store.register("valid_user", "short", "Valid Name")
        with self.assertRaises(AccountValidationError):
            self.store.register("valid_user", "long enough password", "X")
        with self.assertRaises(AccountValidationError):
            self.store.register(
                "valid_user", "long enough password", "X" * 21
            )
        with self.assertRaises(AccountValidationError):
            self.store.register("valid_user", "long enough password", 3)  # type: ignore[arg-type]

    def test_authenticate_accepts_case_insensitive_username(self) -> None:
        self.register_alice()

        account = self.store.authenticate(
            "ALICE_7", "correct horse battery staple"
        )

        self.assertEqual(account.username, "alice_7")
        self.assertEqual(account.display_name, "Alice Commander")

    def test_authentication_failure_is_generic_for_wrong_and_unknown_users(self) -> None:
        self.register_alice()

        for username, password in (
            ("alice_7", "incorrect password"),
            ("unknown", "incorrect password"),
            ("bad username!", "incorrect password"),
        ):
            with self.subTest(username=username):
                with self.assertRaisesRegex(
                    AuthenticationError, "Invalid username or password"
                ):
                    self.store.authenticate(username, password)

    def test_passwords_have_individual_salts_and_are_not_stored_as_plaintext(self) -> None:
        password = "one shared secure password"
        self.store.register("alpha", password, "Alpha")
        self.store.register("bravo", password, "Bravo")

        with closing(sqlite3.connect(self.database_path)) as connection:
            rows = connection.execute(
                """
                SELECT password_salt, password_hash, password_iterations
                FROM accounts ORDER BY username
                """
            ).fetchall()

        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0][0], rows[1][0])
        self.assertNotEqual(rows[0][1], rows[1][1])
        self.assertTrue(all(len(row[0]) == 32 for row in rows))
        self.assertTrue(all(len(row[1]) == 32 for row in rows))
        self.assertTrue(all(row[2] >= 600_000 for row in rows))
        self.assertEqual(PBKDF2_ITERATIONS, rows[0][2])
        self.assertNotIn(password.encode("utf-8"), self.database_path.read_bytes())

    def test_player_state_can_be_replaced_and_returned_data_is_detached(self) -> None:
        self.register_alice()
        state = {"cards": ["infantry", "recon"], "points": 12}

        self.store.save_player_state("ALICE_7", state)
        loaded = self.store.load_player_state("alice_7")
        loaded["cards"].append("armor")

        self.assertEqual(
            self.store.load_player_state("alice_7"),
            {"cards": ["infantry", "recon"], "points": 12},
        )

    def test_player_state_must_be_a_json_object(self) -> None:
        self.register_alice()

        with self.assertRaises(AccountValidationError):
            self.store.register(
                "new_user", "long enough password", "New User", []  # type: ignore[arg-type]
            )
        with self.assertRaises(AccountValidationError):
            self.store.save_player_state("alice_7", ["not", "an", "object"])  # type: ignore[arg-type]
        with self.assertRaises(AccountValidationError):
            self.store.save_player_state("alice_7", {"bad": {1, 2, 3}})
        with self.assertRaises(AccountValidationError):
            self.store.save_player_state("alice_7", {"bad": float("nan")})

    def test_update_display_name_and_missing_account_errors(self) -> None:
        self.register_alice()

        account = self.store.update_display_name("Alice_7", "  New   Callsign ")

        self.assertEqual(account.display_name, "New Callsign")
        with self.assertRaises(AccountNotFoundError):
            self.store.update_display_name("nobody", "New Name")
        with self.assertRaises(AccountNotFoundError):
            self.store.load_player_state("nobody")
        with self.assertRaises(AccountNotFoundError):
            self.store.save_player_state("nobody", {})

    def test_parameterized_queries_treat_sql_as_data(self) -> None:
        hostile_display_name = "Robert'); DROP TABLE"
        self.store.register(
            "safe_user", "long enough password", hostile_display_name, {}
        )

        account = self.store.authenticate("safe_user", "long enough password")

        self.assertEqual(account.display_name, hostile_display_name)
        with closing(sqlite3.connect(self.database_path)) as connection:
            count = connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        self.assertEqual(count, 1)

    def test_corrupt_json_and_database_failures_use_safe_exceptions(self) -> None:
        self.register_alice()
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                "UPDATE accounts SET player_state = ? WHERE username = ?",
                ("not-json", "alice_7"),
            )
            connection.commit()
        with self.assertRaises(AccountDatabaseError):
            self.store.load_player_state("alice_7")

        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("DROP TABLE accounts")
            connection.commit()
        with self.assertRaises(AccountDatabaseError) as raised:
            self.store.load_player_state("alice_7")
        self.assertNotIn("no such table", str(raised.exception).lower())

    def test_in_memory_database_remains_available_until_close(self) -> None:
        memory_store = AccountStore(sqlite_path=":memory:")
        try:
            memory_store.register("memory", "long enough password", "Memory")
            self.assertEqual(memory_store.load_player_state("MEMORY"), {})
        finally:
            memory_store.close()

    def test_invalid_database_configuration_is_safe(self) -> None:
        with self.assertRaises(AccountConfigurationError):
            AccountStore(database_url="mysql://secret@example.invalid/database")
        with self.assertRaises(AccountConfigurationError):
            AccountStore(database_url="one.db", sqlite_path="two.db")

    def test_render_refuses_ephemeral_sqlite_fallback(self) -> None:
        with patch.dict(
            "os.environ",
            {"RENDER": "true"},
            clear=True,
        ):
            with self.assertRaisesRegex(AccountConfigurationError, "DATABASE_URL"):
                AccountStore()

            explicit_test_store = AccountStore(sqlite_path=":memory:")
            explicit_test_store.close()

    def test_long_username_can_supply_the_default_display_name(self) -> None:
        account = self.store.register("Abcdefghijklmnopqrstuvwx", "secure password")

        self.assertEqual(account.username, "abcdefghijklmnopqrstuvwx")
        self.assertEqual(account.display_name, "Abcdefghijklmnopqrst")


class SessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "sessions.sqlite3"
        self.store = AccountStore(sqlite_path=self.database_path)
        self.store.register("session_user", "a secure password", "Session User", {})
        self.base_time = datetime(2026, 7, 11, 4, 30, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.store.close()
        self.temporary_directory.cleanup()

    def test_session_resolves_for_exactly_thirty_days_and_survives_reopen(self) -> None:
        token = self.store.create_session("SESSION_USER", now=self.base_time)
        self.assertGreaterEqual(len(token), 40)
        self.store.close()

        reopened = AccountStore(sqlite_path=self.database_path)
        try:
            account = reopened.resolve_session(
                token, now=self.base_time + SESSION_LIFETIME - timedelta(seconds=1)
            )
            self.assertIsNotNone(account)
            assert account is not None
            self.assertEqual(account.username, "session_user")
            self.assertIsNone(
                reopened.resolve_session(
                    token, now=self.base_time + SESSION_LIFETIME
                )
            )
        finally:
            reopened.close()

    def test_database_contains_only_session_token_hash(self) -> None:
        token = self.store.create_session("session_user", now=self.base_time)
        expected_hash = hashlib.sha256(token.encode("utf-8")).digest()

        with closing(sqlite3.connect(self.database_path)) as connection:
            stored_hash = connection.execute(
                "SELECT token_hash FROM sessions"
            ).fetchone()[0]

        self.assertEqual(stored_hash, expected_hash)
        self.assertNotEqual(stored_hash, token.encode("utf-8"))
        self.assertNotIn(token.encode("utf-8"), self.database_path.read_bytes())

    def test_delete_session_is_idempotent(self) -> None:
        token = self.store.create_session("session_user", now=self.base_time)

        self.assertTrue(self.store.delete_session(token))
        self.assertFalse(self.store.delete_session(token))
        self.assertFalse(self.store.delete_session("bad"))
        self.assertIsNone(self.store.resolve_session(token, now=self.base_time))

    def test_unknown_and_malformed_sessions_do_not_authenticate(self) -> None:
        self.assertIsNone(self.store.resolve_session(""))
        self.assertIsNone(self.store.resolve_session("x" * 64, now=self.base_time))

    def test_purge_expired_sessions_only_removes_expired_rows(self) -> None:
        old_token = self.store.create_session("session_user", now=self.base_time)
        fresh_token = self.store.create_session(
            "session_user", now=self.base_time + timedelta(days=10)
        )

        removed = self.store.purge_expired_sessions(
            now=self.base_time + timedelta(days=31)
        )

        self.assertEqual(removed, 1)
        self.assertIsNone(
            self.store.resolve_session(old_token, now=self.base_time + timedelta(days=31))
        )
        self.assertIsNotNone(
            self.store.resolve_session(fresh_token, now=self.base_time + timedelta(days=31))
        )

    def test_create_session_requires_an_existing_account(self) -> None:
        with self.assertRaises(AccountNotFoundError):
            self.store.create_session("nobody", now=self.base_time)

    def test_naive_session_times_are_rejected(self) -> None:
        with self.assertRaises(AccountValidationError):
            self.store.create_session("session_user", now=datetime(2026, 7, 11))


if __name__ == "__main__":
    unittest.main()

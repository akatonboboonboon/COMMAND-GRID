import unittest
from unittest.mock import patch

from account_store import AccountConfigurationError, AccountDatabaseError
import main


class UiRouteTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

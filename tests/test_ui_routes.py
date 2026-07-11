import unittest
from unittest.mock import patch

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

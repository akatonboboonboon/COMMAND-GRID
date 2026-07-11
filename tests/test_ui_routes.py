import unittest

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
                "/profile",
                "/settings",
                "/healthz",
            }.issubset(paths)
        )
        self.assertNotIn("/legacy-home", paths)
        self.assertNotIn("/legacy-battle", paths)

    def test_health_check_payload(self) -> None:
        self.assertEqual(main.healthz(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()

import asyncio
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nicegui import app, background_tasks, core
from nicegui.persistence.pseudo_persistent_dict import PseudoPersistentDict
from nicegui.storage import Storage
from nicegui.testing import user_simulation

import main


class UiSimulationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._storage_directory = tempfile.TemporaryDirectory()
        self._original_storage_path = Storage.path
        Storage.path = Path(self._storage_directory.name)
        self._original_pytest_marker = os.environ.get("PYTEST_CURRENT_TEST")
        os.environ["PYTEST_CURRENT_TEST"] = self.id()

    def tearDown(self) -> None:
        Storage.path = self._original_storage_path
        if self._original_pytest_marker is None:
            os.environ.pop("PYTEST_CURRENT_TEST", None)
        else:
            os.environ["PYTEST_CURRENT_TEST"] = self._original_pytest_marker
        self._storage_directory.cleanup()

    async def asyncSetUp(self) -> None:
        """Finish a script client's deferred outbox before NiceGUI resets it.

        Some earlier UI unit tests intentionally create elements without starting a
        server. NiceGUI consequently defers that pseudo-client's outbox coroutine
        to app startup. ``user_simulation`` resets the app instead of starting it,
        so we start and stop this one deferred coroutine first.
        """

        client = core.script_client
        if client is None:
            return

        deferred_name = f"outbox loop {client.id}"
        matching_handlers = [
            handler
            for handler in app._startup_handlers  # pylint: disable=protected-access
            if handler.__closure__
            and any(
                cell.cell_contents == deferred_name
                for cell in handler.__closure__
            )
        ]
        if not matching_handlers:
            return

        core.loop = asyncio.get_running_loop()
        client.outbox.stop()
        for handler in matching_handlers:
            handler()
            app._startup_handlers.remove(handler)  # pylint: disable=protected-access
        await asyncio.sleep(0)
        await background_tasks.teardown()

    async def test_collection_marks_every_card_used_by_the_current_deck(self) -> None:
        with patch.object(
            Storage,
            "_create_persistent_dict",
            side_effect=lambda _storage_id: PseudoPersistentDict(),
        ):
            async with user_simulation(root=main.advanced_cards_page) as user:
                await user.open("/")
                await user.should_see("カード図鑑")

                in_deck_badges = {
                    element
                    for element in user.find(content="編制中").elements
                    if "status-chip" in element._classes  # pylint: disable=protected-access
                }
                await asyncio.sleep(0.1)

        self.assertEqual(len(in_deck_badges), len(main.STARTER_DECK))

    async def test_deck_page_shows_count_and_four_stats_in_both_lists(self) -> None:
        with patch.object(
            Storage,
            "_create_persistent_dict",
            side_effect=lambda _storage_id: PseudoPersistentDict(),
        ):
            async with user_simulation(root=main.deck_page) as user:
                await user.open("/")
                await user.should_see("現在選択中 12 / 12枚")
                await user.should_see("部隊名")
                await user.should_not_see("部隊規模")

                expected_card_faces = len(main.CARDS) + len(main.STARTER_DECK)
                for label in ("制圧", "支援", "偵察", "補給"):
                    with self.subTest(label=label):
                        stat_labels = {
                            element
                            for element in user.find(content=label).elements
                            if "card-stat__label" in element._classes  # pylint: disable=protected-access
                        }
                        self.assertEqual(len(stat_labels), expected_card_faces)
                await asyncio.sleep(0.1)

    async def test_advanced_board_renders_day_and_all_four_theater_rules(self) -> None:
        player = main.default_player_state()
        player["progression"]["simulation_unlocked"] = True
        state = main.new_simulation(main.ADVANCED_STARTER_DECK)
        with (
            patch.object(
                Storage,
                "_create_persistent_dict",
                side_effect=lambda _storage_id: PseudoPersistentDict(),
            ),
            patch.object(main, "ensure_player_state", return_value=player),
            patch.object(main, "update_state_mode", return_value=player),
            patch.object(main, "store_player_state", return_value=player),
            patch.object(main, "load_or_start_simulation", return_value=state),
        ):
            async with user_simulation(root=main.simulation_page) as user:
                await user.open("/")
                await user.should_see("現在は昼です")
                await user.should_see("海上作戦域")
                await user.should_see("海軍・空軍のみ配置可能")
                land_restrictions = user.find(content="海軍は配置不可").elements
                self.assertEqual(len(land_restrictions), 3)
                await user.should_see("分類連携 +0 / 航空連携 +0 / 夜間 -0")
                await asyncio.sleep(0.1)

    def test_lane_headers_reserve_one_consistent_status_position(self) -> None:
        stylesheet = (
            Path(main.__file__).resolve().parent / "static" / "styles.css"
        ).read_text(encoding="utf-8")
        match = re.search(r"\.lane-header\s*\{(?P<body>[^}]*)\}", stylesheet)

        self.assertIsNotNone(match)
        declarations = match.group("body") if match else ""
        self.assertIn("flex-direction: column", declarations)
        self.assertIn("align-items: flex-start", declarations)
        self.assertRegex(declarations, r"min-height\s*:\s*\d")

    def test_advanced_board_has_four_desktop_columns_and_mobile_swipe(self) -> None:
        stylesheet = (
            Path(main.__file__).resolve().parent / "static" / "styles.css"
        ).read_text(encoding="utf-8")
        desktop = re.search(
            r"\.simulation-theater-grid\s*\{(?P<body>[^}]*)\}", stylesheet
        )

        self.assertIsNotNone(desktop)
        self.assertIn(
            "grid-template-columns: repeat(4, minmax(0, 1fr))",
            desktop.group("body") if desktop else "",
        )
        self.assertIn(".simulation-time-banner--day", stylesheet)
        self.assertIn(".simulation-time-banner--night", stylesheet)
        self.assertRegex(
            stylesheet,
            r"@media \(max-width: 1180px\)[\s\S]*?\.simulation-theater-grid\s*\{[\s\S]*?display: flex;",
        )

    def test_advanced_board_explains_time_and_theater_restrictions(self) -> None:
        source = Path(main.__file__).read_text(encoding="utf-8")

        for text in (
            "現在は{time_of_day}です",
            "海軍・空軍のみ配置可能",
            "海軍は配置不可",
            "分類連携 +{own_power.family_bonus}",
            "航空連携 +{own_power.aviation_bonus}",
            "夜間 -{own_power.night_penalty}",
        ):
            self.assertIn(text, source)


if __name__ == "__main__":
    unittest.main()

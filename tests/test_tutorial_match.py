import json
import unittest

from game_data import CARDS
from game_engine import MAX_ROUNDS, Phase, RuleViolation
from match_service import ACTIVE_MATCH_KEY
from tutorial_match import (
    CARD_TUTORIAL_MATCH_KEY,
    TUTORIAL_AI_ID,
    TUTORIAL_AI_SCRIPT,
    TUTORIAL_PLAYER_ID,
    abandon_tutorial_match,
    load_tutorial_match,
    play_tutorial_round,
    restart_tutorial_match,
    start_tutorial_match,
    tutorial_match_status,
    tutorial_player_deck,
)


class TutorialMatchTests(unittest.TestCase):
    def test_every_card_starts_first_in_a_nine_card_hand_on_an_empty_board(self) -> None:
        for card in CARDS:
            with self.subTest(card=card.id):
                storage: dict = {}
                state = start_tutorial_match(storage, card.id)

                self.assertEqual(state.max_rounds, MAX_ROUNDS)
                self.assertEqual(state.round_no, 1)
                self.assertEqual(state.phase, Phase.PLANNING)
                self.assertEqual(state.player_order, (TUTORIAL_PLAYER_ID, TUTORIAL_AI_ID))
                self.assertEqual(len(state.players[TUTORIAL_PLAYER_ID].hand), MAX_ROUNDS)
                self.assertEqual(state.players[TUTORIAL_PLAYER_ID].hand[0], card.id)
                self.assertEqual(tuple(state.players[TUTORIAL_PLAYER_ID].hand), tutorial_player_deck(card.id))
                self.assertTrue(
                    all(not lane.deployments for lane in state.lanes.values())
                )
                self.assertIn(CARD_TUTORIAL_MATCH_KEY, storage)

    def test_all_card_exercises_can_pass_with_a_simple_two_front_plan(self) -> None:
        for card in CARDS:
            with self.subTest(card=card.id):
                sentinel = {"normal": "battle remains untouched"}
                storage: dict = {ACTIVE_MATCH_KEY: sentinel}
                state = start_tutorial_match(storage, card.id)

                # Alternating the next available card between two fronts is a
                # deliberately basic plan, not a solver tailored to each card.
                for round_index in range(MAX_ROUNDS):
                    chosen_card = state.players[TUTORIAL_PLAYER_ID].hand[0]
                    lane_id = "left" if round_index % 2 == 0 else "center"
                    state, resolution, status = play_tutorial_round(
                        storage, card.id, chosen_card, lane_id
                    )
                    self.assertEqual(resolution.round_no, round_index + 1)

                self.assertEqual(state.phase, Phase.COMPLETE)
                self.assertTrue(status.match_complete)
                self.assertTrue(status.featured_card_used)
                self.assertTrue(status.passed)
                self.assertGreaterEqual(status.controlled_lane_count, 2)
                self.assertEqual(status.rounds_played, MAX_ROUNDS)
                self.assertEqual(storage[ACTIVE_MATCH_KEY], sentinel)
                json.dumps(storage[CARD_TUTORIAL_MATCH_KEY], ensure_ascii=False)
                json.dumps(status.to_dict(), ensure_ascii=False)

    def test_using_the_card_without_two_fronts_does_not_pass(self) -> None:
        storage: dict = {}
        state = start_tutorial_match(storage, "armor_1")

        for _ in range(MAX_ROUNDS):
            chosen_card = state.players[TUTORIAL_PLAYER_ID].hand[0]
            state, _, status = play_tutorial_round(
                storage, "armor_1", chosen_card, "right"
            )

        self.assertTrue(status.match_complete)
        self.assertTrue(status.featured_card_used)
        self.assertEqual(status.controlled_lanes, ("right",))
        self.assertFalse(status.passed)
        self.assertIn("2戦線", status.message)

    def test_script_creates_nine_legal_ai_orders_and_round_trips(self) -> None:
        self.assertEqual(len(TUTORIAL_AI_SCRIPT), MAX_ROUNDS)
        storage: dict = {}
        state = start_tutorial_match(storage, "recon_2")

        state, _, first_status = play_tutorial_round(
            storage, "recon_2", "recon_2", "left"
        )
        restored = load_tutorial_match(storage, "recon_2")

        self.assertEqual(restored.to_dict(), state.to_dict())
        self.assertTrue(first_status.featured_card_used)
        self.assertFalse(first_status.match_complete)
        self.assertEqual(first_status.rounds_played, 1)
        enemy = next(
            deployment
            for deployment in restored.lanes["left"].deployments
            if deployment.player_id == TUTORIAL_AI_ID
        )
        self.assertEqual(enemy.card_id, "recon_2")

    def test_restart_abandon_and_corrupt_data_have_isolated_lifecycle(self) -> None:
        storage: dict = {ACTIVE_MATCH_KEY: {"normal": True}}
        first = start_tutorial_match(storage, "infantry_1")
        first, _, _ = play_tutorial_round(
            storage, "infantry_1", "infantry_1", "left"
        )

        restarted = restart_tutorial_match(storage, "infantry_1")
        self.assertNotEqual(restarted.game_id, first.game_id)
        self.assertTrue(all(not lane.deployments for lane in restarted.lanes.values()))
        self.assertEqual(storage[ACTIVE_MATCH_KEY], {"normal": True})

        storage[CARD_TUTORIAL_MATCH_KEY] = {"bad": True}
        self.assertIsNone(load_tutorial_match(storage, "infantry_1"))
        self.assertNotIn(CARD_TUTORIAL_MATCH_KEY, storage)
        self.assertEqual(storage[ACTIVE_MATCH_KEY], {"normal": True})

        start_tutorial_match(storage, "infantry_1")
        self.assertTrue(abandon_tutorial_match(storage))
        self.assertFalse(abandon_tutorial_match(storage))
        self.assertEqual(storage[ACTIVE_MATCH_KEY], {"normal": True})

    def test_different_lesson_replaces_only_the_tutorial_match(self) -> None:
        storage: dict = {}
        first = start_tutorial_match(storage, "infantry_1")
        second = start_tutorial_match(storage, "artillery_3")

        self.assertNotEqual(first.game_id, second.game_id)
        self.assertEqual(second.players[TUTORIAL_PLAYER_ID].hand[0], "artillery_3")
        self.assertIsNone(load_tutorial_match(storage, "infantry_1"))
        self.assertEqual(
            tutorial_match_status(storage, "artillery_3").featured_card_id,
            "artillery_3",
        )

    def test_unknown_card_and_playing_after_completion_fail_safely(self) -> None:
        with self.assertRaises(RuleViolation) as unknown:
            start_tutorial_match({}, "not_a_card")
        self.assertEqual(unknown.exception.code, "unknown_card")

        storage: dict = {}
        state = start_tutorial_match(storage, "engineer_1")
        for index in range(MAX_ROUNDS):
            state, _, _ = play_tutorial_round(
                storage,
                "engineer_1",
                state.players[TUTORIAL_PLAYER_ID].hand[0],
                "left" if index % 2 == 0 else "center",
            )
        with self.assertRaises(RuleViolation) as complete:
            play_tutorial_round(storage, "engineer_1", "engineer_1", "left")
        self.assertEqual(complete.exception.code, "match_complete")


if __name__ == "__main__":
    unittest.main()

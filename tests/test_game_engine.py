import json
import unittest

from game_engine import (
    GameState,
    Phase,
    RuleViolation,
    calculate_lane_power,
    card_metadata,
    choose_ai_order,
    forfeit_match,
    new_game,
    play_ai_turn,
    resolve_round,
    submit_order,
)


PLAYER_DECK = [
    "infantry_2",
    "infantry_1",
    "armor_1",
    "logistics_1",
    "engineer_1",
    "artillery_1",
]
OPPONENT_DECK = [
    "recon_2",
    "recon_1",
    "engineer_2",
    "artillery_2",
    "logistics_2",
    "armor_2",
]


class GameEngineTests(unittest.TestCase):
    def make_game(self, **kwargs) -> GameState:
        return new_game(
            PLAYER_DECK,
            OPPONENT_DECK,
            player_id="p1",
            opponent_id="p2",
            player_name="Player 1",
            opponent_name="Player 2",
            game_id="test-game",
            **kwargs,
        )

    def test_full_six_round_match_produces_winner_and_serializable_result(self) -> None:
        winning_deck = ["infantry_2"] * 6
        losing_deck = ["recon_2"] * 6
        state = new_game(
            winning_deck,
            losing_deck,
            player_id="p1",
            opponent_id="p2",
            game_id="full-match",
        )

        for _ in range(6):
            submit_order(state, "p1", "infantry_2", "center")
            submit_order(state, "p2", "recon_2", "left")
            resolution = resolve_round(state)

        self.assertTrue(resolution.match_complete)
        self.assertEqual(state.phase, Phase.COMPLETE)
        self.assertEqual(state.round_no, 6)
        self.assertIsNotNone(state.result)
        self.assertEqual(state.result.outcome, "win")
        self.assertEqual(state.result.winner_id, "p1")
        self.assertEqual(state.players["p1"].mission_points, 6)
        self.assertEqual(state.players["p2"].mission_points, 0)
        restored = GameState.from_dict(json.loads(json.dumps(state.to_dict(), ensure_ascii=False)))
        self.assertEqual(restored.to_dict(), state.to_dict())

    def test_final_two_lane_control_takes_priority_over_accumulated_points(self) -> None:
        state = new_game(
            ["infantry_2"] * 4 + ["recon_2"] * 2,
            ["recon_2"] * 4 + ["infantry_2"] * 2,
            player_id="p1",
            opponent_id="p2",
            game_id="lane-control-win",
        )

        for round_index in range(6):
            submit_order(
                state,
                "p1",
                "infantry_2" if round_index < 4 else "recon_2",
                "center",
            )
            submit_order(
                state,
                "p2",
                "recon_2" if round_index < 4 else "infantry_2",
                "left" if round_index < 5 else "right",
            )
            resolve_round(state)

        self.assertGreater(state.players["p1"].mission_points, state.players["p2"].mission_points)
        self.assertEqual(state.result.winner_id, "p2")
        self.assertIn("2戦線", state.result.summary)

    def test_invalid_orders_are_rejected_with_stable_codes(self) -> None:
        state = self.make_game()
        with self.assertRaises(RuleViolation) as unknown_lane:
            submit_order(state, "p1", "infantry_2", "north")
        self.assertEqual(unknown_lane.exception.code, "unknown_lane")

        with self.assertRaises(RuleViolation) as missing_card:
            submit_order(state, "p1", "infantry_3", "center")
        self.assertEqual(missing_card.exception.code, "card_not_in_hand")

        submit_order(state, "p1", "infantry_2", "center")
        with self.assertRaises(RuleViolation) as duplicate:
            submit_order(state, "p1", "infantry_1", "left")
        self.assertEqual(duplicate.exception.code, "order_already_submitted")

        with self.assertRaises(RuleViolation) as incomplete:
            resolve_round(state)
        self.assertEqual(incomplete.exception.code, "wrong_phase")

    def test_forfeit_finishes_match_and_clears_pending_orders(self) -> None:
        state = self.make_game()
        submit_order(state, "p1", "infantry_2", "center")

        result = forfeit_match(state, "p1")

        self.assertEqual(state.phase, Phase.COMPLETE)
        self.assertEqual(result.winner_id, "p2")
        self.assertFalse(state.orders)
        self.assertIn("不戦勝", result.summary)

    def test_recon_reveals_hidden_enemy_deployment_only_to_scout(self) -> None:
        player_deck = ["recon_1", *PLAYER_DECK[:5]]
        opponent_deck = ["infantry_1", *OPPONENT_DECK[:5]]
        state = new_game(
            player_deck,
            opponent_deck,
            player_id="scout",
            opponent_id="target",
            game_id="recon-test",
        )
        submit_order(state, "scout", "recon_1", "center")
        submit_order(state, "target", "infantry_1", "center")
        resolve_round(state)

        enemy = next(
            deployment
            for deployment in state.lanes["center"].deployments
            if deployment.player_id == "target"
        )
        self.assertIn("scout", enemy.revealed_to)
        scout_view = state.view_for("scout")
        visible_enemy = next(
            deployment
            for deployment in scout_view["lanes"]["center"]["deployments"]
            if deployment["player_id"] == "target"
        )
        self.assertFalse(visible_enemy["hidden"])
        self.assertEqual(visible_enemy["card_id"], "infantry_1")
        self.assertTrue(any(event["kind"] == "recon_reveal" for event in scout_view["events"]))

    def test_hidden_enemy_power_breakdown_is_not_exposed(self) -> None:
        state = self.make_game()
        submit_order(state, "p1", "infantry_2", "center")
        submit_order(state, "p2", "recon_2", "left")
        resolve_round(state)

        view = state.view_for("p1")
        left = view["lanes"]["left"]
        enemy = next(
            deployment
            for deployment in left["deployments"]
            if deployment["player_id"] == "p2"
        )
        self.assertTrue(enemy["hidden"])
        self.assertNotIn("p2", left["last_power"])
        scored = next(
            event
            for event in view["events"]
            if event["kind"] == "lane_scored" and event["lane_id"] == "left"
        )
        self.assertTrue(scored["details"]["power_hidden"])
        self.assertNotIn("power", scored["details"])

    def test_logistics_fully_supplies_armor_and_unlocks_synergy_bonus(self) -> None:
        state = self.make_game()
        submit_order(state, "p1", "armor_1", "center")
        submit_order(state, "p2", "recon_2", "left")
        resolve_round(state)
        armor_alone = calculate_lane_power(state, "center", "p1")
        self.assertEqual(armor_alone.supply_deficit, 2)
        self.assertEqual(armor_alone.armor_supply_bonus, 0)
        self.assertEqual(armor_alone.total, 3)

        submit_order(state, "p1", "logistics_1", "center")
        submit_order(state, "p2", "recon_1", "right")
        resolve_round(state)
        supplied = calculate_lane_power(state, "center", "p1")
        self.assertEqual(supplied.supply_generated, 3)
        self.assertEqual(supplied.supply_demand, 2)
        self.assertEqual(supplied.supply_deficit, 0)
        self.assertEqual(supplied.armor_supply_bonus, 2)
        self.assertEqual(supplied.total, 9)

    def test_round_completion_clears_orders_draws_and_advances(self) -> None:
        state = self.make_game(opening_hand_size=5)
        initial_hand = len(state.players["p1"].hand)
        submit_order(state, "p1", "infantry_2", "center")
        submit_order(state, "p2", "recon_2", "center")
        resolution = resolve_round(state)

        self.assertEqual(resolution.round_no, 1)
        self.assertFalse(resolution.match_complete)
        self.assertEqual(state.round_no, 2)
        self.assertEqual(state.phase, Phase.PLANNING)
        self.assertEqual(state.orders, {})
        self.assertEqual(len(state.players["p1"].hand), initial_hand)
        self.assertEqual(len(state.lanes["center"].round_winners), 1)
        self.assertTrue(any(event.kind == "round_started" for event in state.events))

    def test_ai_plan_is_legal_and_deterministic_after_save_restore(self) -> None:
        state = self.make_game()
        first = choose_ai_order(state, "p2")
        restored = GameState.from_dict(state.to_dict())
        second = choose_ai_order(restored, "p2")
        self.assertEqual(first.to_dict(), second.to_dict())
        played = play_ai_turn(state, "p2")
        self.assertEqual(played.to_dict(), first.to_dict())
        self.assertIn(played.card_id, OPPONENT_DECK)

    def test_division_formation_metadata_and_default_hand_are_available(self) -> None:
        state = self.make_game()
        metadata = card_metadata("infantry_2", "division")
        self.assertEqual(metadata["echelon"], "師団")
        self.assertEqual(metadata["formation"]["name"], "師団")
        self.assertEqual(metadata["formation"]["marker"], "XX")
        self.assertTrue(metadata["large_formation"])
        order = submit_order(state, "p1", "infantry_2", "center", "division")
        self.assertEqual(order.card_id, "infantry_2")
        self.assertEqual(order.formation_id, "division")


if __name__ == "__main__":
    unittest.main()

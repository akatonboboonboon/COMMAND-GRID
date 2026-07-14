import json
import unittest

from game_engine import (
    AiDifficulty,
    GameState,
    MAX_ROUNDS,
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
    "recon_1",
    "armor_2",
    "engineer_2",
]
OPPONENT_DECK = [
    "recon_2",
    "recon_1",
    "engineer_2",
    "artillery_2",
    "logistics_2",
    "armor_2",
    "infantry_1",
    "armor_1",
    "artillery_1",
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

    def test_full_nine_round_match_produces_winner_and_serializable_result(self) -> None:
        winning_deck = ["infantry_2"] * MAX_ROUNDS
        losing_deck = ["recon_2"] * MAX_ROUNDS
        state = new_game(
            winning_deck,
            losing_deck,
            player_id="p1",
            opponent_id="p2",
            game_id="full-match",
        )

        for _ in range(MAX_ROUNDS):
            submit_order(state, "p1", "infantry_2", "center")
            submit_order(state, "p2", "recon_2", "left")
            resolution = resolve_round(state)

        self.assertTrue(resolution.match_complete)
        self.assertEqual(state.phase, Phase.COMPLETE)
        self.assertEqual(state.round_no, MAX_ROUNDS)
        self.assertIsNotNone(state.result)
        self.assertEqual(state.result.outcome, "win")
        self.assertEqual(state.result.winner_id, "p1")
        self.assertEqual(state.players["p1"].mission_points, MAX_ROUNDS)
        self.assertEqual(state.players["p2"].mission_points, 0)
        restored = GameState.from_dict(json.loads(json.dumps(state.to_dict(), ensure_ascii=False)))
        self.assertEqual(restored.to_dict(), state.to_dict())

    def test_final_two_lane_control_takes_priority_over_accumulated_points(self) -> None:
        state = new_game(
            ["infantry_2"] * 6 + ["recon_2"] * 3,
            ["recon_2"] * 6 + ["infantry_2"] * 3,
            player_id="p1",
            opponent_id="p2",
            game_id="lane-control-win",
        )

        for round_index in range(MAX_ROUNDS):
            submit_order(
                state,
                "p1",
                "infantry_2" if round_index < 6 else "recon_2",
                "center",
            )
            submit_order(
                state,
                "p2",
                "recon_2" if round_index < 6 else "infantry_2",
                "left" if round_index < 8 else "right",
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
        player_deck = ["recon_1", *PLAYER_DECK[:8]]
        opponent_deck = ["infantry_1", *OPPONENT_DECK[:8]]
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

    def test_easy_ai_is_predictable_weaker_and_visits_all_three_lanes(self) -> None:
        state = self.make_game()
        chosen: list[tuple[str, str]] = []

        for expected_lane in ("left", "center", "right"):
            restored = GameState.from_dict(state.to_dict())
            expected = choose_ai_order(
                restored, "p2", difficulty=AiDifficulty.EASY
            )
            order = play_ai_turn(state, "p2", difficulty=AiDifficulty.EASY)
            self.assertEqual(order.to_dict(), expected.to_dict())
            self.assertEqual(order.lane_id, expected_lane)
            chosen.append((order.card_id, order.lane_id))
            submit_order(state, "p1", state.players["p1"].hand[0], "left")
            resolve_round(state)

        # The standard AI opens with useful control.  Easy AI intentionally
        # wastes low-impact cards first and never reads the enemy board.
        self.assertEqual(
            chosen,
            [
                ("recon_2", "left"),
                ("artillery_1", "center"),
                ("artillery_2", "right"),
            ],
        )

    def test_unknown_ai_difficulty_is_a_safe_rule_error(self) -> None:
        with self.assertRaises(RuleViolation) as raised:
            choose_ai_order(self.make_game(), "p2", difficulty="impossible")
        self.assertEqual(raised.exception.code, "invalid_ai_difficulty")

    def test_ai_opens_multiple_fronts_instead_of_stacking_one_lane(self) -> None:
        state = new_game(
            ["infantry_2"] * MAX_ROUNDS,
            ["infantry_2"] * MAX_ROUNDS,
            player_id="p1",
            opponent_id="p2",
            game_id="ai-distribution",
        )
        chosen_lanes: list[str] = []

        for _ in range(5):
            submit_order(state, "p1", "infantry_2", "left")
            order = choose_ai_order(state, "p2")
            chosen_lanes.append(order.lane_id)
            submit_order(state, "p2", order.card_id, order.lane_id)
            resolve_round(state)

        self.assertEqual(set(chosen_lanes[:3]), {"left", "center", "right"})
        controlled = {
            lane_id
            for lane_id, lane in state.lanes.items()
            if lane.round_winners[-1] == "p2"
        }
        self.assertGreaterEqual(len(controlled), 2)

    def test_ai_uses_supply_synergy_after_establishing_two_lanes(self) -> None:
        state = new_game(
            ["infantry_2"] * MAX_ROUNDS,
            ["armor_1", "infantry_2", "logistics_1", *(["recon_2"] * 6)],
            player_id="p1",
            opponent_id="p2",
            game_id="ai-supply",
        )
        for ai_card, ai_lane in (("armor_1", "center"), ("infantry_2", "right")):
            submit_order(state, "p1", "infantry_2", "left")
            submit_order(state, "p2", ai_card, ai_lane)
            resolve_round(state)

        order = choose_ai_order(state, "p2")

        self.assertEqual((order.card_id, order.lane_id), ("logistics_1", "center"))

    def test_ai_sends_recon_to_the_hidden_enemy_threat(self) -> None:
        state = new_game(
            ["infantry_2"] * MAX_ROUNDS,
            ["infantry_2", "infantry_1", "recon_1", *(["recon_2"] * 6)],
            player_id="p1",
            opponent_id="p2",
            game_id="ai-recon",
        )
        for ai_card, ai_lane in (("infantry_2", "right"), ("infantry_1", "left")):
            submit_order(state, "p1", "infantry_2", "center")
            submit_order(state, "p2", ai_card, ai_lane)
            resolve_round(state)

        order = choose_ai_order(state, "p2")

        self.assertEqual((order.card_id, order.lane_id), ("recon_1", "center"))

    def test_legacy_formation_argument_is_ignored(self) -> None:
        state = self.make_game()
        metadata = card_metadata("infantry_2", "division")
        self.assertEqual(metadata, card_metadata("infantry_2"))
        self.assertNotIn("echelon", metadata)
        self.assertNotIn("formation", metadata)
        order = submit_order(state, "p1", "infantry_2", "center", "division")
        self.assertEqual(order.card_id, "infantry_2")
        self.assertFalse(hasattr(order, "formation_id"))
        self.assertNotIn("formation_id", order.to_dict())

    def test_legacy_saved_formation_is_ignored_and_log_omits_scale(self) -> None:
        state = self.make_game()
        submit_order(state, "p1", "infantry_1", "center")
        submit_order(state, "p2", "recon_2", "left")
        payload = state.to_dict()
        payload["orders"]["p1"]["formation_id"] = "division"
        state = GameState.from_dict(payload)
        self.assertNotIn("formation_id", state.orders["p1"].to_dict())

        resolve_round(state)
        event = next(
            item
            for item in state.events
            if item.kind == "own_card_deployed" and item.player_id == "p1"
        )
        self.assertIn("歩兵中隊", event.message)
        self.assertNotIn("部隊規模", event.message)

        payload = state.to_dict()
        own = next(
            item
            for item in payload["lanes"]["center"]["deployments"]
            if item["player_id"] == "p1"
        )
        own["formation_id"] = "division"
        restored = GameState.from_dict(payload)
        deployment = next(
            item
            for item in restored.lanes["center"].deployments
            if item.player_id == "p1"
        )
        self.assertNotIn("formation_id", deployment.to_dict())


if __name__ == "__main__":
    unittest.main()

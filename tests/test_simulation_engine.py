import json
import unittest

from advanced_game_data import (
    ADVANCED_CARDS,
    ADVANCED_STARTER_DECK,
    get_advanced_card,
)
from simulation_engine import (
    SIMULATION_ROUNDS,
    SimulationDeployment,
    SimulationOrder,
    SimulationPhase,
    SimulationRuleError,
    SimulationState,
    calculate_simulation_power,
    choose_simulation_ai_order,
    new_simulation,
    play_simulation_round,
    resolve_simulation_round,
    submit_simulation_order,
    validate_simulation_state,
)


class SimulationEngineTests(unittest.TestCase):
    def test_new_simulation_uses_24_card_catalog_deck_and_round_trips(self) -> None:
        state = new_simulation()
        self.assertEqual(state.max_rounds, 12)
        self.assertEqual(len(state.players["player"].hand), 24)
        payload = json.loads(json.dumps(state.to_dict(), ensure_ascii=False))
        restored = SimulationState.from_dict(payload)
        self.assertEqual(restored.to_dict(), state.to_dict())

    def test_invalid_or_short_decks_are_rejected(self) -> None:
        with self.assertRaises(SimulationRuleError):
            new_simulation(ADVANCED_STARTER_DECK[:11])
        with self.assertRaises(SimulationRuleError):
            new_simulation([*ADVANCED_STARTER_DECK[:11], "missing"])

    def test_legacy_scale_fields_are_ignored_when_loading(self) -> None:
        card = ADVANCED_CARDS[0]
        old_order = SimulationOrder.from_dict({
            "player_id": "player",
            "card_id": card.id,
            "theater_id": "north",
            "round_no": 1,
            "scale_id": "advanced_echelon_01",
        })
        old_deployment = SimulationDeployment.from_dict({
            "deployment_id": "legacy:1",
            "player_id": "player",
            "card_id": card.id,
            "theater_id": "north",
            "round_deployed": 1,
            "revealed_to": ["player"],
            "scale_id": "advanced_echelon_01",
        })
        self.assertNotIn("scale_id", old_order.to_dict())
        self.assertNotIn("scale_id", old_deployment.to_dict())
        self.assertFalse(hasattr(old_order, "scale_id"))
        self.assertFalse(hasattr(old_deployment, "scale_id"))

    def test_power_calculation_uses_printed_card_stats(self) -> None:
        card = ADVANCED_CARDS[0]
        state = new_simulation([card.id], max_rounds=1)
        state.theaters["central"].deployments.append(
            SimulationDeployment(
                "plain:1",
                "player",
                card.id,
                "central",
                1,
                ["player"],
            )
        )
        power = calculate_simulation_power(state, "central", "player")
        self.assertEqual(power.control, card.control)
        self.assertEqual(power.support, card.support)
        self.assertEqual(power.recon, card.recon)

    def test_deployment_event_names_only_the_card(self) -> None:
        card = ADVANCED_CARDS[0]
        state = new_simulation([card.id], max_rounds=1)
        submit_simulation_order(state, "player", card.id, "north")
        submit_simulation_order(state, "opponent", card.id, "south")
        resolve_simulation_round(state)
        self.assertTrue(any(card.name in event for event in state.events))
        self.assertTrue(all("部隊規模" not in event for event in state.events))

    def test_state_validation_rejects_nonplayable_cards(self) -> None:
        state = new_simulation()
        state.players["player"].hand[0] = "advanced_frames_01"
        with self.assertRaises(SimulationRuleError):
            validate_simulation_state(state)

    def test_power_explains_support_supply_command_mobility_and_domains(self) -> None:
        state = new_simulation()
        # Use a deterministic mixed-domain subset and deploy it directly through rounds.
        candidates = []
        for card in ADVANCED_CARDS:
            if (
                card.domain.value != "共通"
                and card.domain not in {item.domain for item in candidates}
            ):
                candidates.append(card)
            if len(candidates) == 3:
                break
        for round_no, card in enumerate(candidates, 1):
            state.round_no = round_no
            state.theaters["central"].deployments.append(
                SimulationDeployment(
                    f"test:{round_no}", "player", card.id, "central", round_no, ["player"]
                )
            )
        power = calculate_simulation_power(state, "central", "player")
        self.assertGreater(power.control, 0)
        self.assertEqual(power.active_support, power.support)
        self.assertGreaterEqual(power.command_bonus, 0)
        self.assertGreaterEqual(power.mobility_bonus, 0)
        self.assertEqual(power.domain_bonus, 4)
        self.assertGreaterEqual(power.total, 0)

    def test_orders_resolve_and_recon_reveals_in_the_same_theater(self) -> None:
        state = new_simulation()
        recon_card = max(
            (get_advanced_card(card_id) for card_id in ADVANCED_STARTER_DECK),
            key=lambda card: card.recon,
        )
        enemy_card = get_advanced_card(ADVANCED_STARTER_DECK[1])
        submit_simulation_order(state, "player", recon_card.id, "north")
        submit_simulation_order(state, "opponent", enemy_card.id, "north")
        self.assertIs(state.phase, SimulationPhase.RESOLVING)
        resolve_simulation_round(state)
        enemy = next(
            item for item in state.theaters["north"].deployments
            if item.player_id == "opponent"
        )
        self.assertTrue(enemy.visible_to("player"))
        self.assertEqual(state.round_no, 2)

    def test_advanced_ai_spreads_early_orders_across_theaters(self) -> None:
        state = new_simulation()
        chosen_theaters = []
        for _ in range(3):
            player_card = state.players["player"].hand[0]
            submit_simulation_order(state, "player", player_card, "central")
            ai = choose_simulation_ai_order(state, "opponent")
            chosen_theaters.append(ai.theater_id)
            submit_simulation_order(state, ai.player_id, ai.card_id, ai.theater_id)
            resolve_simulation_round(state)
        self.assertGreaterEqual(len(set(chosen_theaters)), 2)

    def test_full_twelve_turn_match_completes_with_a_result(self) -> None:
        state = new_simulation()
        for round_index in range(SIMULATION_ROUNDS):
            card_id = state.players["player"].hand[0]
            theater_id = ("north", "central", "south")[round_index % 3]
            play_simulation_round(state, "player", card_id, theater_id)
        self.assertIs(state.phase, SimulationPhase.COMPLETE)
        self.assertIsNotNone(state.result)
        self.assertEqual(state.result.rounds_played, SIMULATION_ROUNDS)
        json.dumps(state.to_dict(), ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()

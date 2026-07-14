import json
import unittest

from advanced_game_data import (
    ADVANCED_CARDS,
    ADVANCED_STARTER_DECK,
    get_advanced_card,
)
from simulation_engine import (
    SIMULATION_ROUNDS,
    THEATER_IDS,
    THEATER_LABELS,
    SimulationDeployment,
    SimulationOrder,
    SimulationPhase,
    SimulationRuleError,
    SimulationState,
    calculate_simulation_power,
    card_allowed_in_theater,
    choose_simulation_ai_order,
    current_time_of_day,
    new_simulation,
    play_simulation_round,
    resolve_simulation_round,
    submit_simulation_order,
    time_of_day_for_round,
    validate_simulation_state,
)


class SimulationEngineTests(unittest.TestCase):
    @staticmethod
    def _card_in_family(family: str):
        return next(card for card in ADVANCED_CARDS if card.family == family)

    @staticmethod
    def _deck_with(*required_cards, size: int = 2) -> list[str]:
        ids: list[str] = []
        for card in (*required_cards, *ADVANCED_CARDS):
            if card.id not in ids:
                ids.append(card.id)
            if len(ids) >= size:
                break
        return ids

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
        card = self._card_in_family("infantry")
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
        card = self._card_in_family("infantry")
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
                card_allowed_in_theater(card, "central")
                and
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
            (
                get_advanced_card(card_id)
                for card_id in ADVANCED_STARTER_DECK
                if card_allowed_in_theater(card_id, "north")
            ),
            key=lambda card: card.recon,
        )
        enemy_card = next(
            get_advanced_card(card_id)
            for card_id in ADVANCED_STARTER_DECK
            if card_id != recon_card.id and card_allowed_in_theater(card_id, "north")
        )
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
            player_card = next(
                card_id for card_id in state.players["player"].hand
                if card_allowed_in_theater(card_id, "central")
            )
            submit_simulation_order(state, "player", player_card, "central")
            ai = choose_simulation_ai_order(state, "opponent")
            chosen_theaters.append(ai.theater_id)
            submit_simulation_order(state, ai.player_id, ai.card_id, ai.theater_id)
            resolve_simulation_round(state)
        self.assertGreaterEqual(len(set(chosen_theaters)), 2)

    def test_naval_theater_restricts_cards_and_land_rejects_naval_units(self) -> None:
        naval = self._card_in_family("naval_units")
        aviation = self._card_in_family("aviation_units")
        infantry = self._card_in_family("infantry")

        self.assertEqual(THEATER_IDS, ("north", "central", "south", "naval"))
        self.assertEqual(THEATER_LABELS["naval"], "海上作戦域")
        self.assertTrue(card_allowed_in_theater(naval, "naval"))
        self.assertFalse(card_allowed_in_theater(naval, "north"))
        self.assertTrue(card_allowed_in_theater(aviation, "naval"))
        self.assertTrue(card_allowed_in_theater(aviation, "central"))
        self.assertFalse(card_allowed_in_theater(infantry, "naval"))
        self.assertFalse(card_allowed_in_theater("missing", "naval"))

        state = new_simulation([naval.id], max_rounds=1)
        with self.assertRaisesRegex(SimulationRuleError, "配置できません"):
            submit_simulation_order(state, "player", naval.id, "north")
        submit_simulation_order(state, "player", naval.id, "naval")

        state = new_simulation([infantry.id], max_rounds=1)
        with self.assertRaisesRegex(SimulationRuleError, "配置できません"):
            submit_simulation_order(state, "player", infantry.id, "naval")

    def test_old_three_theater_save_gains_an_empty_naval_theater(self) -> None:
        state = new_simulation()
        payload = state.to_dict()
        payload["theaters"].pop("naval")
        restored = SimulationState.from_dict(payload)
        self.assertEqual(set(restored.theaters), set(THEATER_IDS))
        self.assertEqual(restored.theaters["naval"].label, "海上作戦域")
        self.assertEqual(restored.theaters["naval"].deployments, [])

    def test_validation_rejects_a_card_in_a_forbidden_theater(self) -> None:
        naval = self._card_in_family("naval_units")
        state = new_simulation([naval.id], max_rounds=1)
        state.theaters["north"].deployments.append(
            SimulationDeployment("illegal", "player", naval.id, "north", 1, ["player"])
        )
        with self.assertRaises(SimulationRuleError):
            validate_simulation_state(state)

    def test_day_and_night_alternate_and_all_designated_families_are_penalized(self) -> None:
        self.assertEqual(time_of_day_for_round(1), "昼")
        self.assertEqual(time_of_day_for_round(2), "夜")
        self.assertEqual(time_of_day_for_round(3), "昼")
        with self.assertRaises(SimulationRuleError):
            time_of_day_for_round(0)

        affected_families = (
            "aviation_units",
            "infantry_support",
            "armor",
            "artillery",
            "air_antiarmor",
            "information_support",
        )
        for family in affected_families:
            with self.subTest(family=family):
                card = self._card_in_family(family)
                state = new_simulation(
                    self._deck_with(card, size=2),
                    max_rounds=2,
                )
                state.round_no = 2
                state.theaters["central"].deployments.append(
                    SimulationDeployment(
                        f"night:{family}", "player", card.id, "central", 1, ["player"]
                    )
                )
                power = calculate_simulation_power(state, "central", "player")
                expected = {
                    field: max(0, getattr(card, field) - 1)
                    for field in ("control", "support", "recon", "mobility")
                }
                self.assertEqual(power.control, expected["control"])
                self.assertEqual(power.support, expected["support"])
                self.assertEqual(power.recon, expected["recon"])
                self.assertEqual(power.mobility, expected["mobility"])
                self.assertEqual(power.command, card.command)
                expected_penalty = sum(
                    getattr(card, field) - expected[field] for field in expected
                )
                self.assertEqual(power.night_penalty, expected_penalty)
                self.assertEqual(
                    power.night_mobility_penalty,
                    card.mobility - expected["mobility"],
                )

        unaffected = self._card_in_family("infantry")
        state = new_simulation(self._deck_with(unaffected, size=2), max_rounds=2)
        state.round_no = 2
        state.theaters["central"].deployments.append(
            SimulationDeployment(
                "night:unaffected", "player", unaffected.id, "central", 1, ["player"]
            )
        )
        power = calculate_simulation_power(state, "central", "player")
        self.assertEqual(power.night_penalty, 0)
        self.assertEqual(power.control, unaffected.control)
        self.assertEqual(power.support, unaffected.support)
        self.assertEqual(power.recon, unaffected.recon)
        self.assertEqual(power.mobility, unaffected.mobility)
        self.assertEqual(power.command, unaffected.command)

    def test_family_and_aviation_coordination_bonuses_are_capped(self) -> None:
        family_cards = [
            card for card in ADVANCED_CARDS
            if card.family == "infantry"
        ][:4]
        self.assertEqual(len(family_cards), 4)
        state = new_simulation([card.id for card in family_cards], max_rounds=1)
        for index, card in enumerate(family_cards, 1):
            state.theaters["central"].deployments.append(
                SimulationDeployment(
                    f"family:{index}", "player", card.id, "central", 1, ["player"]
                )
            )
        power = calculate_simulation_power(state, "central", "player")
        self.assertEqual(power.family_bonus, 6)

        keywords = (
            "航空母艦", "航空戦艦", "航空巡洋艦", "空軍", "航空管制", "早期警戒管制"
        )
        aviation_cards = [
            card for card in ADVANCED_CARDS
            if any(keyword in card.name for keyword in keywords)
        ]
        pair_and_theater = next(
            (first, second, theater_id)
            for first in aviation_cards
            for second in aviation_cards
            if first.id != second.id
            for theater_id in THEATER_IDS
            if card_allowed_in_theater(first, theater_id)
            and card_allowed_in_theater(second, theater_id)
        )
        first, second, theater_id = pair_and_theater
        state = new_simulation([first.id, second.id], max_rounds=1)
        for index, card in enumerate((first, second), 1):
            state.theaters[theater_id].deployments.append(
                SimulationDeployment(
                    f"aviation:{index}", "player", card.id, theater_id, 1, ["player"]
                )
            )
        self.assertEqual(
            calculate_simulation_power(state, theater_id, "player").aviation_bonus,
            2,
        )

        # Four qualifying deployments would produce +6, and any further cards
        # remain capped at +6.
        state = new_simulation([first.id], max_rounds=1)
        for index in range(5):
            state.theaters[theater_id].deployments.append(
                SimulationDeployment(
                    f"aviation-cap:{index}",
                    "player",
                    first.id,
                    theater_id,
                    1,
                    ["player"],
                )
            )
        self.assertEqual(
            calculate_simulation_power(state, theater_id, "player").aviation_bonus,
            6,
        )

    def test_ai_only_evaluates_theaters_legal_for_its_card(self) -> None:
        naval = self._card_in_family("naval_units")
        naval_state = new_simulation([naval.id], max_rounds=1)
        naval_order = choose_simulation_ai_order(naval_state, "opponent")
        self.assertEqual(naval_order.theater_id, "naval")

        infantry = self._card_in_family("infantry")
        land_state = new_simulation([infantry.id], max_rounds=1)
        land_order = choose_simulation_ai_order(land_state, "opponent")
        self.assertIn(land_order.theater_id, {"north", "central", "south"})

    def test_four_theaters_score_and_events_record_day_and_night(self) -> None:
        aviation_cards = [
            card for card in ADVANCED_CARDS if card.family == "aviation_units"
        ][:2]
        state = new_simulation(
            [card.id for card in aviation_cards],
            max_rounds=2,
        )
        self.assertEqual(current_time_of_day(state), "昼")
        submit_simulation_order(state, "player", aviation_cards[0].id, "north")
        submit_simulation_order(state, "opponent", aviation_cards[0].id, "naval")
        resolve_simulation_round(state)
        self.assertEqual(state.players["player"].mission_points, 1)
        self.assertEqual(state.players["opponent"].mission_points, 1)
        self.assertTrue(any("（昼）" in event for event in state.events))
        self.assertTrue(all(len(theater.round_winners) == 1 for theater in state.theaters.values()))

        self.assertEqual(current_time_of_day(state), "夜")
        submit_simulation_order(state, "player", aviation_cards[1].id, "central")
        submit_simulation_order(state, "opponent", aviation_cards[1].id, "south")
        resolve_simulation_round(state)
        self.assertTrue(any("（夜）" in event for event in state.events))
        self.assertTrue(all(len(theater.round_winners) == 2 for theater in state.theaters.values()))
        self.assertIsNotNone(state.result)
        self.assertLessEqual(max(state.result.theaters_controlled.values()), 4)

    def test_full_twelve_turn_match_completes_with_a_result(self) -> None:
        state = new_simulation()
        for round_index in range(SIMULATION_ROUNDS):
            card_id = state.players["player"].hand[0]
            preferred = THEATER_IDS[round_index % len(THEATER_IDS)]
            theater_id = (
                preferred
                if card_allowed_in_theater(card_id, preferred)
                else next(
                    item for item in THEATER_IDS
                    if card_allowed_in_theater(card_id, item)
                )
            )
            play_simulation_round(state, "player", card_id, theater_id)
        self.assertIs(state.phase, SimulationPhase.COMPLETE)
        self.assertIsNotNone(state.result)
        self.assertEqual(state.result.rounds_played, SIMULATION_ROUNDS)
        json.dumps(state.to_dict(), ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()

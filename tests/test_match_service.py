import json
import unittest

from game_data import CARDS
from game_engine import MAX_ROUNDS, Phase
from match_service import (
    ACTIVE_MATCH_KEY,
    RECORDED_MATCH_IDS_KEY,
    abandon_match,
    collection_rewards_for_outcome,
    get_match_context,
    load_match,
    play_player_round,
    restart_match,
    start_match,
)
from player_state import (
    PLAYER_STATE_KEY,
    default_player_state,
    store_player_state,
    update_formation,
    update_mode,
)
from symbol_catalog import SYMBOL_CATALOG


class MatchServiceTests(unittest.TestCase):
    def make_storage(self) -> dict:
        state = default_player_state()
        state = update_mode(state, "ranked")
        state = update_formation(state, "division")
        storage: dict = {}
        store_player_state(storage, state)
        return storage

    def test_start_snapshots_settings_and_load_round_trips(self) -> None:
        storage = self.make_storage()

        started = start_match(storage)
        context = get_match_context(storage)
        loaded = load_match(storage)

        self.assertIsNotNone(context)
        self.assertEqual(context["mode"], "ranked")
        self.assertEqual(context["formation"], "division")
        self.assertEqual(context["deck"], storage[PLAYER_STATE_KEY]["deck"])
        self.assertEqual(started.max_rounds, MAX_ROUNDS)
        self.assertEqual(loaded.to_dict(), started.to_dict())
        self.assertEqual(start_match(storage).game_id, started.game_id)
        json.dumps(storage[ACTIVE_MATCH_KEY], ensure_ascii=False)

    def test_play_round_uses_snapshotted_formation_and_persists(self) -> None:
        storage = self.make_storage()
        state = start_match(storage)
        first_card = state.players["player"].hand[0]

        advanced, resolution = play_player_round(storage, first_card, "center")

        self.assertEqual(resolution.round_no, 1)
        self.assertEqual(advanced.round_no, 2)
        own_deployment = next(
            deployment
            for deployment in advanced.lanes["center"].deployments
            if deployment.player_id == "player"
        )
        self.assertEqual(own_deployment.formation_id, "division")
        self.assertEqual(load_match(storage).to_dict(), advanced.to_dict())

    def test_final_result_is_recorded_only_once(self) -> None:
        storage = self.make_storage()
        state = start_match(storage)

        while state.phase is not Phase.COMPLETE:
            card_id = state.players["player"].hand[0]
            state, _ = play_player_round(storage, card_id, "center")

        player = storage[PLAYER_STATE_KEY]
        self.assertEqual(player["stats"]["battles_played"], 1)
        self.assertEqual(len(player["battle_history"]), 1)
        self.assertEqual(player["battle_history"][0]["mode"], "ranked")
        self.assertEqual(player["battle_history"][0]["formation"], "division")
        self.assertIn(state.game_id, storage[RECORDED_MATCH_IDS_KEY])
        self.assertTrue(storage[ACTIVE_MATCH_KEY]["result_recorded"])

        # Re-loading a completed game reconciles the save but never duplicates it.
        load_match(storage)
        start_match(storage)
        self.assertEqual(storage[PLAYER_STATE_KEY]["stats"]["battles_played"], 1)
        self.assertEqual(len(storage[PLAYER_STATE_KEY]["battle_history"]), 1)
        json.dumps(storage, ensure_ascii=False)

    def test_completion_unlocks_ordered_progress_rewards_once(self) -> None:
        storage = self.make_storage()
        expected_by_outcome = {
            outcome: collection_rewards_for_outcome(storage[PLAYER_STATE_KEY], outcome)
            for outcome in ("win", "draw", "loss")
        }
        state = start_match(storage)

        while state.phase is not Phase.COMPLETE:
            card_id = state.players["player"].hand[0]
            state, _ = play_player_round(storage, card_id, "right")

        context = get_match_context(storage)
        if state.result.winner_id is None:
            outcome = "draw"
        else:
            outcome = "win" if state.result.winner_id == "player" else "loss"
        expected = expected_by_outcome[outcome]
        self.assertEqual(context["rewards"], expected)
        collection = storage[PLAYER_STATE_KEY]["collection"]
        self.assertTrue(set(expected["cards"]).issubset(collection["owned_cards"]))
        self.assertTrue(set(expected["symbols"]).issubset(collection["unlocked_symbols"]))

        owned_after = list(collection["owned_cards"])
        symbols_after = list(collection["unlocked_symbols"])
        self.assertEqual(load_match(storage).game_id, state.game_id)
        self.assertEqual(get_match_context(storage)["rewards"], context["rewards"])
        self.assertEqual(
            storage[PLAYER_STATE_KEY]["collection"]["owned_cards"], owned_after
        )
        self.assertEqual(
            storage[PLAYER_STATE_KEY]["collection"]["unlocked_symbols"], symbols_after
        )
        self.assertEqual(storage[PLAYER_STATE_KEY]["stats"]["battles_played"], 1)
        json.dumps(storage[ACTIVE_MATCH_KEY], ensure_ascii=False)

    def test_reward_policy_varies_by_outcome_and_stops_when_exhausted(self) -> None:
        state = default_player_state()
        win = collection_rewards_for_outcome(state, "win")
        draw = collection_rewards_for_outcome(state, "draw")
        loss = collection_rewards_for_outcome(state, "loss")

        self.assertEqual(len(win["cards"]), 1)
        self.assertEqual(len(win["symbols"]), 12)
        self.assertEqual(draw["cards"], [])
        self.assertEqual(len(draw["symbols"]), 3)
        self.assertEqual(loss["cards"], [])
        self.assertEqual(len(loss["symbols"]), 1)

        state["collection"]["owned_cards"] = [card.id for card in CARDS]
        state["collection"]["unlocked_symbols"] = [
            symbol.id for symbol in SYMBOL_CATALOG
        ]
        for outcome in ("win", "draw", "loss"):
            self.assertEqual(
                collection_rewards_for_outcome(state, outcome),
                {"cards": [], "symbols": []},
            )
        with self.assertRaises(ValueError):
            collection_rewards_for_outcome(state, "abandoned")

    def test_abandon_and_restart_have_clear_lifecycle(self) -> None:
        storage = self.make_storage()
        first = start_match(storage)

        self.assertTrue(abandon_match(storage))
        self.assertNotIn(ACTIVE_MATCH_KEY, storage)
        self.assertFalse(abandon_match(storage))

        second = restart_match(storage)
        self.assertNotEqual(first.game_id, second.game_id)
        third = restart_match(storage)
        self.assertNotEqual(second.game_id, third.game_id)

    def test_corrupt_save_is_discarded_and_can_be_restarted(self) -> None:
        storage = self.make_storage()
        storage[ACTIVE_MATCH_KEY] = {"service_version": 1, "game": {"bad": True}}

        self.assertIsNone(load_match(storage))
        self.assertNotIn(ACTIVE_MATCH_KEY, storage)
        self.assertIsNotNone(start_match(storage))


if __name__ == "__main__":
    unittest.main()

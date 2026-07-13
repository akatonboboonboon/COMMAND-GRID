import json
import unittest
from unittest.mock import patch

from game_engine import MAX_ROUNDS, RuleViolation
from multiplayer_service import (
    MultiplayerError,
    cancel_waiting,
    claim_result,
    close_session,
    create_friend_room,
    disconnect,
    ensure_player_token,
    join_friend_room,
    join_queue,
    leave,
    poll,
    reset_service_for_tests,
    submit_player_order,
)
from player_state import (
    ensure_player_state,
    store_player_state,
    update_profile,
    update_selected_symbol,
)
from symbol_catalog import SYMBOL_CATALOG


class MultiplayerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_service_for_tests()
        self.alice: dict = {"player_name": "Alice"}
        self.bob: dict = {"player_name": "Bob"}

    def _pair(self, mode: str = "casual") -> tuple[dict, dict]:
        waiting = join_queue(self.alice, mode)
        self.assertEqual(waiting["status"], "waiting")
        bob_view = join_queue(self.bob, mode)
        self.assertEqual(bob_view["status"], "playing")
        alice_view = poll(self.alice)
        self.assertEqual(alice_view["match_id"], bob_view["match_id"])
        return alice_view, bob_view

    @staticmethod
    def _first_card(view: dict) -> str:
        player_id = view["player_id"]
        return view["game"]["players"][player_id]["hand"][0]

    def test_queue_nine_rounds_and_each_result_is_claimed_once(self) -> None:
        initial = ensure_player_state(self.alice)
        expected_cards: list[str] = []
        expected_symbols = [
            symbol.id
            for symbol in SYMBOL_CATALOG
            if symbol.id not in set(initial["collection"]["unlocked_symbols"])
        ][:3]
        alice_view, bob_view = self._pair("ranked")
        self.assertNotEqual(ensure_player_token(self.alice), ensure_player_token(self.bob))

        for round_no in range(1, MAX_ROUNDS + 1):
            alice_view = poll(self.alice)
            bob_view = poll(self.bob)
            self.assertEqual(alice_view["game"]["round_no"], round_no)
            submit_player_order(self.alice, self._first_card(alice_view), "left")
            after_resolution = submit_player_order(self.bob, self._first_card(bob_view), "right")

        self.assertEqual(after_resolution["status"], "complete")
        self.assertEqual(after_resolution["game"]["phase"], "complete")
        alice_claim = claim_result(self.alice)
        bob_claim = claim_result(self.bob)
        self.assertTrue(alice_claim["claimed"])
        self.assertTrue(bob_claim["claimed"])
        self.assertEqual(alice_claim["outcome"], "draw")
        self.assertEqual(bob_claim["outcome"], "draw")
        self.assertEqual(alice_claim["stats"]["battles_played"], 1)
        self.assertEqual(bob_claim["stats"]["battles_played"], 1)
        self.assertEqual(alice_claim["history_entry"]["mode"], "ranked")
        self.assertEqual(alice_claim["history_entry"]["opponent"], "Bob")
        self.assertEqual(alice_claim["rewards"]["cards"], expected_cards)
        self.assertEqual(alice_claim["rewards"]["symbols"], expected_symbols)
        self.assertEqual(
            len(alice_claim["rewards"]["cards"]),
            len(set(alice_claim["rewards"]["cards"])),
        )
        self.assertEqual(
            len(alice_claim["rewards"]["symbols"]),
            len(set(alice_claim["rewards"]["symbols"])),
        )
        collection = ensure_player_state(self.alice)["collection"]
        self.assertTrue(set(expected_cards).issubset(collection["owned_cards"]))
        self.assertTrue(set(expected_symbols).issubset(collection["unlocked_symbols"]))

        duplicate = claim_result(self.alice)
        self.assertFalse(duplicate["claimed"])
        self.assertEqual(duplicate["reason"], "already_claimed")
        self.assertEqual(duplicate["rewards"], alice_claim["rewards"])
        self.assertEqual(ensure_player_state(self.alice)["stats"]["battles_played"], 1)

        # Every service response intended for the UI remains JSON-safe.
        json.dumps(poll(self.alice))
        json.dumps(alice_claim)

    def test_friend_code_starts_exactly_one_match(self) -> None:
        room = create_friend_room(self.alice, name="Alpha")
        self.assertEqual(room["status"], "waiting_friend")
        self.assertEqual(len(room["room_code"]), 6)
        self.assertEqual(poll(self.alice)["room_code"], room["room_code"])

        joined = join_friend_room(self.bob, room["room_code"].lower(), name="Bravo")
        self.assertEqual(joined["status"], "playing")
        self.assertEqual(joined["mode"], "friend")
        self.assertEqual(poll(self.alice)["opponent"]["name"], "Bravo")

        charlie: dict = {}
        with self.assertRaises(MultiplayerError) as context:
            join_friend_room(charlie, room["room_code"])
        self.assertEqual(context.exception.code, "room_not_found")

    def test_legacy_formation_arguments_are_ignored(self) -> None:
        waiting = join_queue(self.alice, "casual", formation="division")
        self.assertNotIn("formation", waiting)
        joined = join_queue(self.bob, "casual", formation="obsolete-value")
        self.assertEqual(joined["status"], "playing")
        self.assertNotIn("formation", joined)
        self.assertNotIn("formation", poll(self.alice))

    def test_default_match_name_comes_from_player_profile(self) -> None:
        state = ensure_player_state(self.alice)
        state = update_profile(state, display_name="Profile Alice")
        selected_symbol = state["collection"]["unlocked_symbols"][-1]
        state = update_selected_symbol(state, selected_symbol)
        store_player_state(self.alice, state)
        room = create_friend_room(self.alice)
        join_friend_room(self.bob, room["room_code"])
        bob_view = poll(self.bob)
        alice_view = poll(self.alice)
        self.assertEqual(bob_view["opponent"]["name"], "Profile Alice")
        self.assertEqual(bob_view["opponent"]["icon_symbol_id"], selected_symbol)
        self.assertEqual(alice_view["player"]["icon_symbol_id"], selected_symbol)
        self.assertEqual(
            alice_view["opponent"]["icon_symbol_id"],
            bob_view["player"]["icon_symbol_id"],
        )

    def test_pending_order_and_opponent_secrets_are_redacted(self) -> None:
        alice_view, _ = self._pair()
        alice_id = alice_view["player_id"]
        alice_card = self._first_card(alice_view)
        own_pending = submit_player_order(self.alice, alice_card, "center")
        self.assertEqual(own_pending["game"]["orders"][alice_id]["card_id"], alice_card)

        bob_pending = poll(self.bob)
        bob_id = bob_pending["player_id"]
        opponent_id = next(key for key in bob_pending["game"]["players"] if key != bob_id)
        self.assertNotIn("hand", bob_pending["game"]["players"][opponent_id])
        self.assertNotIn("draw_pile", bob_pending["game"]["players"][opponent_id])
        self.assertEqual(
            bob_pending["game"]["orders"][opponent_id],
            {"player_id": opponent_id, "submitted": True},
        )

        with self.assertRaises(RuleViolation) as context:
            submit_player_order(self.alice, alice_card, "left")
        self.assertEqual(context.exception.code, "order_already_submitted")
        with self.assertRaises(RuleViolation) as context:
            submit_player_order(self.bob, "not-a-card", "left")
        self.assertEqual(context.exception.code, "unknown_card")

    def test_disconnect_reconnect_leave_and_invalid_operations(self) -> None:
        self._pair()
        disconnected = disconnect(self.alice)
        self.assertTrue(disconnected["disconnected"])
        self.assertFalse(poll(self.bob)["opponent"]["connected"])
        self.assertTrue(poll(self.alice)["opponent"]["connected"])
        self.assertTrue(poll(self.bob)["opponent"]["connected"])

        left = leave(self.alice)
        self.assertEqual(left["status"], "left")
        opponent_view = poll(self.bob)
        self.assertEqual(opponent_view["status"], "complete")
        self.assertTrue(opponent_view["opponent"]["left"])
        self.assertEqual(
            opponent_view["game"]["result"]["winner_id"],
            opponent_view["player_id"],
        )
        bob_result = claim_result(self.bob)
        self.assertTrue(bob_result["claimed"])
        self.assertEqual(bob_result["outcome"], "win")
        self.assertEqual(len(bob_result["rewards"]["cards"]), 1)
        self.assertEqual(len(bob_result["rewards"]["symbols"]), 12)
        alice_result = claim_result(self.alice)
        self.assertTrue(alice_result["claimed"])
        self.assertEqual(alice_result["outcome"], "loss")
        self.assertEqual(alice_result["rewards"]["cards"], [])
        self.assertEqual(len(alice_result["rewards"]["symbols"]), 1)
        with self.assertRaises(MultiplayerError) as context:
            submit_player_order(self.bob, self._first_card(opponent_view), "left")
        self.assertEqual(context.exception.code, "opponent_left")

        outsider: dict = {}
        self.assertEqual(poll(outsider)["status"], "idle")
        with self.assertRaises(MultiplayerError) as context:
            submit_player_order(outsider, "infantry_1", "left")
        self.assertEqual(context.exception.code, "no_active_match")

    def test_close_requires_completed_or_left_and_gc_after_both_close(self) -> None:
        self._pair()
        with self.assertRaises(MultiplayerError) as context:
            close_session(self.alice)
        self.assertEqual(context.exception.code, "match_in_progress")

        leave(self.alice)
        first_close = close_session(self.alice)
        self.assertTrue(first_close["closed"])
        self.assertFalse(first_close["garbage_collected"])
        self.assertEqual(ensure_player_state(self.alice)["stats"]["losses"], 1)
        self.assertEqual(poll(self.alice)["status"], "idle")
        self.assertEqual(join_queue(self.alice, "ranked")["status"], "waiting")

        # Alice's exit completed the old match as Bob's forfeit win.
        second_close = close_session(self.bob)
        self.assertTrue(second_close["garbage_collected"])
        self.assertEqual(second_close["match_id"], first_close["match_id"])
        self.assertEqual(ensure_player_state(self.bob)["stats"]["wins"], 1)
        self.assertEqual(poll(self.alice)["status"], "waiting")

    def test_close_completed_session_auto_claims_before_next_match(self) -> None:
        self._pair()
        for _ in range(MAX_ROUNDS):
            alice_view = poll(self.alice)
            bob_view = poll(self.bob)
            submit_player_order(self.alice, self._first_card(alice_view), "left")
            submit_player_order(self.bob, self._first_card(bob_view), "right")

        alice_close = close_session(self.alice)
        self.assertTrue(alice_close["closed"])
        self.assertEqual(ensure_player_state(self.alice)["stats"]["battles_played"], 1)
        self.assertEqual(join_queue(self.alice, "casual")["status"], "waiting")
        bob_close = close_session(self.bob)
        self.assertTrue(bob_close["garbage_collected"])

    def test_invalid_queue_mode_and_short_deck_are_rejected(self) -> None:
        with self.assertRaises(MultiplayerError) as context:
            join_queue(self.alice, "training")
        self.assertEqual(context.exception.code, "invalid_mode")
        with self.assertRaises(MultiplayerError) as context:
            join_queue(self.alice, "casual", deck=["infantry_1"])
        self.assertEqual(context.exception.code, "deck_too_small")

    def test_cancelled_waiter_cannot_become_a_ghost_opponent(self) -> None:
        self.assertEqual(join_queue(self.alice, "casual")["status"], "waiting")
        self.assertTrue(cancel_waiting(self.alice)["cancelled"])

        bob_view = join_queue(self.bob, "casual")

        self.assertEqual(bob_view["status"], "waiting")

    def test_stale_waiter_expires_before_pairing(self) -> None:
        with patch("multiplayer_service.monotonic", return_value=100.0):
            self.assertEqual(join_queue(self.alice, "casual")["status"], "waiting")
        with patch("multiplayer_service.monotonic", return_value=121.0):
            bob_view = join_queue(self.bob, "casual")

        self.assertEqual(bob_view["status"], "waiting")
        self.assertEqual(poll(self.alice)["status"], "idle")


if __name__ == "__main__":
    unittest.main()

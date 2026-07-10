import json
import unittest
from datetime import datetime, timezone

from game_data import STARTER_DECK
from player_state import (
    MAX_BATTLE_HISTORY,
    PLAYER_STATE_KEY,
    PREFERENCE_DEFAULTS,
    default_player_state,
    ensure_player_state,
    normalize_player_state,
    record_result,
    store_player_state,
    unlock_collection,
    update_deck,
    update_formation,
    update_mode,
    update_preference,
    update_profile,
    update_selected_symbol,
)


class PlayerStateTests(unittest.TestCase):
    def test_default_state_is_detached_and_json_serializable(self) -> None:
        first = default_player_state()
        second = default_player_state()
        first["preferences"]["beginner_mode"] = False
        first["deck"].clear()

        self.assertTrue(second["preferences"]["beginner_mode"])
        self.assertEqual(second["deck"], list(STARTER_DECK))
        self.assertEqual(second["profile"]["display_name"], "COMMANDER")
        self.assertEqual(second["profile"]["tagline"], "偵察から覚えています")
        self.assertEqual(
            second["profile"]["selected_symbol"],
            second["collection"]["unlocked_symbols"][0],
        )
        json.dumps(second)

    def test_profile_normalizes_nested_and_legacy_root_values(self) -> None:
        legacy = normalize_player_state(
            {
                "player_name": "  Field   Fox  ",
                "tagline": "  補給から   覚えています  ",
            }
        )
        self.assertEqual(legacy["profile"]["display_name"], "Field Fox")
        self.assertEqual(legacy["profile"]["tagline"], "補給から 覚えています")

        nested = normalize_player_state(
            {
                "display_name": "Legacy Name",
                "tagline": "legacy",
                "profile": {"display_name": "SCOUT", "tagline": "索敵担当"},
            }
        )
        self.assertEqual(nested["profile"]["display_name"], "SCOUT")
        self.assertEqual(nested["profile"]["tagline"], "索敵担当")

        repaired = normalize_player_state(
            {
                "profile": {
                    "display_name": "X",
                    "tagline": "長" * 61,
                }
            }
        )
        self.assertEqual(repaired["profile"]["display_name"], "COMMANDER")
        self.assertEqual(repaired["profile"]["tagline"], "偵察から覚えています")
        json.dumps(repaired)

    def test_selected_symbol_is_normalized_to_an_unlocked_symbol(self) -> None:
        baseline = default_player_state()
        fallback = baseline["collection"]["unlocked_symbols"][0]
        locked_symbol = "infantry_09"
        self.assertNotIn(locked_symbol, baseline["collection"]["unlocked_symbols"])

        unknown = normalize_player_state(
            {"profile": {"selected_symbol": "not_a_symbol"}}
        )
        locked = normalize_player_state(
            {"profile": {"selected_symbol": locked_symbol}}
        )
        self.assertEqual(unknown["profile"]["selected_symbol"], fallback)
        self.assertEqual(locked["profile"]["selected_symbol"], fallback)

        migrated = normalize_player_state({"selected_symbol": fallback})
        self.assertEqual(migrated["profile"]["selected_symbol"], fallback)

    def test_malformed_legacy_state_is_safely_normalized(self) -> None:
        raw = {
            "schema_version": "old",
            "preferences": {
                "beginner_mode": "false",
                "text_size": "large",
                "reduce_motion": "yes",
                "profile_visibility": "everyone",
                "unknown_setting": True,
            },
            "collection": {
                "cards": {
                    "infantry_1": {"copies": 2},
                    "not_a_card": True,
                },
                "unlocked_symbols": ["infantry_01", "not_a_symbol", 4],
                "unlocked_formations": ["師団", "space_army"],
            },
            "deck": ["infantry_1", "infantry_1", "not_a_card", 7],
            "formation": "師団",
            "mode": "ランク対戦",
            "history": [
                {
                    "result": "勝利",
                    "points": "4",
                    "turns": "6",
                    "deck": ["infantry_1", "not_a_card"],
                },
                "broken",
                {"result": "unknown"},
            ],
            "stats": {"played": -12, "wins": "bad", "mission_points": -1},
        }

        state = normalize_player_state(raw)

        self.assertFalse(state["preferences"]["beginner_mode"])
        self.assertEqual(state["preferences"]["font_size"], "large")
        self.assertTrue(state["preferences"]["reduce_motion"])
        self.assertEqual(state["preferences"]["profile_visibility"], "friends")
        self.assertEqual(set(state["preferences"]), set(PREFERENCE_DEFAULTS))
        self.assertEqual(state["deck"], ["infantry_1"])
        self.assertEqual(state["selected_formation"], "division")
        self.assertEqual(state["selected_mode"], "ranked")
        self.assertEqual(len(state["battle_history"]), 1)
        self.assertEqual(state["battle_history"][0]["mission_points_for"], 4)
        self.assertEqual(state["stats"]["battles_played"], 1)
        self.assertEqual(state["stats"]["wins"], 1)
        self.assertEqual(state["stats"]["mission_points_earned"], 4)
        json.dumps(state)

    def test_storage_helper_migrates_legacy_root_keys_and_persists(self) -> None:
        storage = {
            "deck": ["infantry_1", "recon_1"],
            "beginner_mode": False,
            "mode": "casual",
        }

        loaded = ensure_player_state(storage)

        self.assertIn(PLAYER_STATE_KEY, storage)
        self.assertEqual(loaded["deck"], ["infantry_1", "recon_1"])
        self.assertFalse(loaded["preferences"]["beginner_mode"])
        self.assertEqual(loaded["selected_mode"], "casual")
        loaded["deck"].clear()
        self.assertEqual(
            storage[PLAYER_STATE_KEY]["deck"], ["infantry_1", "recon_1"]
        )

        persisted = store_player_state(storage, {"mode": "friend", "deck": []})
        self.assertEqual(persisted["selected_mode"], "friend")
        self.assertEqual(storage[PLAYER_STATE_KEY], persisted)

    def test_update_helpers_validate_inputs_without_mutating_source(self) -> None:
        original = default_player_state()
        changed = update_preference(original, "high_contrast", True)
        changed = update_mode(changed, "フレンド対戦")
        changed = update_formation(changed, "師団")
        changed = update_deck(changed, ["infantry_1", "recon_1"])

        self.assertFalse(original["preferences"]["high_contrast"])
        self.assertEqual(original["selected_mode"], "training")
        self.assertEqual(original["selected_formation"], "native")
        self.assertTrue(changed["preferences"]["high_contrast"])
        self.assertEqual(changed["selected_mode"], "friend")
        self.assertEqual(changed["selected_formation"], "division")
        self.assertEqual(changed["deck"], ["infantry_1", "recon_1"])

        with self.assertRaises(ValueError):
            update_preference(original, "does_not_exist", True)
        with self.assertRaises(ValueError):
            update_preference(original, "high_contrast", "yes")
        with self.assertRaises(ValueError):
            update_preference(original, "font_size", "huge")
        with self.assertRaises(ValueError):
            update_mode(original, "battle_royale")
        with self.assertRaises(ValueError):
            update_formation(original, "army_group")
        with self.assertRaises(ValueError):
            update_deck(original, ["not_a_card"])
        with self.assertRaises(ValueError):
            update_deck(original, ["infantry_1", "infantry_1"])

    def test_update_profile_supports_partial_updates_and_validation(self) -> None:
        original = default_player_state()
        renamed = update_profile(original, display_name="  AOI  17 ")
        updated = update_profile(renamed, tagline="")

        self.assertEqual(original["profile"]["display_name"], "COMMANDER")
        self.assertEqual(renamed["profile"]["display_name"], "AOI 17")
        self.assertEqual(renamed["profile"]["tagline"], "偵察から覚えています")
        self.assertEqual(updated["profile"]["tagline"], "")

        with self.assertRaises(ValueError):
            update_profile(original, display_name="A")
        with self.assertRaises(ValueError):
            update_profile(original, display_name="X" * 21)
        with self.assertRaises(ValueError):
            update_profile(original, tagline="長" * 61)
        with self.assertRaises(ValueError):
            update_profile(original, display_name=3)  # type: ignore[arg-type]

    def test_selected_symbol_requires_unlock_and_survives_later_unlocks(self) -> None:
        state = default_player_state()
        available = state["collection"]["unlocked_symbols"]
        selected = available[-1]
        state = update_selected_symbol(state, selected)
        state = unlock_collection(
            state,
            cards=["infantry_3"],
            symbols=["infantry_09"],
        )

        self.assertEqual(state["profile"]["selected_symbol"], selected)
        self.assertIn("infantry_09", state["collection"]["unlocked_symbols"])
        state = update_selected_symbol(state, "infantry_09")
        self.assertEqual(state["profile"]["selected_symbol"], "infantry_09")

        with self.assertRaises(ValueError):
            update_selected_symbol(default_player_state(), "infantry_09")
        with self.assertRaises(ValueError):
            update_selected_symbol(default_player_state(), "not_a_symbol")
        with self.assertRaises(ValueError):
            update_selected_symbol(default_player_state(), 3)  # type: ignore[arg-type]

    def test_unlock_collection_adds_known_items_and_rejects_unknowns(self) -> None:
        original = default_player_state()
        unlocked = unlock_collection(
            original,
            cards=["infantry_3"],
            symbols=["infantry_09"],
            formations=["division"],
        )

        self.assertNotIn("infantry_3", original["collection"]["owned_cards"])
        self.assertIn("infantry_3", unlocked["collection"]["owned_cards"])
        self.assertIn("infantry_09", unlocked["collection"]["unlocked_symbols"])

        with self.assertRaises(ValueError):
            unlock_collection(original, cards=["missing"])
        with self.assertRaises(ValueError):
            unlock_collection(original, symbols="infantry_01")

    def test_record_result_updates_history_stats_streak_and_rewards(self) -> None:
        state = default_player_state()
        played_at = datetime(2026, 7, 10, 12, 30, tzinfo=timezone.utc)
        won = record_result(
            state,
            "勝利",
            mode="casual",
            opponent=" Aoi-17 ",
            mission_points_for=5,
            mission_points_against=2,
            turns=6,
            played_at=played_at,
            summary="中央と右翼を確保",
            unlocked_cards=["infantry_3"],
            unlocked_symbols=["infantry_09"],
        )

        self.assertEqual(state["stats"]["battles_played"], 0)
        self.assertEqual(won["stats"]["battles_played"], 1)
        self.assertEqual(won["stats"]["wins"], 1)
        self.assertEqual(won["stats"]["current_win_streak"], 1)
        self.assertEqual(won["stats"]["best_win_streak"], 1)
        self.assertEqual(won["stats"]["mission_points_earned"], 5)
        self.assertEqual(won["battle_history"][0]["opponent"], "Aoi-17")
        self.assertEqual(
            won["battle_history"][0]["played_at"], "2026-07-10T12:30:00+00:00"
        )
        self.assertIn("infantry_3", won["collection"]["owned_cards"])

        lost = record_result(won, "loss", mission_points_for=1)
        self.assertEqual(lost["stats"]["battles_played"], 2)
        self.assertEqual(lost["stats"]["losses"], 1)
        self.assertEqual(lost["stats"]["current_win_streak"], 0)
        self.assertEqual(lost["battle_history"][0]["result"], "loss")
        self.assertEqual(lost["battle_history"][1]["result"], "win")
        json.dumps(lost)

    def test_record_result_rejects_invalid_values_and_caps_history(self) -> None:
        state = default_player_state()
        with self.assertRaises(ValueError):
            record_result(state, "abandoned")
        with self.assertRaises(ValueError):
            record_result(state, "win", mission_points_for=-1)
        with self.assertRaises(ValueError):
            record_result(state, "win", turns=0)
        with self.assertRaises(ValueError):
            record_result(state, "win", played_at="yesterday")

        for index in range(MAX_BATTLE_HISTORY + 3):
            state = record_result(
                state,
                "draw",
                opponent=f"opponent-{index}",
                played_at="2026-07-10T00:00:00+00:00",
            )
        self.assertEqual(len(state["battle_history"]), MAX_BATTLE_HISTORY)
        self.assertEqual(state["stats"]["battles_played"], MAX_BATTLE_HISTORY + 3)


if __name__ == "__main__":
    unittest.main()

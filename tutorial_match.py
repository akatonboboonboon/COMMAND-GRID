"""Dedicated nine-round practical exercises for card tutorials.

The exercise deliberately uses its own storage key and never calls
``match_service``.  Completing or abandoning one therefore cannot overwrite a
normal battle, add battle-history rows, or grant ordinary match rewards.  The
UI remains responsible for awarding the official tutorial deck after
``TutorialExerciseStatus.passed`` becomes true.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from game_data import CARD_INDEX
from game_engine import (
    LANE_IDS,
    MAX_ROUNDS,
    GameState,
    Phase,
    RoundResolution,
    RuleViolation,
    new_game,
    resolve_round,
    submit_order,
)


CARD_TUTORIAL_MATCH_KEY = "card_tutorial_match"
TUTORIAL_MATCH_SCHEMA_VERSION = 1
TUTORIAL_PLAYER_ID = "tutorial_player"
TUTORIAL_AI_ID = "tutorial_ai"

# Every featured card is moved to slot one.  The remaining cards give each of
# the six beginner roles enough partners to demonstrate its real rules.
_TUTORIAL_BASE_DECK: tuple[str, ...] = (
    "infantry_1",
    "infantry_2",
    "armor_1",
    "recon_1",
    "artillery_1",
    "engineer_1",
    "engineer_2",
    "logistics_1",
    "logistics_2",
)

# The scripted opponent creates three equal, reachable fronts.  Its first six
# cards have no control, so their support is initially wasted; the final recon
# card gives each lane a final power of five.  This also puts hidden units on
# every lane early enough for any featured recon card to demonstrate revealing.
TUTORIAL_AI_SCRIPT: tuple[tuple[str, str], ...] = (
    ("recon_2", "left"),
    ("recon_2", "center"),
    ("recon_2", "right"),
    ("artillery_1", "left"),
    ("artillery_1", "center"),
    ("artillery_1", "right"),
    ("recon_1", "left"),
    ("recon_1", "center"),
    ("recon_1", "right"),
)
TUTORIAL_AI_DECK: tuple[str, ...] = tuple(
    card_id for card_id, _ in TUTORIAL_AI_SCRIPT
)


@dataclass(frozen=True, slots=True)
class TutorialExerciseStatus:
    """Progress and pass/fail conditions for one practical exercise."""

    featured_card_id: str
    round_no: int
    rounds_played: int
    max_rounds: int
    match_complete: bool
    featured_card_used: bool
    controlled_lanes: tuple[str, ...]
    passed: bool
    message: str

    @property
    def controlled_lane_count(self) -> int:
        return len(self.controlled_lanes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "featured_card_id": self.featured_card_id,
            "round_no": self.round_no,
            "rounds_played": self.rounds_played,
            "max_rounds": self.max_rounds,
            "match_complete": self.match_complete,
            "featured_card_used": self.featured_card_used,
            "controlled_lanes": list(self.controlled_lanes),
            "controlled_lane_count": self.controlled_lane_count,
            "passed": self.passed,
            "message": self.message,
        }


def tutorial_player_deck(featured_card_id: str) -> tuple[str, ...]:
    """Return an exact nine-card exercise deck with the lesson card first."""

    _require_featured_card(featured_card_id)
    other_cards = [
        card_id for card_id in _TUTORIAL_BASE_DECK if card_id != featured_card_id
    ]
    deck = (featured_card_id, *other_cards[: MAX_ROUNDS - 1])
    if len(deck) < MAX_ROUNDS:
        raise RuntimeError("tutorial base deck cannot fill nine exercise slots")
    return deck


def start_tutorial_match(
    storage: MutableMapping[str, Any],
    featured_card_id: str,
    *,
    reset: bool = False,
) -> GameState:
    """Start or resume an isolated, empty-board card exercise."""

    _require_featured_card(featured_card_id)
    if not reset:
        existing = load_tutorial_match(storage, featured_card_id)
        if existing is not None:
            return existing

    state = new_game(
        tutorial_player_deck(featured_card_id),
        TUTORIAL_AI_DECK,
        player_id=TUTORIAL_PLAYER_ID,
        opponent_id=TUTORIAL_AI_ID,
        player_name="あなた",
        opponent_name="実演習AI",
        game_id=f"card-tutorial-{featured_card_id}-{uuid4().hex}",
        max_rounds=MAX_ROUNDS,
    )
    _store_envelope(storage, featured_card_id, state)
    return state


def load_tutorial_match(
    storage: MutableMapping[str, Any],
    featured_card_id: str | None = None,
) -> GameState | None:
    """Load a valid exercise, dropping only corrupt exercise data."""

    raw = storage.get(CARD_TUTORIAL_MATCH_KEY)
    if not isinstance(raw, Mapping):
        if raw is not None:
            storage.pop(CARD_TUTORIAL_MATCH_KEY, None)
        return None

    try:
        if int(raw.get("service_version", 0)) != TUTORIAL_MATCH_SCHEMA_VERSION:
            raise ValueError("unsupported tutorial match schema")
        stored_card_id = str(raw["featured_card_id"])
        _require_featured_card(stored_card_id)
        if featured_card_id is not None and stored_card_id != featured_card_id:
            return None
        game_data = raw["game"]
        if not isinstance(game_data, Mapping):
            raise ValueError("tutorial game must be a mapping")
        state = GameState.from_dict(game_data)
        if state.player_order != (TUTORIAL_PLAYER_ID, TUTORIAL_AI_ID):
            raise ValueError("tutorial players do not match")
        if state.max_rounds != MAX_ROUNDS:
            raise ValueError("tutorial match must last nine rounds")
    except (KeyError, TypeError, ValueError, RuleViolation):
        storage.pop(CARD_TUTORIAL_MATCH_KEY, None)
        return None

    _store_envelope(storage, stored_card_id, state)
    return state


def play_tutorial_round(
    storage: MutableMapping[str, Any],
    featured_card_id: str,
    card_id: str,
    lane_id: str,
) -> tuple[GameState, RoundResolution, TutorialExerciseStatus]:
    """Play one player order against the exercise's scripted weak opponent."""

    state = load_tutorial_match(storage, featured_card_id)
    if state is None:
        state = start_tutorial_match(storage, featured_card_id, reset=True)
    if state.phase is Phase.COMPLETE:
        raise RuleViolation("match_complete", "この実演習はすでに終了しています。")

    script_index = state.round_no - 1
    if not 0 <= script_index < len(TUTORIAL_AI_SCRIPT):
        raise RuleViolation("invalid_state", "実演習AIの命令が見つかりません。")
    ai_card_id, ai_lane_id = TUTORIAL_AI_SCRIPT[script_index]

    submit_order(state, TUTORIAL_PLAYER_ID, card_id, lane_id)
    submit_order(state, TUTORIAL_AI_ID, ai_card_id, ai_lane_id)
    resolution = resolve_round(state)
    _store_envelope(storage, featured_card_id, state)
    return state, resolution, exercise_status(state, featured_card_id)


def exercise_status(
    state: GameState,
    featured_card_id: str,
) -> TutorialExerciseStatus:
    """Evaluate the explicit lesson-card and two-front completion conditions."""

    _require_featured_card(featured_card_id)
    if state.player_order != (TUTORIAL_PLAYER_ID, TUTORIAL_AI_ID):
        raise RuleViolation("invalid_state", "実演習ではない対戦データです。")

    featured_card_used = any(
        deployment.player_id == TUTORIAL_PLAYER_ID
        and deployment.card_id == featured_card_id
        for lane in state.lanes.values()
        for deployment in lane.deployments
    )
    controlled_lanes = tuple(
        lane_id
        for lane_id in LANE_IDS
        if state.lanes[lane_id].round_winners
        and state.lanes[lane_id].round_winners[-1] == TUTORIAL_PLAYER_ID
    )
    match_complete = state.phase is Phase.COMPLETE
    rounds_played = (
        state.result.rounds_played
        if state.result is not None
        else max(0, state.round_no - 1)
    )
    passed = (
        match_complete
        and rounds_played == MAX_ROUNDS
        and featured_card_used
        and len(controlled_lanes) >= 2
    )

    if passed:
        message = "実演習完了：履修カードを使い、9ラウンドで2戦線以上を確保しました。"
    elif match_complete and not featured_card_used:
        message = "履修カードを配備していないため、もう一度挑戦してください。"
    elif match_complete:
        message = (
            f"確保できたのは{len(controlled_lanes)}戦線でした。"
            "2戦線を目標に、最初からもう一度挑戦してください。"
        )
    elif featured_card_used:
        message = f"残り{MAX_ROUNDS - rounds_played}ラウンドです。2戦線の確保を目指してください。"
    else:
        message = (
            f"残り{MAX_ROUNDS - rounds_played}ラウンドです。"
            "履修カードを少なくとも1回配備してください。"
        )

    return TutorialExerciseStatus(
        featured_card_id=featured_card_id,
        round_no=state.round_no,
        rounds_played=rounds_played,
        max_rounds=state.max_rounds,
        match_complete=match_complete,
        featured_card_used=featured_card_used,
        controlled_lanes=controlled_lanes,
        passed=passed,
        message=message,
    )


def tutorial_match_status(
    storage: MutableMapping[str, Any],
    featured_card_id: str,
) -> TutorialExerciseStatus | None:
    state = load_tutorial_match(storage, featured_card_id)
    return None if state is None else exercise_status(state, featured_card_id)


def restart_tutorial_match(
    storage: MutableMapping[str, Any], featured_card_id: str
) -> GameState:
    return start_tutorial_match(storage, featured_card_id, reset=True)


def abandon_tutorial_match(storage: MutableMapping[str, Any]) -> bool:
    existed = CARD_TUTORIAL_MATCH_KEY in storage
    storage.pop(CARD_TUTORIAL_MATCH_KEY, None)
    return existed


def _require_featured_card(card_id: str) -> None:
    if not isinstance(card_id, str) or card_id not in CARD_INDEX:
        raise RuleViolation("unknown_card", f"存在しない履修カードです: {card_id}")


def _store_envelope(
    storage: MutableMapping[str, Any], featured_card_id: str, state: GameState
) -> None:
    storage[CARD_TUTORIAL_MATCH_KEY] = {
        "service_version": TUTORIAL_MATCH_SCHEMA_VERSION,
        "featured_card_id": featured_card_id,
        "game": state.to_dict(),
    }


__all__ = [
    "CARD_TUTORIAL_MATCH_KEY",
    "TUTORIAL_AI_DECK",
    "TUTORIAL_AI_ID",
    "TUTORIAL_AI_SCRIPT",
    "TUTORIAL_MATCH_SCHEMA_VERSION",
    "TUTORIAL_PLAYER_ID",
    "TutorialExerciseStatus",
    "abandon_tutorial_match",
    "exercise_status",
    "load_tutorial_match",
    "play_tutorial_round",
    "restart_tutorial_match",
    "start_tutorial_match",
    "tutorial_match_status",
    "tutorial_player_deck",
]

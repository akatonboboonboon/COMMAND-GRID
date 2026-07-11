"""Persistence bridge between NiceGUI storage and the rules engine.

The rules engine deliberately knows nothing about browsers or NiceGUI.  This
module keeps one authoritative :class:`~game_engine.GameState` in
``app.storage.user`` and snapshots the player's selected mode, formation and
deck when a match starts.  Every value written here is JSON-compatible.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from typing import Any
from uuid import uuid4

from game_data import CARDS, STARTER_DECK
from game_engine import (
    GameState,
    RoundResolution,
    new_game,
    play_round_with_ai,
)
from player_state import (
    ensure_player_state,
    record_result,
    store_player_state,
)
from symbol_catalog import SYMBOL_CATALOG


ACTIVE_MATCH_KEY = "active_match"
RECORDED_MATCH_IDS_KEY = "recorded_match_ids"
MATCH_SCHEMA_VERSION = 1
HUMAN_PLAYER_ID = "player"
AI_PLAYER_ID = "opponent"
MAX_RECORDED_MATCH_IDS = 100

_OPPONENT_NAMES = {
    "training": "訓練AI",
    "casual": "カジュアルAI",
    "ranked": "ランクAI",
    "friend": "フレンド代役AI",
}


def start_match(
    storage: MutableMapping[str, Any], *, reset: bool = False
) -> GameState:
    """Start or resume the active local match.

    ``reset=False`` resumes a valid stored match.  A new match snapshots the
    selected deck, mode and formation from :mod:`player_state`; later settings
    changes therefore cannot alter a battle already in progress.

    The selected deck must satisfy the engine's normal nine-card minimum.  The
    engine's :class:`~game_engine.RuleViolation` is intentionally allowed to
    propagate so the UI can show its stable error code and friendly message.
    """

    if not reset:
        existing = load_match(storage)
        if existing is not None:
            return existing

    player = ensure_player_state(storage)
    deck = list(player["deck"])
    mode = str(player["selected_mode"])
    formation = str(player["selected_formation"])
    game = new_game(
        deck,
        STARTER_DECK,
        player_id=HUMAN_PLAYER_ID,
        opponent_id=AI_PLAYER_ID,
        player_name=str(player["profile"]["display_name"]),
        opponent_name=_OPPONENT_NAMES.get(mode, "対戦AI"),
        game_id=f"command-grid-{uuid4().hex}",
    )
    envelope = _new_envelope(
        game,
        mode=mode,
        formation=formation,
        deck=deck,
    )
    storage[ACTIVE_MATCH_KEY] = envelope
    return game


def load_match(storage: MutableMapping[str, Any]) -> GameState | None:
    """Restore the active match, or return ``None`` for missing/bad storage.

    Corrupt saves are removed so they cannot trap the player on a broken battle
    screen.  A completed save is also reconciled with player history; the
    match-id ledger prevents that result from being recorded more than once.
    """

    raw = storage.get(ACTIVE_MATCH_KEY)
    if not isinstance(raw, Mapping):
        if raw is not None:
            storage.pop(ACTIVE_MATCH_KEY, None)
        return None

    try:
        envelope = _normalize_envelope(storage, raw)
        state = GameState.from_dict(envelope["game"])
    except (KeyError, TypeError, ValueError):
        storage.pop(ACTIVE_MATCH_KEY, None)
        return None

    if state.result is not None:
        _record_completed_result_once(storage, state, envelope)
    storage[ACTIVE_MATCH_KEY] = _with_game(envelope, state)
    return state


def play_player_round(
    storage: MutableMapping[str, Any], card_id: str, lane_id: str
) -> tuple[GameState, RoundResolution]:
    """Submit one player order, run the deterministic AI, and persist it.

    If no match exists, one is started from the current player settings.  The
    formation captured at match start is attached to every player deployment.
    On the final round, the result is written to player history exactly once.
    """

    state = load_match(storage)
    if state is None:
        state = start_match(storage)
    envelope = _require_envelope(storage)
    resolution = play_round_with_ai(
        state,
        HUMAN_PLAYER_ID,
        card_id,
        lane_id,
        ai_id=AI_PLAYER_ID,
        formation_id=str(envelope["formation"]),
    )
    if resolution.match_complete:
        _record_completed_result_once(storage, state, envelope)
    storage[ACTIVE_MATCH_KEY] = _with_game(envelope, state)
    return state, resolution


def abandon_match(storage: MutableMapping[str, Any]) -> bool:
    """Discard an in-progress/finished active match without recording a loss."""

    existed = ACTIVE_MATCH_KEY in storage
    storage.pop(ACTIVE_MATCH_KEY, None)
    return existed


def restart_match(storage: MutableMapping[str, Any]) -> GameState:
    """Discard the active match and start a fresh one from current settings."""

    return start_match(storage, reset=True)


def get_match_context(storage: MutableMapping[str, Any]) -> dict[str, Any] | None:
    """Return the JSON-safe settings snapshot for the active valid match."""

    state = load_match(storage)
    if state is None:
        return None
    envelope = _require_envelope(storage)
    return {
        "game_id": state.game_id,
        "mode": str(envelope["mode"]),
        "formation": str(envelope["formation"]),
        "deck": list(envelope["deck"]),
        "rewards": deepcopy(envelope.get("rewards", {"cards": [], "symbols": []})),
        "result_recorded": bool(envelope.get("result_recorded", False)),
    }


def _new_envelope(
    state: GameState,
    *,
    mode: str,
    formation: str,
    deck: list[str],
) -> dict[str, Any]:
    return {
        "service_version": MATCH_SCHEMA_VERSION,
        "game": state.to_dict(),
        "player_id": HUMAN_PLAYER_ID,
        "opponent_id": AI_PLAYER_ID,
        "mode": mode,
        "formation": formation,
        "deck": list(deck),
        "rewards": {"cards": [], "symbols": []},
        "result_recorded": False,
    }


def _normalize_envelope(
    storage: MutableMapping[str, Any], raw: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate our envelope and migrate a legacy raw ``GameState`` save."""

    player = ensure_player_state(storage)
    if "game" in raw:
        if int(raw.get("service_version", MATCH_SCHEMA_VERSION)) != MATCH_SCHEMA_VERSION:
            raise ValueError("unsupported match service save")
        game_data = raw["game"]
        mode = raw.get("mode", player["selected_mode"])
        formation = raw.get("formation", player["selected_formation"])
        deck = raw.get("deck", player["deck"])
        rewards = raw.get("rewards", {"cards": [], "symbols": []})
        result_recorded = bool(raw.get("result_recorded", False))
    else:
        # Early prototypes stored GameState.to_dict() directly.
        game_data = raw
        mode = player["selected_mode"]
        formation = player["selected_formation"]
        deck = player["deck"]
        rewards = {"cards": [], "symbols": []}
        result_recorded = False

    if not isinstance(game_data, Mapping):
        raise ValueError("match game data must be a mapping")
    if mode not in {"training", "casual", "ranked", "friend"}:
        raise ValueError("invalid stored match mode")
    if formation not in {"native", "battalion", "brigade", "division"}:
        raise ValueError("invalid stored match formation")
    if (
        not isinstance(deck, list | tuple)
        or any(not isinstance(card_id, str) for card_id in deck)
    ):
        raise ValueError("invalid stored match deck")
    if not isinstance(rewards, Mapping):
        raise ValueError("invalid stored match rewards")
    reward_cards = rewards.get("cards", [])
    reward_symbols = rewards.get("symbols", [])
    if (
        not isinstance(reward_cards, list | tuple)
        or not isinstance(reward_symbols, list | tuple)
        or any(not isinstance(value, str) for value in reward_cards)
        or any(not isinstance(value, str) for value in reward_symbols)
    ):
        raise ValueError("invalid stored match rewards")
    return {
        "service_version": MATCH_SCHEMA_VERSION,
        "game": deepcopy(dict(game_data)),
        "player_id": HUMAN_PLAYER_ID,
        "opponent_id": AI_PLAYER_ID,
        "mode": str(mode),
        "formation": str(formation),
        "deck": list(deck),
        "rewards": {
            "cards": list(reward_cards),
            "symbols": list(reward_symbols),
        },
        "result_recorded": result_recorded,
    }


def _with_game(envelope: Mapping[str, Any], state: GameState) -> dict[str, Any]:
    saved = dict(envelope)
    saved["game"] = state.to_dict()
    return saved


def _require_envelope(storage: MutableMapping[str, Any]) -> dict[str, Any]:
    raw = storage.get(ACTIVE_MATCH_KEY)
    if not isinstance(raw, Mapping) or "game" not in raw:
        raise RuntimeError("active match envelope is missing")
    return dict(raw)


def _record_completed_result_once(
    storage: MutableMapping[str, Any],
    state: GameState,
    envelope: dict[str, Any],
) -> None:
    if state.result is None:
        return

    recorded_ids = _recorded_ids(storage.get(RECORDED_MATCH_IDS_KEY))
    if envelope.get("result_recorded") or state.game_id in recorded_ids:
        envelope["result_recorded"] = True
        if state.game_id not in recorded_ids:
            recorded_ids.append(state.game_id)
            storage[RECORDED_MATCH_IDS_KEY] = recorded_ids[-MAX_RECORDED_MATCH_IDS:]
        return

    result = state.result
    if result.winner_id is None:
        player_result = "draw"
    elif result.winner_id == HUMAN_PLAYER_ID:
        player_result = "win"
    else:
        player_result = "loss"

    points = result.mission_points
    player = ensure_player_state(storage)
    rewards = collection_rewards_for_outcome(player, player_result)
    reward_cards = rewards["cards"]
    reward_symbols = rewards["symbols"]
    updated = record_result(
        player,
        player_result,
        mode=str(envelope["mode"]),
        opponent=_OPPONENT_NAMES.get(str(envelope["mode"]), "対戦AI"),
        mission_points_for=int(points.get(HUMAN_PLAYER_ID, 0)),
        mission_points_against=int(points.get(AI_PLAYER_ID, 0)),
        turns=result.rounds_played,
        deck=list(envelope["deck"]),
        formation=str(envelope["formation"]),
        summary=result.summary,
        unlocked_cards=reward_cards,
        unlocked_symbols=reward_symbols,
    )
    store_player_state(storage, updated)
    recorded_ids.append(state.game_id)
    storage[RECORDED_MATCH_IDS_KEY] = recorded_ids[-MAX_RECORDED_MATCH_IDS:]
    envelope["rewards"] = {
        "cards": reward_cards,
        "symbols": reward_symbols,
    }
    envelope["result_recorded"] = True


def collection_rewards_for_outcome(
    player: Mapping[str, Any], outcome: str
) -> dict[str, list[str]]:
    """Select deterministic collection rewards for one completed match.

    A win grants the next unowned card and up to twelve symbols. A draw grants
    three symbols, while a loss grants one small symbol reward. Exhausted card
    or symbol catalogs naturally produce empty lists. Keeping this policy in a
    shared pure function makes local and online rewards identical.
    """

    symbol_limits = {"win": 12, "draw": 3, "loss": 1}
    if outcome not in symbol_limits:
        raise ValueError(f"unknown match outcome: {outcome}")
    collection = player.get("collection")
    if not isinstance(collection, Mapping):
        raise ValueError("player collection is missing")
    owned_cards = set(collection.get("owned_cards", []))
    unlocked_symbols = set(collection.get("unlocked_symbols", []))
    reward_cards = (
        [card.id for card in CARDS if card.id not in owned_cards][:1]
        if outcome == "win"
        else []
    )
    reward_symbols = [
        symbol.id
        for symbol in SYMBOL_CATALOG
        if symbol.id not in unlocked_symbols
    ][: symbol_limits[outcome]]
    return {"cards": reward_cards, "symbols": reward_symbols}


def _recorded_ids(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(value for value in raw if isinstance(value, str)))


__all__ = [
    "ACTIVE_MATCH_KEY",
    "AI_PLAYER_ID",
    "HUMAN_PLAYER_ID",
    "MATCH_SCHEMA_VERSION",
    "RECORDED_MATCH_IDS_KEY",
    "abandon_match",
    "collection_rewards_for_outcome",
    "get_match_context",
    "load_match",
    "play_player_round",
    "restart_match",
    "start_match",
]

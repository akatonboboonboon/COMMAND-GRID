"""Persistent, JSON-safe player state for COMMAND GRID.

The NiceGUI app can store the returned dictionaries directly in
``app.storage.user``.  Normalization is deliberately forgiving so older or
partially corrupted browser storage does not prevent the game from loading.
Update helpers are deliberately strict so programming mistakes are noticed
when new state is written.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from game_data import CARDS, CARD_INDEX, STARTER_DECK
from symbol_catalog import CARD_SYMBOL_IDS, SYMBOL_INDEX


PLAYER_STATE_KEY = "player_state"
SCHEMA_VERSION = 1
MAX_DECK_SIZE = 12
MAX_BATTLE_HISTORY = 50
DEFAULT_DISPLAY_NAME = "COMMANDER"
DEFAULT_TAGLINE = "偵察から覚えています"

VALID_MODES = frozenset({"training", "casual", "ranked", "friend"})
VALID_FORMATIONS = frozenset({"native", "battalion", "brigade", "division"})
VALID_RESULTS = frozenset({"win", "loss", "draw"})

PREFERENCE_DEFAULTS: dict[str, bool | str] = {
    "beginner_mode": True,
    "explain_military_terms": True,
    "recommended_actions": True,
    "slow_resolution": True,
    "font_size": "standard",
    "high_contrast": False,
    "reduce_motion": False,
    "large_symbols": False,
    "confirm_orders": True,
    "auto_logs": True,
    "faction_patterns": True,
    "time_warning": True,
    "spectators": False,
    "history_public": True,
    "cards_public": False,
    "profile_visibility": "friends",
}

PREFERENCE_CHOICES = {
    "font_size": frozenset({"standard", "large", "maximum"}),
    "profile_visibility": frozenset({"public", "friends", "private"}),
}

DEFAULT_OWNED_CARDS = tuple(card.id for card in CARDS if card.owned)
DEFAULT_UNLOCKED_SYMBOLS = tuple(
    dict.fromkeys(
        CARD_SYMBOL_IDS[card_id]
        for card_id in DEFAULT_OWNED_CARDS
        if card_id in CARD_SYMBOL_IDS
    )
)
DEFAULT_UNLOCKED_FORMATIONS = ("native", "battalion", "brigade", "division")


_MODE_ALIASES = {
    "practice": "training",
    "tutorial": "training",
    "演習": "training",
    "練習": "training",
    "カジュアル": "casual",
    "カジュアル対戦": "casual",
    "ランク": "ranked",
    "ランク対戦": "ranked",
    "フレンド": "friend",
    "フレンド対戦": "friend",
}
_FORMATION_ALIASES = {
    "default": "native",
    "card": "native",
    "カード固有": "native",
    "大隊": "battalion",
    "旅団": "brigade",
    "師団": "division",
}
_RESULT_ALIASES = {
    "victory": "win",
    "won": "win",
    "勝利": "win",
    "defeat": "loss",
    "lost": "loss",
    "敗北": "loss",
    "tie": "draw",
    "引き分け": "draw",
}
_PREFERENCE_ALIASES = {
    "text_size": "font_size",
    "reduced_motion": "reduce_motion",
    "plain_language": "explain_military_terms",
    "recommended_action": "recommended_actions",
    "auto_battle_log": "auto_logs",
    "allow_spectators": "spectators",
    "share_history": "history_public",
    "share_collection": "cards_public",
}
_LEGACY_ROOT_KEYS = frozenset(
    {
        "preferences",
        "collection",
        "owned_cards",
        "unlocked_symbols",
        "unlocked_formations",
        "deck",
        "selected_formation",
        "formation",
        "selected_mode",
        "mode",
        "battle_history",
        "history",
        "stats",
        "profile",
        "player_name",
        "display_name",
        "tagline",
        "selected_symbol",
        *PREFERENCE_DEFAULTS,
        *_PREFERENCE_ALIASES,
    }
)


def default_player_state() -> dict[str, Any]:
    """Return a fresh default state containing only JSON-compatible values."""

    return {
        "schema_version": SCHEMA_VERSION,
        "profile": {
            "display_name": DEFAULT_DISPLAY_NAME,
            "tagline": DEFAULT_TAGLINE,
            "selected_symbol": (
                DEFAULT_UNLOCKED_SYMBOLS[0] if DEFAULT_UNLOCKED_SYMBOLS else ""
            ),
        },
        "preferences": deepcopy(PREFERENCE_DEFAULTS),
        "collection": {
            "owned_cards": list(DEFAULT_OWNED_CARDS),
            "unlocked_symbols": list(DEFAULT_UNLOCKED_SYMBOLS),
            "unlocked_formations": list(DEFAULT_UNLOCKED_FORMATIONS),
        },
        "deck": list(STARTER_DECK),
        "selected_formation": "native",
        "selected_mode": "training",
        "battle_history": [],
        "stats": _default_stats(),
    }


def normalize_player_state(raw: object) -> dict[str, Any]:
    """Migrate arbitrary storage data into the current, safe state schema.

    Invalid values are discarded rather than raising.  Starter ownership is
    always restored, so malformed collection data cannot make the game
    unplayable.
    """

    source: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    state = default_player_state()

    collection = _normalize_collection(source)
    state["collection"] = collection
    state["profile"] = _normalize_profile(source, collection["unlocked_symbols"])
    state["preferences"] = _normalize_preferences(source)
    state["deck"] = _normalize_deck(source.get("deck"), collection["owned_cards"])

    raw_formation = source.get("selected_formation", source.get("formation"))
    formation = _normalize_formation(raw_formation)
    if formation not in collection["unlocked_formations"]:
        formation = "native"
    state["selected_formation"] = formation
    state["selected_mode"] = _normalize_mode(
        source.get("selected_mode", source.get("mode"))
    )

    history_source = source.get("battle_history", source.get("history"))
    history = _normalize_history(history_source, collection["owned_cards"])
    state["battle_history"] = history
    state["stats"] = _normalize_stats(source.get("stats"), history)
    return state


def ensure_player_state(storage: MutableMapping[str, Any]) -> dict[str, Any]:
    """Normalize and persist state in a NiceGUI ``app.storage.user`` mapping.

    When the namespaced state does not yet exist, known legacy root keys are
    migrated.  Legacy values are left untouched so rolling back an app version
    remains safe.
    """

    existing = storage.get(PLAYER_STATE_KEY)
    if isinstance(existing, Mapping):
        raw: object = existing
    else:
        raw = {key: storage[key] for key in _LEGACY_ROOT_KEYS if key in storage}
    normalized = normalize_player_state(raw)
    storage[PLAYER_STATE_KEY] = normalized
    return deepcopy(normalized)


def store_player_state(
    storage: MutableMapping[str, Any], state: object
) -> dict[str, Any]:
    """Normalize ``state``, persist it, and return a detached copy."""

    normalized = normalize_player_state(state)
    storage[PLAYER_STATE_KEY] = normalized
    return deepcopy(normalized)


def update_preference(
    state: object, key: str, value: bool | str
) -> dict[str, Any]:
    """Return state with one validated preference updated."""

    if key not in PREFERENCE_DEFAULTS:
        raise ValueError(f"Unknown preference: {key}")
    expected = PREFERENCE_DEFAULTS[key]
    if isinstance(expected, bool):
        if type(value) is not bool:
            raise ValueError(f"Preference {key} must be a boolean")
    elif value not in PREFERENCE_CHOICES[key]:
        choices = ", ".join(sorted(PREFERENCE_CHOICES[key]))
        raise ValueError(f"Preference {key} must be one of: {choices}")

    updated = normalize_player_state(state)
    updated["preferences"][key] = value
    return updated


def update_profile(
    state: object,
    display_name: str | None = None,
    tagline: str | None = None,
) -> dict[str, Any]:
    """Return state with validated profile fields updated.

    ``None`` keeps the existing value.  Pass an empty string to deliberately
    clear the tagline; display names must contain 2 to 20 characters after
    surrounding and repeated whitespace is normalized.
    """

    updated = normalize_player_state(state)
    profile = dict(updated["profile"])
    if display_name is not None:
        cleaned_name = _normalize_whitespace(display_name)
        if not 2 <= len(cleaned_name) <= 20:
            raise ValueError("display_name must contain 2 to 20 characters")
        profile["display_name"] = cleaned_name
    if tagline is not None:
        cleaned_tagline = _normalize_whitespace(tagline)
        if len(cleaned_tagline) > 60:
            raise ValueError("tagline cannot contain more than 60 characters")
        profile["tagline"] = cleaned_tagline
    updated["profile"] = profile
    return updated


def update_selected_symbol(state: object, symbol_id: str) -> dict[str, Any]:
    """Return state with an unlocked collection symbol selected for display."""

    if not isinstance(symbol_id, str):
        raise ValueError("symbol_id must be a string")
    updated = normalize_player_state(state)
    if symbol_id not in updated["collection"]["unlocked_symbols"]:
        raise ValueError(f"Symbol is not unlocked: {symbol_id}")
    updated["profile"]["selected_symbol"] = symbol_id
    return updated


def update_deck(state: object, card_ids: Sequence[str]) -> dict[str, Any]:
    """Return state with a validated deck (zero to twelve unique cards)."""

    if isinstance(card_ids, (str, bytes)) or not isinstance(card_ids, Sequence):
        raise ValueError("Deck must be a sequence of card IDs")
    if len(card_ids) > MAX_DECK_SIZE:
        raise ValueError(f"Deck cannot contain more than {MAX_DECK_SIZE} cards")
    if any(not isinstance(card_id, str) for card_id in card_ids):
        raise ValueError("Every deck entry must be a card ID string")
    if len(set(card_ids)) != len(card_ids):
        raise ValueError("Deck cannot contain duplicate cards")

    updated = normalize_player_state(state)
    owned = set(updated["collection"]["owned_cards"])
    unknown = [card_id for card_id in card_ids if card_id not in CARD_INDEX]
    if unknown:
        raise ValueError(f"Unknown card ID: {unknown[0]}")
    locked = [card_id for card_id in card_ids if card_id not in owned]
    if locked:
        raise ValueError(f"Card is not owned: {locked[0]}")
    updated["deck"] = list(card_ids)
    return updated


def update_mode(state: object, mode: str) -> dict[str, Any]:
    """Return state with the selected game mode updated."""

    canonical = _canonical_string(mode, _MODE_ALIASES)
    if canonical not in VALID_MODES:
        raise ValueError(f"Unknown game mode: {mode}")
    updated = normalize_player_state(state)
    updated["selected_mode"] = canonical
    return updated


def update_formation(state: object, formation: str) -> dict[str, Any]:
    """Return state with one currently unlocked formation selected."""

    canonical = _canonical_string(formation, _FORMATION_ALIASES)
    if canonical not in VALID_FORMATIONS:
        raise ValueError(f"Unknown formation: {formation}")
    updated = normalize_player_state(state)
    if canonical not in updated["collection"]["unlocked_formations"]:
        raise ValueError(f"Formation is not unlocked: {canonical}")
    updated["selected_formation"] = canonical
    return updated


def unlock_collection(
    state: object,
    *,
    cards: Iterable[str] = (),
    symbols: Iterable[str] = (),
    formations: Iterable[str] = (),
) -> dict[str, Any]:
    """Return state with validated card, symbol, and formation unlocks added."""

    card_ids = _validated_unlock_ids(cards, set(CARD_INDEX), "card")
    symbol_ids = _validated_unlock_ids(symbols, set(SYMBOL_INDEX), "symbol")
    formation_ids: list[str] = []
    for value in _materialize_ids(formations, "formation"):
        canonical = _canonical_string(value, _FORMATION_ALIASES)
        if canonical not in VALID_FORMATIONS:
            raise ValueError(f"Unknown formation ID: {value}")
        if canonical not in formation_ids:
            formation_ids.append(canonical)

    updated = normalize_player_state(state)
    collection = updated["collection"]
    collection["owned_cards"] = _ordered_union(collection["owned_cards"], card_ids)
    collection["unlocked_symbols"] = _ordered_union(
        collection["unlocked_symbols"], symbol_ids
    )
    collection["unlocked_formations"] = _ordered_union(
        collection["unlocked_formations"], formation_ids
    )
    return updated


def record_result(
    state: object,
    result: str,
    *,
    mode: str | None = None,
    opponent: str | None = None,
    mission_points_for: int = 0,
    mission_points_against: int = 0,
    turns: int | None = None,
    played_at: datetime | str | None = None,
    deck: Sequence[str] | None = None,
    formation: str | None = None,
    summary: str | None = None,
    unlocked_cards: Iterable[str] = (),
    unlocked_symbols: Iterable[str] = (),
    unlocked_formations: Iterable[str] = (),
) -> dict[str, Any]:
    """Record a completed battle and update aggregate stats and unlocks.

    History is stored newest first and capped at :data:`MAX_BATTLE_HISTORY`.
    The returned state is detached from the input and can be assigned directly
    to ``app.storage.user[PLAYER_STATE_KEY]``.
    """

    canonical_result = _canonical_string(result, _RESULT_ALIASES)
    if canonical_result not in VALID_RESULTS:
        raise ValueError(f"Unknown battle result: {result}")
    points_for = _require_nonnegative_int(mission_points_for, "mission_points_for")
    points_against = _require_nonnegative_int(
        mission_points_against, "mission_points_against"
    )
    if turns is not None:
        turns = _require_nonnegative_int(turns, "turns")
        if turns == 0:
            raise ValueError("turns must be greater than zero")

    updated = unlock_collection(
        state,
        cards=unlocked_cards,
        symbols=unlocked_symbols,
        formations=unlocked_formations,
    )
    if mode is not None:
        updated = update_mode(updated, mode)
    if formation is not None:
        updated = update_formation(updated, formation)
    if deck is not None:
        updated = update_deck(updated, deck)

    entry = {
        "id": uuid4().hex,
        "result": canonical_result,
        "mode": updated["selected_mode"],
        "formation": updated["selected_formation"],
        "deck": list(updated["deck"]),
        "opponent": _clean_optional_text(opponent, 80),
        "mission_points_for": points_for,
        "mission_points_against": points_against,
        "turns": turns,
        "played_at": _normalize_played_at(played_at),
        "summary": _clean_optional_text(summary, 500),
    }
    updated["battle_history"] = [entry, *updated["battle_history"]][
        :MAX_BATTLE_HISTORY
    ]

    stats = dict(updated["stats"])
    stats["battles_played"] += 1
    stats[{"win": "wins", "loss": "losses", "draw": "draws"}[canonical_result]] += 1
    stats["mission_points_earned"] += points_for
    if canonical_result == "win":
        stats["current_win_streak"] += 1
        stats["best_win_streak"] = max(
            stats["best_win_streak"], stats["current_win_streak"]
        )
    else:
        stats["current_win_streak"] = 0
    updated["stats"] = stats
    return updated


def _default_stats() -> dict[str, int]:
    return {
        "battles_played": 0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "current_win_streak": 0,
        "best_win_streak": 0,
        "mission_points_earned": 0,
    }


def _normalize_profile(
    source: Mapping[str, Any], unlocked_symbols: Sequence[str]
) -> dict[str, str]:
    raw_profile = source.get("profile")
    nested = raw_profile if isinstance(raw_profile, Mapping) else {}

    display_name = DEFAULT_DISPLAY_NAME
    for candidate in (
        nested.get("display_name"),
        source.get("display_name"),
        source.get("player_name"),
    ):
        if not isinstance(candidate, str):
            continue
        cleaned = _normalize_whitespace(candidate)
        if 2 <= len(cleaned) <= 20:
            display_name = cleaned
            break

    tagline = DEFAULT_TAGLINE
    for candidate in (nested.get("tagline"), source.get("tagline")):
        if not isinstance(candidate, str):
            continue
        cleaned = _normalize_whitespace(candidate)
        if len(cleaned) <= 60:
            tagline = cleaned
            break

    fallback_symbol = unlocked_symbols[0] if unlocked_symbols else ""
    selected_symbol = nested.get("selected_symbol", source.get("selected_symbol"))
    if (
        not isinstance(selected_symbol, str)
        or selected_symbol not in SYMBOL_INDEX
        or selected_symbol not in unlocked_symbols
    ):
        selected_symbol = fallback_symbol

    return {
        "display_name": display_name,
        "tagline": tagline,
        "selected_symbol": selected_symbol,
    }


def _normalize_preferences(source: Mapping[str, Any]) -> dict[str, bool | str]:
    result = deepcopy(PREFERENCE_DEFAULTS)
    raw_preferences = source.get("preferences")
    nested = raw_preferences if isinstance(raw_preferences, Mapping) else {}

    candidates: dict[str, Any] = {}
    for raw_key, value in source.items():
        key = _PREFERENCE_ALIASES.get(str(raw_key), str(raw_key))
        if key in PREFERENCE_DEFAULTS:
            candidates[key] = value
    for raw_key, value in nested.items():
        key = _PREFERENCE_ALIASES.get(str(raw_key), str(raw_key))
        if key in PREFERENCE_DEFAULTS:
            candidates[key] = value

    for key, default in PREFERENCE_DEFAULTS.items():
        value = candidates.get(key)
        if isinstance(default, bool):
            coerced = _coerce_bool(value)
            if coerced is not None:
                result[key] = coerced
        elif isinstance(value, str) and value.strip().lower() in PREFERENCE_CHOICES[key]:
            result[key] = value.strip().lower()
    return result


def _normalize_collection(source: Mapping[str, Any]) -> dict[str, list[str]]:
    raw_collection = source.get("collection")
    collection = raw_collection if isinstance(raw_collection, Mapping) else {}

    owned_source = collection.get("owned_cards", source.get("owned_cards"))
    if owned_source is None:
        cards_map = collection.get("cards")
        if isinstance(cards_map, Mapping):
            owned_source = [
                card_id
                for card_id, value in cards_map.items()
                if _collection_value_is_owned(value)
            ]
        elif isinstance(raw_collection, Sequence) and not isinstance(
            raw_collection, (str, bytes)
        ):
            owned_source = raw_collection
    owned = _known_ids(owned_source, set(CARD_INDEX))
    owned = _ordered_union(DEFAULT_OWNED_CARDS, owned)

    symbols_source = collection.get(
        "unlocked_symbols", source.get("unlocked_symbols")
    )
    symbols = _known_ids(symbols_source, set(SYMBOL_INDEX))
    symbols = _ordered_union(DEFAULT_UNLOCKED_SYMBOLS, symbols)

    formations_source = collection.get(
        "unlocked_formations", source.get("unlocked_formations")
    )
    formations = []
    for value in _string_values(formations_source):
        canonical = _canonical_string(value, _FORMATION_ALIASES)
        if canonical in VALID_FORMATIONS and canonical not in formations:
            formations.append(canonical)
    formations = _ordered_union(DEFAULT_UNLOCKED_FORMATIONS, formations)
    return {
        "owned_cards": owned,
        "unlocked_symbols": symbols,
        "unlocked_formations": formations,
    }


def _normalize_deck(raw: object, owned_cards: Sequence[str]) -> list[str]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return [card_id for card_id in STARTER_DECK if card_id in owned_cards]
    owned = set(owned_cards)
    result = []
    for card_id in raw:
        if (
            isinstance(card_id, str)
            and card_id in CARD_INDEX
            and card_id in owned
            and card_id not in result
        ):
            result.append(card_id)
        if len(result) == MAX_DECK_SIZE:
            break
    return result


def _normalize_history(raw: object, owned_cards: Sequence[str]) -> list[dict[str, Any]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    result = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            continue
        battle_result = _canonical_string(item.get("result"), _RESULT_ALIASES)
        if battle_result not in VALID_RESULTS:
            continue
        mode = _normalize_mode(item.get("mode"))
        formation = _normalize_formation(item.get("formation"))
        deck = _normalize_deck(item.get("deck", []), owned_cards)
        identifier = _clean_optional_text(item.get("id"), 80) or f"legacy-{index + 1}"
        played_at = _clean_optional_text(item.get("played_at"), 64) or ""
        turns_value = _coerce_nonnegative_int(item.get("turns"))
        result.append(
            {
                "id": identifier,
                "result": battle_result,
                "mode": mode,
                "formation": formation,
                "deck": deck,
                "opponent": _clean_optional_text(item.get("opponent"), 80),
                "mission_points_for": _coerce_nonnegative_int(
                    item.get("mission_points_for", item.get("points", 0))
                ),
                "mission_points_against": _coerce_nonnegative_int(
                    item.get("mission_points_against", 0)
                ),
                "turns": turns_value or None,
                "played_at": played_at,
                "summary": _clean_optional_text(item.get("summary"), 500),
            }
        )
        if len(result) == MAX_BATTLE_HISTORY:
            break
    return result


def _normalize_stats(raw: object, history: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    source = raw if isinstance(raw, Mapping) else {}
    aliases = {
        "battles_played": ("battles_played", "played", "matches"),
        "wins": ("wins", "win"),
        "losses": ("losses", "loss"),
        "draws": ("draws", "draw"),
        "current_win_streak": ("current_win_streak", "win_streak", "streak"),
        "best_win_streak": ("best_win_streak", "best_streak"),
        "mission_points_earned": ("mission_points_earned", "mission_points"),
    }
    result = _default_stats()
    for target, source_keys in aliases.items():
        for source_key in source_keys:
            if source_key in source:
                result[target] = _coerce_nonnegative_int(source[source_key])
                break

    history_counts = {
        name: sum(1 for entry in history if entry["result"] == result_name)
        for name, result_name in (("wins", "win"), ("losses", "loss"), ("draws", "draw"))
    }
    for name, count in history_counts.items():
        result[name] = max(result[name], count)
    result["battles_played"] = max(
        result["battles_played"],
        result["wins"] + result["losses"] + result["draws"],
    )
    history_points = sum(int(entry["mission_points_for"]) for entry in history)
    result["mission_points_earned"] = max(
        result["mission_points_earned"], history_points
    )
    result["best_win_streak"] = max(
        result["best_win_streak"], result["current_win_streak"]
    )
    return result


def _normalize_mode(value: object) -> str:
    canonical = _canonical_string(value, _MODE_ALIASES)
    return canonical if canonical in VALID_MODES else "training"


def _normalize_formation(value: object) -> str:
    canonical = _canonical_string(value, _FORMATION_ALIASES)
    return canonical if canonical in VALID_FORMATIONS else "native"


def _canonical_string(value: object, aliases: Mapping[str, str]) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = value.strip().lower()
    return aliases.get(cleaned, cleaned)


def _coerce_bool(value: object) -> bool | None:
    if type(value) is bool:
        return value
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in {"true", "1", "yes", "on"}:
            return True
        if cleaned in {"false", "0", "no", "off"}:
            return False
    return None


def _coerce_nonnegative_int(value: object) -> int:
    if type(value) is bool:
        return 0
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, number)


def _require_nonnegative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _normalize_played_at(value: datetime | str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    if isinstance(value, str):
        cleaned = value.strip()
        try:
            datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("played_at must be an ISO-8601 timestamp") from error
        return cleaned
    raise ValueError("played_at must be a datetime or ISO-8601 timestamp")


def _clean_optional_text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())[:limit]
    return cleaned or None


def _normalize_whitespace(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Profile values must be strings")
    return " ".join(value.split())


def _collection_value_is_owned(value: object) -> bool:
    if isinstance(value, Mapping):
        owned = _coerce_bool(value.get("owned"))
        if owned is not None:
            return owned
        return _coerce_nonnegative_int(value.get("copies")) > 0
    boolean = _coerce_bool(value)
    if boolean is not None:
        return boolean
    return _coerce_nonnegative_int(value) > 0


def _known_ids(raw: object, known: set[str]) -> list[str]:
    return [value for value in _string_values(raw) if value in known]


def _string_values(raw: object) -> list[str]:
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes, Mapping)):
        return []
    result = []
    for value in raw:
        if isinstance(value, str) and value not in result:
            result.append(value)
    return result


def _materialize_ids(values: Iterable[str], kind: str) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise ValueError(f"{kind.title()} unlocks must be an iterable of IDs")
    result = list(values)
    if any(not isinstance(value, str) for value in result):
        raise ValueError(f"Every {kind} unlock must be an ID string")
    return result


def _validated_unlock_ids(
    values: Iterable[str], known: set[str], kind: str
) -> list[str]:
    result = []
    for value in _materialize_ids(values, kind):
        if value not in known:
            raise ValueError(f"Unknown {kind} ID: {value}")
        if value not in result:
            result.append(value)
    return result


def _ordered_union(existing: Iterable[str], additions: Iterable[str]) -> list[str]:
    return list(dict.fromkeys([*existing, *additions]))

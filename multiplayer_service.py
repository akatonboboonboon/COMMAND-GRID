"""In-memory online match service for COMMAND GRID.

This module is the server-side boundary between a NiceGUI session and
``game_engine``.  It deliberately has no NiceGUI dependency: every public
function accepts the user's JSON-compatible storage mapping, authenticates it
with an anonymous bearer token, and returns a JSON-compatible dictionary.

Supported flows
---------------

* ``join_queue`` pairs the casual and ranked queues.
* ``create_friend_room`` / ``join_friend_room`` pair players by a short code.
* ``submit_player_order`` locks one secret order.  The service resolves the
  round automatically as soon as both orders have arrived.
* ``poll`` is both the polling and reconnect endpoint.  ``disconnect`` marks
  a temporarily closed client and ``leave`` marks an intentional exit.
* ``claim_result`` writes a completed result to each player's own storage via
  :func:`player_state.record_result`, exactly once per match and player.
* ``close_session`` releases a completed/left player for their next match and
  garbage-collects the old match after both players have closed it.

Security and deployment constraints
-----------------------------------

The value created by ``ensure_player_token`` is a bearer credential.  It must
remain in server-backed/user-scoped storage and must not be put in a public URL
or another player's response.  Match IDs and friend codes are not credentials.
All game views come from :meth:`game_engine.GameState.view_for`, so opponent
hands, draw piles, unrevealed deployments, and pending order details stay
hidden.

State is held in one process behind :class:`threading.Lock`.  This is suitable
for a single Render process and an MVP only: multiple workers or restart-safe
matches require a shared transactional store (for example PostgreSQL/Redis).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
import secrets
from threading import Lock
from time import monotonic
from typing import Any, Mapping, MutableMapping, Sequence
from uuid import uuid4

from game_engine import (
    MAX_ROUNDS,
    GameState,
    Phase,
    RuleViolation,
    forfeit_match,
    formation_metadata,
    lookup_card,
    new_game,
    resolve_round,
    submit_order,
)
from match_service import collection_rewards_for_outcome
from player_state import (
    ensure_player_state,
    record_result,
    store_player_state,
    update_deck,
    update_formation,
)


PLAYER_TOKEN_KEY = "command_grid_player_token"
CLAIMED_MATCHES_KEY = "command_grid_claimed_matches"
MATCHMAKING_MODES = frozenset({"casual", "ranked"})
FRIEND_CODE_LENGTH = 6
_FRIEND_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{24,128}$")
_MAX_PERSISTED_CLAIMS = 100
WAITING_TTL_SECONDS = 20.0


class MultiplayerError(ValueError):
    """A stable, user-correctable matchmaking/service error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PlayerSnapshot:
    """Immutable player choices captured at queue/room entry."""

    token: str
    deck: tuple[str, ...]
    formation: str
    name: str
    icon_symbol_id: str


@dataclass(slots=True)
class FriendRoom:
    code: str
    host: PlayerSnapshot
    created_at: str


@dataclass(slots=True)
class MatchRecord:
    match_id: str
    mode: str
    game: GameState
    snapshots: dict[str, PlayerSnapshot]
    player_ids: dict[str, str]
    connected: dict[str, bool]
    last_seen: dict[str, str]
    friend_code: str | None = None
    left_tokens: set[str] = field(default_factory=set)
    claimed_tokens: set[str] = field(default_factory=set)
    closed_tokens: set[str] = field(default_factory=set)
    rewards_by_token: dict[str, dict[str, list[str]]] = field(default_factory=dict)


_lock = Lock()
_queues: dict[str, list[PlayerSnapshot]] = {"casual": [], "ranked": []}
_friend_rooms: dict[str, FriendRoom] = {}
_matches: dict[str, MatchRecord] = {}
# token -> ("queue" | "friend" | "match", identifier)
_locations: dict[str, tuple[str, str]] = {}
_waiting_last_seen: dict[str, float] = {}


def ensure_player_token(storage: MutableMapping[str, Any]) -> str:
    """Return the anonymous bearer token stored for this browser/user.

    A malformed legacy value is replaced.  The returned string is JSON-safe;
    callers should keep it in private server-backed session storage.
    """

    existing = storage.get(PLAYER_TOKEN_KEY)
    if isinstance(existing, str) and _TOKEN_PATTERN.fullmatch(existing):
        return existing
    token = secrets.token_urlsafe(32)
    storage[PLAYER_TOKEN_KEY] = token
    return token


def join_queue(
    storage: MutableMapping[str, Any],
    mode: str,
    *,
    name: str | None = None,
    deck: Sequence[str] | None = None,
    formation: str | None = None,
) -> dict[str, Any]:
    """Join ``casual`` or ``ranked`` matchmaking and pair immediately.

    Deck, formation, and display name are snapshotted at entry.  Repeating the
    call while already waiting in the same queue is idempotent; entering a
    different active session raises ``MultiplayerError('active_session', ...)``.
    """

    canonical_mode = str(mode).strip().lower()
    if canonical_mode not in MATCHMAKING_MODES:
        raise MultiplayerError("invalid_mode", "Queue mode must be casual or ranked.")
    snapshot = _make_snapshot(storage, name=name, deck=deck, formation=formation)

    with _lock:
        _cleanup_stale_waiters_locked()
        existing = _locations.get(snapshot.token)
        if existing is not None:
            if existing == ("queue", canonical_mode):
                return _poll_locked(snapshot.token, reconnect=True)
            if existing[0] == "match":
                return _poll_locked(snapshot.token, reconnect=True)
            raise MultiplayerError("active_session", "The player is already in another session.")

        queue = _queues[canonical_mode]
        opponent: PlayerSnapshot | None = None
        while queue:
            candidate = queue.pop(0)
            if _locations.get(candidate.token) == ("queue", canonical_mode):
                opponent = candidate
                break
        if opponent is None:
            queue.append(snapshot)
            _locations[snapshot.token] = ("queue", canonical_mode)
            _waiting_last_seen[snapshot.token] = monotonic()
            return _queue_view_locked(snapshot.token, canonical_mode)

        match = _start_match_locked(opponent, snapshot, canonical_mode)
        return _match_view_locked(match, snapshot.token, reconnect=True)


def cancel_waiting(storage: MutableMapping[str, Any]) -> dict[str, Any]:
    """Cancel a queue wait or an unjoined friend room.

    Active matches are not cancelled by this helper; use :func:`leave`.
    """

    token = ensure_player_token(storage)
    with _lock:
        location = _locations.get(token)
        if location is None:
            return {"status": "idle"}
        kind, identifier = location
        if kind == "queue":
            _queues[identifier] = [entry for entry in _queues[identifier] if entry.token != token]
            del _locations[token]
            _waiting_last_seen.pop(token, None)
            return {"status": "idle", "cancelled": True}
        if kind == "friend":
            room = _friend_rooms.get(identifier)
            if room is not None and room.host.token == token:
                del _friend_rooms[identifier]
            del _locations[token]
            _waiting_last_seen.pop(token, None)
            return {"status": "idle", "cancelled": True}
        raise MultiplayerError("match_active", "An active match must be left explicitly.")


def create_friend_room(
    storage: MutableMapping[str, Any],
    *,
    name: str | None = None,
    deck: Sequence[str] | None = None,
    formation: str | None = None,
) -> dict[str, Any]:
    """Create a private one-use room and return its six-character code."""

    snapshot = _make_snapshot(storage, name=name, deck=deck, formation=formation)
    with _lock:
        _cleanup_stale_waiters_locked()
        if snapshot.token in _locations:
            raise MultiplayerError("active_session", "The player is already in a session.")
        code = _new_friend_code_locked()
        room = FriendRoom(code=code, host=snapshot, created_at=_now())
        _friend_rooms[code] = room
        _locations[snapshot.token] = ("friend", code)
        _waiting_last_seen[snapshot.token] = monotonic()
        return _friend_view_locked(room)


def join_friend_room(
    storage: MutableMapping[str, Any],
    code: str,
    *,
    name: str | None = None,
    deck: Sequence[str] | None = None,
    formation: str | None = None,
) -> dict[str, Any]:
    """Join an open friend room and start its match.

    Codes are case-insensitive and whitespace is ignored at the ends.  A code
    is consumed when the second player joins, preventing a third participant.
    """

    normalized_code = str(code).strip().upper()
    snapshot = _make_snapshot(storage, name=name, deck=deck, formation=formation)
    with _lock:
        _cleanup_stale_waiters_locked()
        if snapshot.token in _locations:
            raise MultiplayerError("active_session", "The player is already in a session.")
        room = _friend_rooms.get(normalized_code)
        if room is None:
            raise MultiplayerError("room_not_found", "The friend room does not exist or is already full.")
        if room.host.token == snapshot.token:
            raise MultiplayerError("self_join", "A player cannot join their own friend room.")

        del _friend_rooms[normalized_code]
        match = _start_match_locked(
            room.host,
            snapshot,
            "friend",
            friend_code=normalized_code,
        )
        return _match_view_locked(match, snapshot.token, reconnect=True)


def poll(storage: MutableMapping[str, Any]) -> dict[str, Any]:
    """Return current queue/room/match state and reconnect this client.

    Calling this after a transient client disconnect is sufficient to mark the
    player connected again.  If process memory was restarted, the stable token
    remains valid but the response is ``{"status": "idle"}``.
    """

    token = ensure_player_token(storage)
    with _lock:
        return _poll_locked(token, reconnect=True)


def disconnect(storage: MutableMapping[str, Any]) -> dict[str, Any]:
    """Mark an active-match client temporarily disconnected.

    This does not forfeit or erase the match.  A later :func:`poll` reconnects
    the same anonymous token.
    """

    token = ensure_player_token(storage)
    with _lock:
        location = _locations.get(token)
        if location is None or location[0] != "match":
            return {"status": "idle", "disconnected": False}
        match = _matches[location[1]]
        match.connected[token] = False
        match.last_seen[token] = _now()
        return {
            "status": "disconnected",
            "match_id": match.match_id,
            "disconnected": True,
        }


def leave(storage: MutableMapping[str, Any]) -> dict[str, Any]:
    """Leave waiting or mark an intentional exit from an active match.

    Leaving an active unfinished match is a forfeit: the remaining player wins
    and both users can claim the result exactly once. Match data is retained
    until both sessions close.
    """

    token = ensure_player_token(storage)
    with _lock:
        location = _locations.get(token)
        if location is None:
            return {"status": "idle", "left": False}
        kind, identifier = location
        if kind == "queue":
            _queues[identifier] = [entry for entry in _queues[identifier] if entry.token != token]
            del _locations[token]
            _waiting_last_seen.pop(token, None)
            return {"status": "idle", "left": True}
        if kind == "friend":
            room = _friend_rooms.get(identifier)
            if room is not None and room.host.token == token:
                del _friend_rooms[identifier]
            del _locations[token]
            _waiting_last_seen.pop(token, None)
            return {"status": "idle", "left": True}

        match = _matches[identifier]
        if match.game.phase is not Phase.COMPLETE:
            forfeit_match(match.game, match.player_ids[token])
        match.left_tokens.add(token)
        match.connected[token] = False
        match.last_seen[token] = _now()
        return _match_view_locked(match, token, reconnect=False)


def close_session(storage: MutableMapping[str, Any]) -> dict[str, Any]:
    """Detach a completed/left player so they can start another match.

    A completed but unclaimed result is claimed first, preventing the close
    action from losing history or collection rewards.  A player who is still
    participating in an unfinished match must call :func:`leave` first.  The
    match record is garbage-collected only after both tokens have closed it.
    """

    token = ensure_player_token(storage)

    # Claim outside the close lock section because claim_result owns the same
    # non-reentrant process lock. The match cannot return to an earlier phase.
    with _lock:
        location = _locations.get(token)
        should_claim = False
        if location is not None and location[0] == "match":
            match = _matches.get(location[1])
            should_claim = (
                match is not None
                and match.game.phase is Phase.COMPLETE
                and token not in match.claimed_tokens
                and match.match_id not in _read_persisted_claims(storage)
            )
    if should_claim:
        claim_result(storage)

    with _lock:
        location = _locations.get(token)
        if location is None:
            return {"status": "idle", "closed": False}
        if location[0] != "match":
            raise MultiplayerError(
                "session_not_closable",
                "Only a completed or explicitly left match can be closed.",
            )
        match = _matches.get(location[1])
        if match is None:
            del _locations[token]
            return {"status": "idle", "closed": True, "match_id": location[1]}
        if match.game.phase is not Phase.COMPLETE and token not in match.left_tokens:
            raise MultiplayerError(
                "match_in_progress",
                "Leave the unfinished match before closing its session.",
            )

        del _locations[token]
        match.closed_tokens.add(token)
        match.connected[token] = False
        match.last_seen[token] = _now()
        match_id = match.match_id
        garbage_collected = match.closed_tokens == set(match.snapshots)
        if garbage_collected:
            del _matches[match_id]
        return {
            "status": "idle",
            "closed": True,
            "match_id": match_id,
            "garbage_collected": garbage_collected,
        }


def submit_player_order(
    storage: MutableMapping[str, Any],
    card_id: str,
    lane_id: str,
) -> dict[str, Any]:
    """Submit this player's secret order and resolve when both are ready.

    Formation is taken from the immutable matchmaking snapshot, preventing a
    client from changing it mid-match.  ``game_engine.RuleViolation`` is
    allowed through with stable codes such as ``order_already_submitted`` and
    ``card_not_in_hand``.  The operation is atomic within this process.
    """

    token = ensure_player_token(storage)
    with _lock:
        match = _require_match_locked(token)
        if token in match.left_tokens:
            raise MultiplayerError("player_left", "A player who left cannot submit another order.")
        opponent = _opponent_token(match, token)
        if opponent in match.left_tokens:
            raise MultiplayerError("opponent_left", "The opponent has left this match.")
        player_id = match.player_ids[token]
        snapshot = match.snapshots[token]
        submit_order(match.game, player_id, card_id, lane_id, snapshot.formation)
        if match.game.phase is Phase.RESOLVING:
            resolve_round(match.game)
        match.connected[token] = True
        match.last_seen[token] = _now()
        return _match_view_locked(match, token, reconnect=False)


def claim_result(storage: MutableMapping[str, Any]) -> dict[str, Any]:
    """Record this player's completed match result exactly once.

    The authoritative snapshot supplies mode, deck, formation, opponent, and
    points.  The update is persisted through ``store_player_state`` before the
    in-memory claim is marked.  Repeated calls return ``already_claimed`` and
    leave aggregate stats unchanged.
    """

    token = ensure_player_token(storage)
    with _lock:
        match = _require_match_locked(token)
        if match.game.phase is not Phase.COMPLETE or match.game.result is None:
            return {"claimed": False, "reason": "not_complete", "match_id": match.match_id}

        persisted_claims = _read_persisted_claims(storage)
        if token in match.claimed_tokens or match.match_id in persisted_claims:
            match.claimed_tokens.add(token)
            return {
                "claimed": False,
                "reason": "already_claimed",
                "match_id": match.match_id,
                "rewards": _copy_rewards(match.rewards_by_token.get(token)),
            }

        player_id = match.player_ids[token]
        opponent_token = _opponent_token(match, token)
        opponent_id = match.player_ids[opponent_token]
        snapshot = match.snapshots[token]
        result = match.game.result
        if result.winner_id is None:
            outcome = "draw"
        else:
            outcome = "win" if result.winner_id == player_id else "loss"

        state = ensure_player_state(storage)
        rewards = collection_rewards_for_outcome(state, outcome)
        reward_cards = rewards["cards"]
        reward_symbols = rewards["symbols"]
        updated = record_result(
            state,
            outcome,
            mode=match.mode,
            opponent=match.snapshots[opponent_token].name,
            mission_points_for=result.mission_points[player_id],
            mission_points_against=result.mission_points[opponent_id],
            turns=result.rounds_played,
            deck=snapshot.deck,
            formation=snapshot.formation,
            summary=result.summary,
            unlocked_cards=reward_cards,
            unlocked_symbols=reward_symbols,
        )
        stored = store_player_state(storage, updated)
        storage[CLAIMED_MATCHES_KEY] = [
            match.match_id,
            *[value for value in persisted_claims if value != match.match_id],
        ][:_MAX_PERSISTED_CLAIMS]
        match.claimed_tokens.add(token)
        match.rewards_by_token[token] = {
            "cards": list(reward_cards),
            "symbols": list(reward_symbols),
        }
        return {
            "claimed": True,
            "match_id": match.match_id,
            "outcome": outcome,
            "stats": dict(stored["stats"]),
            "history_entry": dict(stored["battle_history"][0]),
            "rewards": _copy_rewards(match.rewards_by_token[token]),
        }


def reset_service_for_tests() -> None:
    """Clear all process-global state.

    This is intentionally a test helper, not an administrative production API.
    It must never be exposed as a web endpoint.
    """

    with _lock:
        for mode in MATCHMAKING_MODES:
            _queues[mode].clear()
        _friend_rooms.clear()
        _matches.clear()
        _locations.clear()
        _waiting_last_seen.clear()


def _make_snapshot(
    storage: MutableMapping[str, Any],
    *,
    name: str | None,
    deck: Sequence[str] | None,
    formation: str | None,
) -> PlayerSnapshot:
    token = ensure_player_token(storage)
    state = ensure_player_state(storage)

    if deck is not None:
        try:
            state = update_deck(state, deck)
        except ValueError as error:
            raise MultiplayerError("invalid_deck", str(error)) from error
    chosen_deck = tuple(str(card_id) for card_id in state["deck"])
    if len(chosen_deck) < MAX_ROUNDS:
        raise MultiplayerError(
            "deck_too_small",
            f"Online matches require at least {MAX_ROUNDS} cards.",
        )
    try:
        for card_id in chosen_deck:
            lookup_card(card_id)
    except RuleViolation as error:
        raise MultiplayerError("invalid_deck", str(error)) from error

    if formation is not None:
        try:
            state = update_formation(state, formation)
        except ValueError as error:
            raise MultiplayerError("invalid_formation", str(error)) from error
    chosen_formation = str(state["selected_formation"])
    try:
        formation_metadata(chosen_formation)
    except RuleViolation as error:
        raise MultiplayerError("invalid_formation", str(error)) from error

    raw_name = name if name is not None else state["profile"]["display_name"]
    display_name = " ".join(str(raw_name).split())[:32] or "司令官"
    icon_symbol_id = str(state["profile"]["selected_symbol"])
    return PlayerSnapshot(
        token,
        chosen_deck,
        chosen_formation,
        display_name,
        icon_symbol_id,
    )


def _start_match_locked(
    first: PlayerSnapshot,
    second: PlayerSnapshot,
    mode: str,
    *,
    friend_code: str | None = None,
) -> MatchRecord:
    match_id = uuid4().hex
    first_id = "side_a"
    second_id = "side_b"
    game = new_game(
        first.deck,
        second.deck,
        player_id=first_id,
        opponent_id=second_id,
        player_name=first.name,
        opponent_name=second.name,
        game_id=match_id,
        max_rounds=MAX_ROUNDS,
    )
    timestamp = _now()
    record = MatchRecord(
        match_id=match_id,
        mode=mode,
        game=game,
        snapshots={first.token: first, second.token: second},
        player_ids={first.token: first_id, second.token: second_id},
        connected={first.token: True, second.token: True},
        last_seen={first.token: timestamp, second.token: timestamp},
        friend_code=friend_code,
    )
    _matches[match_id] = record
    _locations[first.token] = ("match", match_id)
    _locations[second.token] = ("match", match_id)
    _waiting_last_seen.pop(first.token, None)
    _waiting_last_seen.pop(second.token, None)
    return record


def _cleanup_stale_waiters_locked() -> None:
    """Remove queue and friend-room entries that stopped polling."""

    cutoff = monotonic() - WAITING_TTL_SECONDS
    stale_tokens = [
        token for token, last_seen in _waiting_last_seen.items()
        if last_seen < cutoff
    ]
    for token in stale_tokens:
        location = _locations.get(token)
        if location is not None:
            kind, identifier = location
            if kind == "queue":
                _queues[identifier] = [
                    entry for entry in _queues[identifier]
                    if entry.token != token
                ]
                _locations.pop(token, None)
            elif kind == "friend":
                room = _friend_rooms.get(identifier)
                if room is not None and room.host.token == token:
                    _friend_rooms.pop(identifier, None)
                _locations.pop(token, None)
        _waiting_last_seen.pop(token, None)


def _poll_locked(token: str, *, reconnect: bool) -> dict[str, Any]:
    _cleanup_stale_waiters_locked()
    location = _locations.get(token)
    if location is None:
        return {"status": "idle"}
    kind, identifier = location
    if kind == "queue":
        _waiting_last_seen[token] = monotonic()
        return _queue_view_locked(token, identifier)
    if kind == "friend":
        room = _friend_rooms.get(identifier)
        if room is None:
            del _locations[token]
            return {"status": "idle"}
        _waiting_last_seen[token] = monotonic()
        return _friend_view_locked(room)
    match = _matches.get(identifier)
    if match is None:
        del _locations[token]
        return {"status": "idle"}
    return _match_view_locked(match, token, reconnect=reconnect)


def _queue_view_locked(token: str, mode: str) -> dict[str, Any]:
    active = [entry for entry in _queues[mode] if _locations.get(entry.token) == ("queue", mode)]
    position = next((index + 1 for index, entry in enumerate(active) if entry.token == token), 1)
    return {"status": "waiting", "mode": mode, "queue_position": position}


def _friend_view_locked(room: FriendRoom) -> dict[str, Any]:
    return {
        "status": "waiting_friend",
        "mode": "friend",
        "room_code": room.code,
        "created_at": room.created_at,
    }


def _match_view_locked(
    match: MatchRecord,
    token: str,
    *,
    reconnect: bool,
) -> dict[str, Any]:
    if token not in match.player_ids:
        raise MultiplayerError("not_a_player", "This token is not a player in the match.")
    if reconnect and token not in match.left_tokens:
        match.connected[token] = True
        match.last_seen[token] = _now()
    opponent = _opponent_token(match, token)
    player_id = match.player_ids[token]

    if token in match.left_tokens:
        status = "left"
    elif match.game.phase is Phase.COMPLETE:
        status = "complete"
    elif opponent in match.left_tokens:
        status = "opponent_left"
    else:
        status = "playing"
    return {
        "status": status,
        "mode": match.mode,
        "match_id": match.match_id,
        "friend_code": match.friend_code,
        "player_id": player_id,
        "formation": match.snapshots[token].formation,
        "submitted": player_id in match.game.orders,
        "result_claimed": token in match.claimed_tokens,
        "player": {
            "name": match.snapshots[token].name,
            "icon_symbol_id": match.snapshots[token].icon_symbol_id,
        },
        "opponent": {
            "name": match.snapshots[opponent].name,
            "icon_symbol_id": match.snapshots[opponent].icon_symbol_id,
            "connected": match.connected[opponent],
            "left": opponent in match.left_tokens,
            "last_seen": match.last_seen[opponent],
        },
        "game": match.game.view_for(player_id),
    }


def _require_match_locked(token: str) -> MatchRecord:
    location = _locations.get(token)
    if location is None or location[0] != "match":
        raise MultiplayerError("no_active_match", "The player is not in an active match.")
    match = _matches.get(location[1])
    if match is None:
        del _locations[token]
        raise MultiplayerError("match_expired", "The in-memory match no longer exists.")
    return match


def _opponent_token(match: MatchRecord, token: str) -> str:
    if token not in match.player_ids:
        raise MultiplayerError("not_a_player", "This token is not a player in the match.")
    return next(candidate for candidate in match.player_ids if candidate != token)


def _new_friend_code_locked() -> str:
    for _ in range(100):
        code = "".join(secrets.choice(_FRIEND_ALPHABET) for _ in range(FRIEND_CODE_LENGTH))
        if code not in _friend_rooms:
            return code
    raise MultiplayerError("code_exhausted", "Could not allocate a friend room code.")


def _read_persisted_claims(storage: Mapping[str, Any]) -> list[str]:
    raw = storage.get(CLAIMED_MATCHES_KEY)
    if not isinstance(raw, list):
        return []
    return [value for value in raw if isinstance(value, str)][:_MAX_PERSISTED_CLAIMS]


def _copy_rewards(rewards: Mapping[str, Sequence[str]] | None) -> dict[str, list[str]]:
    if rewards is None:
        return {"cards": [], "symbols": []}
    return {
        "cards": list(rewards.get("cards", [])),
        "symbols": list(rewards.get("symbols", [])),
    }


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


__all__ = [
    "CLAIMED_MATCHES_KEY",
    "MATCHMAKING_MODES",
    "PLAYER_TOKEN_KEY",
    "MultiplayerError",
    "cancel_waiting",
    "claim_result",
    "close_session",
    "create_friend_room",
    "disconnect",
    "ensure_player_token",
    "join_friend_room",
    "join_queue",
    "leave",
    "poll",
    "reset_service_for_tests",
    "submit_player_order",
]

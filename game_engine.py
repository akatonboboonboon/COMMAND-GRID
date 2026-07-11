"""Deterministic, UI-independent rules engine for COMMAND GRID.

The engine intentionally keeps the first playable ruleset small:

* two players, three lanes and nine rounds;
* each player secretly assigns one card to one lane each round;
* orders resolve as deploy -> recon -> supply/support/control -> scoring;
* a player earns one mission point for every lane they lead each round;
* after round nine, controlling more of the three lanes decides the winner;
* mission points break a tied lane count, and equal points are a draw.

All mutations happen through the functions in this module.  NiceGUI, an API,
or a deterministic AI can therefore drive the same match without duplicating
game rules.  ``GameState.to_dict`` is a complete save format, while
``GameState.view_for`` redacts hidden information for one player.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable, Mapping, Sequence

from game_data import STARTER_DECK, UnitCard, get_card, get_formation


LANE_IDS: tuple[str, ...] = ("left", "center", "right")
LANE_LABELS: dict[str, str] = {
    "left": "左翼",
    "center": "中央",
    "right": "右翼",
}
MAX_ROUNDS = 9
MISSION_POINTS_PER_LANE = 1
ARMOR_SUPPLY_BONUS = 2

# The value is metadata only; card balance continues to come from game_data.
# Unknown future echelons remain playable and simply receive ``rank=None``.
FORMATION_SCALE: dict[str, int] = {
    "班": 1,
    "分隊": 2,
    "小隊": 3,
    "中隊": 4,
    "大隊": 5,
    "連隊": 6,
    "旅団": 7,
    "師団": 8,
    "軍団": 9,
    "軍": 10,
    "軍集団": 11,
    "総軍": 12,
}


class Phase(StrEnum):
    PLANNING = "planning"
    RESOLVING = "resolving"
    COMPLETE = "complete"


class RuleViolation(ValueError):
    """A safe, user-correctable game rule error.

    ``code`` is stable for UI/API handling; the human message may be shown to
    a player directly.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise RuleViolation(code, message)


def lookup_card(card_id: str) -> UnitCard:
    """Look a card up through :mod:`game_data` with a rules-friendly error."""

    _require(isinstance(card_id, str) and bool(card_id), "invalid_card", "カードIDが空です。")
    try:
        return get_card(card_id)
    except KeyError as exc:
        raise RuleViolation("unknown_card", f"存在しないカードです: {card_id}") from exc


def formation_metadata(formation_id: str | None = None) -> dict[str, Any]:
    """Return the canonical formation selector metadata from ``game_data``."""

    requested = "native" if formation_id is None else str(formation_id)
    formation = get_formation(requested)
    _require(
        formation.id == requested,
        "unknown_formation",
        f"存在しない編制規模です: {requested}",
    )
    return {
        "id": formation.id,
        "name": formation.name,
        "marker": formation.marker,
        "catalog_symbol_id": formation.catalog_symbol_id,
    }


def card_metadata(card_id: str, formation_id: str | None = None) -> dict[str, Any]:
    """Return UI-safe card and formation metadata from the canonical lookup."""

    card = lookup_card(card_id)
    formation = formation_metadata(formation_id)
    effective_echelon = card.echelon if formation["id"] == "native" else formation["name"]
    rank = FORMATION_SCALE.get(effective_echelon)
    return {
        "id": card.id,
        "name": card.name,
        "branch": card.branch,
        "symbol": card.symbol,
        "echelon": effective_echelon,
        "native_echelon": card.echelon,
        "formation_rank": rank,
        "large_formation": rank is not None and rank >= FORMATION_SCALE["旅団"],
        "formation": formation,
        "cost": card.cost,
        "control": card.control,
        "support": card.support,
        "recon": card.recon,
        "supply": card.supply,
    }


@dataclass(slots=True)
class Order:
    player_id: str
    card_id: str
    lane_id: str
    round_no: int
    formation_id: str = "native"

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "card_id": self.card_id,
            "lane_id": self.lane_id,
            "round_no": self.round_no,
            "formation_id": self.formation_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Order:
        return cls(
            player_id=str(data["player_id"]),
            card_id=str(data["card_id"]),
            lane_id=str(data["lane_id"]),
            round_no=int(data["round_no"]),
            formation_id=str(data.get("formation_id", "native")),
        )


@dataclass(slots=True)
class Deployment:
    deployment_id: str
    player_id: str
    card_id: str
    lane_id: str
    round_deployed: int
    formation_id: str = "native"
    revealed_to: list[str] = field(default_factory=list)

    def visible_to(self, player_id: str) -> bool:
        return player_id == self.player_id or player_id in self.revealed_to

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "player_id": self.player_id,
            "card_id": self.card_id,
            "lane_id": self.lane_id,
            "round_deployed": self.round_deployed,
            "formation_id": self.formation_id,
            "revealed_to": list(self.revealed_to),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Deployment:
        return cls(
            deployment_id=str(data["deployment_id"]),
            player_id=str(data["player_id"]),
            card_id=str(data["card_id"]),
            lane_id=str(data["lane_id"]),
            round_deployed=int(data["round_deployed"]),
            formation_id=str(data.get("formation_id", "native")),
            revealed_to=[str(value) for value in data.get("revealed_to", [])],
        )


@dataclass(slots=True)
class LanePower:
    """An explainable lane-strength calculation for one player.

    Control is the front-line value. Support contributes only when at least
    one control point is present. Negative supply is demand; an unmet point of
    demand removes one power. Fully supplied armor gains +2 each.
    Recon does not add power: it reveals hidden opposing deployments instead.
    """

    control: int = 0
    support: int = 0
    active_support: int = 0
    recon: int = 0
    supply_generated: int = 0
    supply_demand: int = 0
    supply_deficit: int = 0
    armor_count: int = 0
    armor_supply_bonus: int = 0
    total: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "control": self.control,
            "support": self.support,
            "active_support": self.active_support,
            "recon": self.recon,
            "supply_generated": self.supply_generated,
            "supply_demand": self.supply_demand,
            "supply_deficit": self.supply_deficit,
            "armor_count": self.armor_count,
            "armor_supply_bonus": self.armor_supply_bonus,
            "total": self.total,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LanePower:
        return cls(**{name: int(data.get(name, 0)) for name in cls.__dataclass_fields__})


@dataclass(slots=True)
class LaneState:
    lane_id: str
    label: str
    deployments: list[Deployment] = field(default_factory=list)
    last_power: dict[str, LanePower] = field(default_factory=dict)
    round_winners: list[str | None] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lane_id": self.lane_id,
            "label": self.label,
            "deployments": [deployment.to_dict() for deployment in self.deployments],
            "last_power": {
                player_id: power.to_dict() for player_id, power in self.last_power.items()
            },
            "round_winners": list(self.round_winners),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LaneState:
        return cls(
            lane_id=str(data["lane_id"]),
            label=str(data["label"]),
            deployments=[Deployment.from_dict(value) for value in data.get("deployments", [])],
            last_power={
                str(player_id): LanePower.from_dict(value)
                for player_id, value in data.get("last_power", {}).items()
            },
            round_winners=[
                None if value is None else str(value) for value in data.get("round_winners", [])
            ],
        )


@dataclass(slots=True)
class PlayerState:
    player_id: str
    name: str
    hand: list[str]
    draw_pile: list[str]
    mission_points: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "hand": list(self.hand),
            "draw_pile": list(self.draw_pile),
            "mission_points": self.mission_points,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PlayerState:
        return cls(
            player_id=str(data["player_id"]),
            name=str(data["name"]),
            hand=[str(value) for value in data.get("hand", [])],
            draw_pile=[str(value) for value in data.get("draw_pile", [])],
            mission_points=int(data.get("mission_points", 0)),
        )


@dataclass(slots=True)
class GameEvent:
    sequence: int
    round_no: int
    kind: str
    message: str
    player_id: str | None = None
    lane_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    visible_to: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "round_no": self.round_no,
            "kind": self.kind,
            "message": self.message,
            "player_id": self.player_id,
            "lane_id": self.lane_id,
            "details": dict(self.details),
            "visible_to": None if self.visible_to is None else list(self.visible_to),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GameEvent:
        visible = data.get("visible_to")
        return cls(
            sequence=int(data["sequence"]),
            round_no=int(data["round_no"]),
            kind=str(data["kind"]),
            message=str(data["message"]),
            player_id=None if data.get("player_id") is None else str(data["player_id"]),
            lane_id=None if data.get("lane_id") is None else str(data["lane_id"]),
            details=dict(data.get("details", {})),
            visible_to=None if visible is None else [str(value) for value in visible],
        )


@dataclass(slots=True)
class MatchResult:
    outcome: str
    winner_id: str | None
    mission_points: dict[str, int]
    rounds_played: int
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "winner_id": self.winner_id,
            "mission_points": dict(self.mission_points),
            "rounds_played": self.rounds_played,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MatchResult:
        winner = data.get("winner_id")
        return cls(
            outcome=str(data["outcome"]),
            winner_id=None if winner is None else str(winner),
            mission_points={str(key): int(value) for key, value in data["mission_points"].items()},
            rounds_played=int(data["rounds_played"]),
            summary=str(data["summary"]),
        )


@dataclass(slots=True)
class RoundResolution:
    round_no: int
    lane_power: dict[str, dict[str, LanePower]]
    lane_winners: dict[str, str | None]
    mission_points: dict[str, int]
    match_complete: bool
    winner_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_no": self.round_no,
            "lane_power": {
                lane_id: {
                    player_id: power.to_dict() for player_id, power in powers.items()
                }
                for lane_id, powers in self.lane_power.items()
            },
            "lane_winners": dict(self.lane_winners),
            "mission_points": dict(self.mission_points),
            "match_complete": self.match_complete,
            "winner_id": self.winner_id,
        }


@dataclass(slots=True)
class GameState:
    game_id: str
    round_no: int
    max_rounds: int
    phase: Phase
    player_order: tuple[str, str]
    players: dict[str, PlayerState]
    lanes: dict[str, LaneState]
    orders: dict[str, Order] = field(default_factory=dict)
    events: list[GameEvent] = field(default_factory=list)
    result: MatchResult | None = None
    next_event_sequence: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Return the complete authoritative save state (including secrets)."""

        return {
            "version": 1,
            "game_id": self.game_id,
            "round_no": self.round_no,
            "max_rounds": self.max_rounds,
            "phase": self.phase.value,
            "player_order": list(self.player_order),
            "players": {key: value.to_dict() for key, value in self.players.items()},
            "lanes": {key: value.to_dict() for key, value in self.lanes.items()},
            "orders": {key: value.to_dict() for key, value in self.orders.items()},
            "events": [event.to_dict() for event in self.events],
            "result": None if self.result is None else self.result.to_dict(),
            "next_event_sequence": self.next_event_sequence,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GameState:
        _require(int(data.get("version", 1)) == 1, "unsupported_save", "未対応の保存形式です。")
        player_order_values = tuple(str(value) for value in data["player_order"])
        _require(len(player_order_values) == 2, "invalid_state", "対戦者は2人必要です。")
        state = cls(
            game_id=str(data["game_id"]),
            round_no=int(data["round_no"]),
            max_rounds=int(data["max_rounds"]),
            phase=Phase(str(data["phase"])),
            player_order=(player_order_values[0], player_order_values[1]),
            players={
                str(key): PlayerState.from_dict(value) for key, value in data["players"].items()
            },
            lanes={str(key): LaneState.from_dict(value) for key, value in data["lanes"].items()},
            orders={str(key): Order.from_dict(value) for key, value in data.get("orders", {}).items()},
            events=[GameEvent.from_dict(value) for value in data.get("events", [])],
            result=(
                None
                if data.get("result") is None
                else MatchResult.from_dict(data["result"])
            ),
            next_event_sequence=int(data.get("next_event_sequence", 1)),
        )
        validate_state(state)
        return state

    def view_for(self, player_id: str) -> dict[str, Any]:
        """Return a JSON-safe state with the opponent's secrets redacted."""

        _player(self, player_id)
        opponent_id = (
            self.player_order[1]
            if player_id == self.player_order[0]
            else self.player_order[0]
        )
        view = self.to_dict()
        for other_id, player_data in view["players"].items():
            if other_id == player_id:
                player_data["hand_cards"] = [card_metadata(card_id) for card_id in player_data["hand"]]
                continue
            player_data["hand_count"] = len(player_data["hand"])
            player_data["draw_count"] = len(player_data["draw_pile"])
            player_data.pop("hand", None)
            player_data.pop("draw_pile", None)

        hidden_opponent_lanes: set[str] = set()
        for lane_id, lane_data in view["lanes"].items():
            if any(
                deployment.player_id == opponent_id
                and not deployment.visible_to(player_id)
                for deployment in self.lanes[lane_id].deployments
            ):
                hidden_opponent_lanes.add(lane_id)
                lane_data["last_power"].pop(opponent_id, None)
            for deployment_data in lane_data["deployments"]:
                source = _deployment_by_id(self, deployment_data["deployment_id"])
                if source.visible_to(player_id) or self.phase is Phase.COMPLETE:
                    deployment_data["hidden"] = False
                    deployment_data["card"] = card_metadata(source.card_id, source.formation_id)
                else:
                    deployment_data["hidden"] = True
                    deployment_data["card_id"] = None
                    deployment_data["card"] = None
                    deployment_data["revealed_to"] = []

        redacted_orders: dict[str, Any] = {}
        for owner_id, order_data in view["orders"].items():
            redacted_orders[owner_id] = (
                order_data if owner_id == player_id else {"player_id": owner_id, "submitted": True}
            )
        view["orders"] = redacted_orders

        visible_events: list[dict[str, Any]] = []
        for event in self.events:
            if event.visible_to is not None and player_id not in event.visible_to:
                continue
            event_data = event.to_dict()
            event_data.pop("visible_to", None)
            if event.kind == "lane_scored" and event.lane_id in hidden_opponent_lanes:
                event_data["details"] = {
                    "winner_id": event.details.get("winner_id"),
                    "power_hidden": True,
                }
            visible_events.append(event_data)
        view["events"] = visible_events
        return view


def _event(
    state: GameState,
    kind: str,
    message: str,
    *,
    player_id: str | None = None,
    lane_id: str | None = None,
    details: Mapping[str, Any] | None = None,
    visible_to: list[str] | None = None,
) -> None:
    state.events.append(
        GameEvent(
            sequence=state.next_event_sequence,
            round_no=state.round_no,
            kind=kind,
            message=message,
            player_id=player_id,
            lane_id=lane_id,
            details=dict(details or {}),
            visible_to=visible_to,
        )
    )
    state.next_event_sequence += 1


def _validate_deck(deck: Sequence[str], owner: str, max_rounds: int) -> list[str]:
    _require(not isinstance(deck, (str, bytes)), "invalid_deck", f"{owner}のデッキ形式が不正です。")
    cards = [str(card_id) for card_id in deck]
    _require(
        len(cards) >= max_rounds,
        "deck_too_small",
        f"{owner}のデッキには最低{max_rounds}枚必要です。",
    )
    for card_id in cards:
        lookup_card(card_id)
    return cards


def new_game(
    player_deck: Sequence[str] = STARTER_DECK,
    opponent_deck: Sequence[str] | None = None,
    *,
    player_id: str = "player",
    opponent_id: str = "opponent",
    player_name: str = "あなた",
    opponent_name: str = "対戦相手",
    game_id: str = "command-grid-local",
    opening_hand_size: int | None = None,
    max_rounds: int = MAX_ROUNDS,
) -> GameState:
    """Create a match without randomness.

    Cards are kept in the exact deck order supplied. By default the full deck
    is available in hand, making the beginner game (and the division card)
    immediately usable. Pass ``opening_hand_size=5`` for draw-pile play.
    """

    _require(bool(player_id) and bool(opponent_id), "invalid_player", "プレイヤーIDが空です。")
    _require(player_id != opponent_id, "duplicate_player", "プレイヤーIDは別々にしてください。")
    _require(max_rounds > 0, "invalid_rounds", "ラウンド数は1以上必要です。")
    first_deck = _validate_deck(player_deck, player_name, max_rounds)
    second_deck = _validate_deck(
        opponent_deck if opponent_deck is not None else player_deck,
        opponent_name,
        max_rounds,
    )

    if opening_hand_size is None:
        first_hand_size = len(first_deck)
        second_hand_size = len(second_deck)
    else:
        _require(opening_hand_size > 0, "invalid_hand_size", "初期手札は1枚以上必要です。")
        first_hand_size = min(opening_hand_size, len(first_deck))
        second_hand_size = min(opening_hand_size, len(second_deck))

    players = {
        player_id: PlayerState(
            player_id,
            player_name,
            first_deck[:first_hand_size],
            first_deck[first_hand_size:],
        ),
        opponent_id: PlayerState(
            opponent_id,
            opponent_name,
            second_deck[:second_hand_size],
            second_deck[second_hand_size:],
        ),
    }
    state = GameState(
        game_id=game_id,
        round_no=1,
        max_rounds=max_rounds,
        phase=Phase.PLANNING,
        player_order=(player_id, opponent_id),
        players=players,
        lanes={
            lane_id: LaneState(lane_id=lane_id, label=LANE_LABELS[lane_id])
            for lane_id in LANE_IDS
        },
    )
    _event(state, "match_started", f"{max_rounds}ラウンドの対戦を開始しました。")
    validate_state(state)
    return state


def _player(state: GameState, player_id: str) -> PlayerState:
    try:
        return state.players[player_id]
    except KeyError as exc:
        raise RuleViolation("unknown_player", f"存在しないプレイヤーです: {player_id}") from exc


def _lane(state: GameState, lane_id: str) -> LaneState:
    try:
        return state.lanes[lane_id]
    except KeyError as exc:
        raise RuleViolation("unknown_lane", f"存在しない戦線です: {lane_id}") from exc


def _opponent_id(state: GameState, player_id: str) -> str:
    _player(state, player_id)
    return state.player_order[1] if player_id == state.player_order[0] else state.player_order[0]


def _deployment_by_id(state: GameState, deployment_id: str) -> Deployment:
    for lane in state.lanes.values():
        for deployment in lane.deployments:
            if deployment.deployment_id == deployment_id:
                return deployment
    raise RuleViolation("invalid_state", f"配備データが見つかりません: {deployment_id}")


def submit_order(
    state: GameState,
    player_id: str,
    card_id: str,
    lane_id: str,
    formation_id: str | None = None,
) -> Order:
    """Lock one secret deployment order for the current round."""

    _require(state.phase is Phase.PLANNING, "wrong_phase", "現在は命令を選べません。")
    player = _player(state, player_id)
    _lane(state, lane_id)
    lookup_card(card_id)
    formation = formation_metadata(formation_id)
    _require(player_id not in state.orders, "order_already_submitted", "このラウンドの命令は確定済みです。")
    _require(card_id in player.hand, "card_not_in_hand", "そのカードは手札にありません。")

    order = Order(player_id, card_id, lane_id, state.round_no, formation["id"])
    state.orders[player_id] = order
    _event(
        state,
        "order_submitted",
        f"{player.name}が命令を確定しました。",
        player_id=player_id,
    )
    if set(state.orders) == set(state.player_order):
        state.phase = Phase.RESOLVING
    return order


def cancel_order(state: GameState, player_id: str) -> None:
    """Cancel an order while the opponent has not yet locked theirs."""

    _require(state.phase is Phase.PLANNING, "wrong_phase", "命令の受付は終了しています。")
    _player(state, player_id)
    _require(player_id in state.orders, "no_order", "取り消す命令がありません。")
    del state.orders[player_id]
    _event(state, "order_cancelled", "命令を選び直します。", player_id=player_id, visible_to=[player_id])


def forfeit_match(state: GameState, player_id: str) -> MatchResult:
    """Finish an active match when one player intentionally withdraws."""

    _require(state.phase is not Phase.COMPLETE, "match_complete", "対戦はすでに終了しています。")
    forfeiting = _player(state, player_id)
    winner_id = _opponent_id(state, player_id)
    winner = _player(state, winner_id)
    state.orders.clear()
    state.result = MatchResult(
        outcome="win",
        winner_id=winner_id,
        mission_points={
            owner_id: state.players[owner_id].mission_points
            for owner_id in state.player_order
        },
        rounds_played=state.round_no,
        summary=f"{forfeiting.name}が退出したため、{winner.name}の不戦勝です。",
    )
    state.phase = Phase.COMPLETE
    _event(
        state,
        "match_forfeited",
        state.result.summary,
        player_id=winner_id,
        details={"winner_id": winner_id, "forfeiting_player_id": player_id},
    )
    validate_state(state)
    return state.result


def calculate_lane_power(
    state: GameState,
    lane_id: str,
    player_id: str,
    *,
    visible_to: str | None = None,
) -> LanePower:
    """Calculate one player's explainable power in a lane.

    Supplying armor means meeting *all* demand in that lane. This keeps the
    beginner rule binary: green supply means every armor unit gets +2; red
    supply means the remaining deficit is subtracted instead.
    """

    lane = _lane(state, lane_id)
    _player(state, player_id)
    deployments = [deployment for deployment in lane.deployments if deployment.player_id == player_id]
    if visible_to is not None and visible_to != player_id:
        deployments = [deployment for deployment in deployments if deployment.visible_to(visible_to)]
    cards = [lookup_card(deployment.card_id) for deployment in deployments]
    control = sum(card.control for card in cards)
    support = sum(card.support for card in cards)
    recon = sum(card.recon for card in cards)
    generated = sum(max(0, card.supply) for card in cards)
    demand = sum(abs(min(0, card.supply)) for card in cards)
    deficit = max(0, demand - generated)
    armor_count = sum(card.branch == "機甲" for card in cards)
    active_support = support if control > 0 else 0
    armor_bonus = ARMOR_SUPPLY_BONUS * armor_count if armor_count and generated >= demand else 0
    total = max(0, control + active_support + armor_bonus - deficit)
    return LanePower(
        control=control,
        support=support,
        active_support=active_support,
        recon=recon,
        supply_generated=generated,
        supply_demand=demand,
        supply_deficit=deficit,
        armor_count=armor_count,
        armor_supply_bonus=armor_bonus,
        total=total,
    )


def _project_lane_power(current: LanePower, card: UnitCard) -> LanePower:
    """Calculate the lane power after adding ``card`` without mutating state."""

    control = current.control + card.control
    support = current.support + card.support
    generated = current.supply_generated + max(0, card.supply)
    demand = current.supply_demand + abs(min(0, card.supply))
    deficit = max(0, demand - generated)
    armor_branch = lookup_card("armor_1").branch
    armor_count = current.armor_count + int(card.branch == armor_branch)
    active_support = support if control > 0 else 0
    armor_bonus = ARMOR_SUPPLY_BONUS * armor_count if armor_count and generated >= demand else 0
    total = max(0, control + active_support + armor_bonus - deficit)
    return LanePower(
        control=control,
        support=support,
        active_support=active_support,
        recon=current.recon + card.recon,
        supply_generated=generated,
        supply_demand=demand,
        supply_deficit=deficit,
        armor_count=armor_count,
        armor_supply_bonus=armor_bonus,
        total=total,
    )


def _estimated_enemy_power(
    state: GameState,
    lane_id: str,
    player_id: str,
    opponent_id: str,
) -> tuple[float, int]:
    """Estimate a hidden enemy lane using only information available to the AI.

    The public winner of the previous round gives a useful upper/lower bound,
    while every still-hidden deployment contributes a conservative estimate.
    No card identity or pending opponent order is inspected.
    """

    lane = state.lanes[lane_id]
    own = calculate_lane_power(state, lane_id, player_id)
    seen = calculate_lane_power(state, lane_id, opponent_id, visible_to=player_id)
    hidden_count = sum(
        deployment.player_id == opponent_id and not deployment.visible_to(player_id)
        for deployment in lane.deployments
    )
    estimate = float(seen.total) + hidden_count * 3.0
    latest_winner = lane.round_winners[-1] if lane.round_winners else None
    if latest_winner == opponent_id:
        estimate = max(estimate, float(own.total + 1))
    elif latest_winner == player_id:
        estimate = min(estimate, float(max(0, own.total - 1)))
    elif lane.round_winners:
        estimate = float(own.total)
    return estimate, hidden_count


def choose_ai_order(state: GameState, player_id: str) -> Order:
    """Choose a legal order with a stable, multi-front heuristic.

    The AI aims to finish with at least two lanes instead of repeatedly adding
    power to one safe lane. It weighs the easiest lane to capture, threatened
    lanes it already controls, visible and inferred enemy pressure, remaining
    rounds, and the actual power gained by supply/support combinations. Recon
    is valued only where hidden enemy deployments can be revealed. Equal
    choices preserve hand order and left/center/right order.
    """

    _require(state.phase is Phase.PLANNING, "wrong_phase", "AIは現在命令を選べません。")
    player = _player(state, player_id)
    _require(player_id not in state.orders, "order_already_submitted", "AIの命令は確定済みです。")
    _require(bool(player.hand), "empty_hand", "AIの手札がありません。")
    opponent_id = _opponent_id(state, player_id)

    latest_winners = {
        lane_id: (
            state.lanes[lane_id].round_winners[-1]
            if state.lanes[lane_id].round_winners
            else None
        )
        for lane_id in LANE_IDS
    }
    controlled_count = sum(winner == player_id for winner in latest_winners.values())
    own_deployment_counts = {
        lane_id: sum(
            deployment.player_id == player_id
            for deployment in state.lanes[lane_id].deployments
        )
        for lane_id in LANE_IDS
    }
    least_committed = min(own_deployment_counts.values())
    remaining_rounds = state.max_rounds - state.round_no + 1
    endgame_weight = 1.6 if remaining_rounds <= 3 else 1.0

    best: tuple[float, str, str] | None = None
    for card_id in player.hand:
        card = lookup_card(card_id)
        for lane_id in LANE_IDS:
            lane = state.lanes[lane_id]
            own = calculate_lane_power(state, lane_id, player_id)
            enemy_estimate, hidden_enemy = _estimated_enemy_power(
                state, lane_id, player_id, opponent_id
            )
            projected = _project_lane_power(own, card)
            power_gain = projected.total - own.total
            current_winner = latest_winners[lane_id]
            before_margin = own.total - enemy_estimate
            projected_margin = projected.total - enemy_estimate

            # Actual lane-power gain naturally captures front-line support,
            # fixing a supply deficit, and the fully-supplied armor bonus.
            score = power_gain * 2.0
            score += min(card.recon, hidden_enemy) * 2.5

            if current_winner != player_id:
                # With fewer than two lanes, opening/capturing another front is
                # the primary objective. Prefer a reachable lane over a hopeless
                # attempt to match a heavily fortified enemy lane.
                score += (9.0 if controlled_count < 2 else 3.0) * endgame_weight
                score += max(0.0, 6.0 - abs(before_margin))
                if projected_margin > 0:
                    score += 7.0 * endgame_weight
                else:
                    score += min(float(power_gain), max(0.0, -before_margin))
                    score -= max(0.0, -projected_margin - 5.0) * 0.8
            else:
                # Defend a narrow lead, especially when exactly two lanes are
                # held. A safe lane with a large surplus receives little value.
                if before_margin <= 3:
                    score += (6.0 if controlled_count <= 2 else 3.0) * endgame_weight
                    score += max(0.0, 4.0 - before_margin)
                elif controlled_count <= 2 and remaining_rounds <= 3:
                    score += 2.0
                score -= max(0.0, before_margin - 4.0) * 1.4

            enemy_deployments = sum(
                deployment.player_id == opponent_id for deployment in lane.deployments
            )
            score += min(enemy_deployments, 4) * (0.7 if before_margin <= 3 else 0.2)

            # Avoid piling cards into the most occupied or already overpowered
            # lane when another front can still contribute to a two-lane win.
            excess_commitment = own_deployment_counts[lane_id] - least_committed
            score -= excess_commitment * 1.8
            score -= max(0.0, projected_margin - 7.0) * 0.6

            if best is None or score > best[0]:
                best = (score, card_id, lane_id)

    _require(best is not None, "no_legal_order", "AIが出せる命令がありません。")
    return Order(
        player_id=player_id,
        card_id=best[1],
        lane_id=best[2],
        round_no=state.round_no,
        formation_id="native",
    )


def play_ai_turn(state: GameState, player_id: str) -> Order:
    order = choose_ai_order(state, player_id)
    return submit_order(
        state,
        order.player_id,
        order.card_id,
        order.lane_id,
        order.formation_id,
    )


def _deploy_orders(state: GameState) -> None:
    for player_id in state.player_order:
        player = state.players[player_id]
        order = state.orders[player_id]
        _require(order.round_no == state.round_no, "stale_order", "古いラウンドの命令が含まれています。")
        _require(order.card_id in player.hand, "card_not_in_hand", "命令カードが手札にありません。")
        player.hand.remove(order.card_id)
        deployment = Deployment(
            deployment_id=f"{state.game_id}:{state.round_no}:{player_id}",
            player_id=player_id,
            card_id=order.card_id,
            lane_id=order.lane_id,
            round_deployed=state.round_no,
            formation_id=order.formation_id,
            revealed_to=[player_id],
        )
        state.lanes[order.lane_id].deployments.append(deployment)
        _event(
            state,
            "deployed",
            f"{player.name}が{LANE_LABELS[order.lane_id]}へ部隊を配備しました。",
            player_id=player_id,
            lane_id=order.lane_id,
        )
        _event(
            state,
            "own_card_deployed",
            (
                f"{formation_metadata(order.formation_id)['name']}編制の"
                f"{lookup_card(order.card_id).name}を{LANE_LABELS[order.lane_id]}へ配備しました。"
            ),
            player_id=player_id,
            lane_id=order.lane_id,
            details={"card_id": order.card_id, "formation_id": order.formation_id},
            visible_to=[player_id],
        )


def _resolve_recon(state: GameState) -> None:
    for player_id in state.player_order:
        opponent_id = _opponent_id(state, player_id)
        for lane_id in LANE_IDS:
            recon = calculate_lane_power(state, lane_id, player_id).recon
            if recon <= 0:
                continue
            hidden = [
                deployment
                for deployment in state.lanes[lane_id].deployments
                if deployment.player_id == opponent_id and not deployment.visible_to(player_id)
            ]
            # Newest threats are revealed first; deployment_id makes the order stable.
            hidden.sort(key=lambda deployment: (-deployment.round_deployed, deployment.deployment_id))
            for deployment in hidden[:recon]:
                deployment.revealed_to.append(player_id)
                card = lookup_card(deployment.card_id)
                _event(
                    state,
                    "recon_reveal",
                    f"偵察で{LANE_LABELS[lane_id]}の{card.name}を発見しました。",
                    player_id=player_id,
                    lane_id=lane_id,
                    details={
                        "deployment_id": deployment.deployment_id,
                        "card_id": deployment.card_id,
                    },
                    visible_to=[player_id],
                )


def _draw_one(player: PlayerState) -> str | None:
    if not player.draw_pile:
        return None
    card_id = player.draw_pile.pop(0)
    player.hand.append(card_id)
    return card_id


def _finish_match(state: GameState) -> None:
    points = {player_id: state.players[player_id].mission_points for player_id in state.player_order}
    first_id, second_id = state.player_order
    lanes_controlled = {player_id: 0 for player_id in state.player_order}
    for lane_id in LANE_IDS:
        first_power = calculate_lane_power(state, lane_id, first_id).total
        second_power = calculate_lane_power(state, lane_id, second_id).total
        if first_power > second_power:
            lanes_controlled[first_id] += 1
        elif second_power > first_power:
            lanes_controlled[second_id] += 1

    if lanes_controlled[first_id] != lanes_controlled[second_id]:
        winner_id = (
            first_id
            if lanes_controlled[first_id] > lanes_controlled[second_id]
            else second_id
        )
        state.result = MatchResult(
            outcome="win",
            winner_id=winner_id,
            mission_points=points,
            rounds_played=state.round_no,
            summary=(
                f"{state.players[winner_id].name}が"
                f"{lanes_controlled[winner_id]}戦線を確保して勝利しました。"
            ),
        )
    elif points[first_id] == points[second_id]:
        state.result = MatchResult(
            outcome="draw",
            winner_id=None,
            mission_points=points,
            rounds_played=state.round_no,
            summary=(
                f"確保戦線も任務点も同じため、"
                f"{points[first_id]}対{points[second_id]}で引き分けです。"
            ),
        )
    else:
        winner_id = first_id if points[first_id] > points[second_id] else second_id
        loser_id = second_id if winner_id == first_id else first_id
        state.result = MatchResult(
            outcome="win",
            winner_id=winner_id,
            mission_points=points,
            rounds_played=state.round_no,
            summary=(
                f"確保戦線が同数のため任務点で判定し、{state.players[winner_id].name}が"
                f"{points[winner_id]}対{points[loser_id]}で勝利しました。"
            ),
        )
    state.phase = Phase.COMPLETE
    _event(
        state,
        "match_complete",
        state.result.summary,
        player_id=state.result.winner_id,
        details=state.result.to_dict(),
    )


def resolve_round(state: GameState) -> RoundResolution:
    """Resolve both locked orders and advance or complete the match."""

    _require(state.phase is Phase.RESOLVING, "wrong_phase", "両者の命令がまだ揃っていません。")
    _require(set(state.orders) == set(state.player_order), "missing_order", "両者の命令が必要です。")
    resolving_round = state.round_no

    _deploy_orders(state)
    _resolve_recon(state)

    lane_power: dict[str, dict[str, LanePower]] = {}
    lane_winners: dict[str, str | None] = {}
    for lane_id in LANE_IDS:
        lane = state.lanes[lane_id]
        powers = {
            player_id: calculate_lane_power(state, lane_id, player_id)
            for player_id in state.player_order
        }
        lane.last_power = powers
        first_id, second_id = state.player_order
        if powers[first_id].total == powers[second_id].total:
            winner_id = None
            message = f"{lane.label}は{powers[first_id].total}対{powers[second_id].total}で互角です。"
        else:
            winner_id = first_id if powers[first_id].total > powers[second_id].total else second_id
            state.players[winner_id].mission_points += MISSION_POINTS_PER_LANE
            message = (
                f"{lane.label}は{state.players[winner_id].name}が確保し、"
                f"任務ポイントを{MISSION_POINTS_PER_LANE}獲得しました。"
            )
        lane.round_winners.append(winner_id)
        lane_power[lane_id] = powers
        lane_winners[lane_id] = winner_id
        _event(
            state,
            "lane_scored",
            message,
            player_id=winner_id,
            lane_id=lane_id,
            details={
                "winner_id": winner_id,
                "power": {key: value.to_dict() for key, value in powers.items()},
            },
        )

    state.orders.clear()
    if resolving_round >= state.max_rounds:
        _finish_match(state)
    else:
        for player_id in state.player_order:
            player = state.players[player_id]
            drawn = _draw_one(player)
            if drawn is not None:
                _event(
                    state,
                    "card_drawn",
                    f"{lookup_card(drawn).name}を引きました。",
                    player_id=player_id,
                    details={"card_id": drawn},
                    visible_to=[player_id],
                )
        state.round_no += 1
        state.phase = Phase.PLANNING
        _event(state, "round_started", f"ラウンド{state.round_no}を開始します。")

    validate_state(state)
    return RoundResolution(
        round_no=resolving_round,
        lane_power=lane_power,
        lane_winners=lane_winners,
        mission_points={
            player_id: state.players[player_id].mission_points for player_id in state.player_order
        },
        match_complete=state.phase is Phase.COMPLETE,
        winner_id=None if state.result is None else state.result.winner_id,
    )


def play_round_with_ai(
    state: GameState,
    human_id: str,
    card_id: str,
    lane_id: str,
    *,
    ai_id: str | None = None,
    formation_id: str | None = None,
) -> RoundResolution:
    """Convenience transaction for a local human-versus-AI screen."""

    resolved_ai_id = ai_id if ai_id is not None else _opponent_id(state, human_id)
    _require(resolved_ai_id != human_id, "duplicate_player", "AIと人間のIDが同じです。")
    submit_order(state, human_id, card_id, lane_id, formation_id)
    play_ai_turn(state, resolved_ai_id)
    return resolve_round(state)


def validate_state(state: GameState) -> None:
    """Fail fast when loading or integrating a corrupted match state."""

    _require(len(state.player_order) == 2, "invalid_state", "対戦者は2人必要です。")
    _require(len(set(state.player_order)) == 2, "invalid_state", "対戦者IDが重複しています。")
    _require(set(state.players) == set(state.player_order), "invalid_state", "対戦者データが一致しません。")
    _require(set(state.lanes) == set(LANE_IDS), "invalid_state", "3戦線のデータが必要です。")
    _require(state.max_rounds > 0, "invalid_state", "最大ラウンド数が不正です。")
    _require(1 <= state.round_no <= state.max_rounds, "invalid_state", "現在ラウンドが不正です。")
    _require(set(state.orders).issubset(state.players), "invalid_state", "命令の所有者が不正です。")
    _require(all(points.mission_points >= 0 for points in state.players.values()), "invalid_state", "任務ポイントが不正です。")

    all_deployment_ids: list[str] = []
    for player_id, player in state.players.items():
        _require(player.player_id == player_id, "invalid_state", "プレイヤーIDが一致しません。")
        for card_id in [*player.hand, *player.draw_pile]:
            lookup_card(card_id)
    for lane_id, lane in state.lanes.items():
        _require(lane.lane_id == lane_id, "invalid_state", "戦線IDが一致しません。")
        _require(len(lane.round_winners) <= state.round_no, "invalid_state", "戦線履歴が長すぎます。")
        for deployment in lane.deployments:
            all_deployment_ids.append(deployment.deployment_id)
            _require(deployment.player_id in state.players, "invalid_state", "配備の所有者が不正です。")
            _require(deployment.lane_id == lane_id, "invalid_state", "配備先が一致しません。")
            _require(1 <= deployment.round_deployed <= state.round_no, "invalid_state", "配備ラウンドが不正です。")
            _require(set(deployment.revealed_to).issubset(state.players), "invalid_state", "公開先が不正です。")
            lookup_card(deployment.card_id)
            formation_metadata(deployment.formation_id)
    _require(len(all_deployment_ids) == len(set(all_deployment_ids)), "invalid_state", "配備IDが重複しています。")

    for owner_id, order in state.orders.items():
        _require(order.player_id == owner_id, "invalid_state", "命令の所有者が一致しません。")
        _require(order.round_no == state.round_no, "invalid_state", "命令ラウンドが一致しません。")
        _require(order.lane_id in LANE_IDS, "invalid_state", "命令の戦線が不正です。")
        _require(order.card_id in state.players[owner_id].hand, "invalid_state", "命令カードが手札にありません。")
        lookup_card(order.card_id)
        formation_metadata(order.formation_id)

    if state.phase is Phase.PLANNING:
        _require(len(state.orders) < 2, "invalid_state", "命令が揃った状態は解決フェーズです。")
        _require(state.result is None, "invalid_state", "進行中の対戦に結果があります。")
    elif state.phase is Phase.RESOLVING:
        _require(set(state.orders) == set(state.player_order), "invalid_state", "解決に必要な命令がありません。")
        _require(state.result is None, "invalid_state", "解決中の対戦に結果があります。")
    elif state.phase is Phase.COMPLETE:
        _require(state.result is not None, "invalid_state", "終了した対戦に結果がありません。")
        _require(not state.orders, "invalid_state", "終了後に命令が残っています。")

    sequences = [event.sequence for event in state.events]
    _require(sequences == sorted(sequences), "invalid_state", "イベント順が不正です。")
    _require(len(sequences) == len(set(sequences)), "invalid_state", "イベント番号が重複しています。")
    if sequences:
        _require(state.next_event_sequence > sequences[-1], "invalid_state", "次のイベント番号が不正です。")


__all__ = [
    "ARMOR_SUPPLY_BONUS",
    "FORMATION_SCALE",
    "LANE_IDS",
    "LANE_LABELS",
    "MAX_ROUNDS",
    "Deployment",
    "GameEvent",
    "GameState",
    "LanePower",
    "LaneState",
    "MatchResult",
    "Order",
    "Phase",
    "PlayerState",
    "RoundResolution",
    "RuleViolation",
    "calculate_lane_power",
    "cancel_order",
    "card_metadata",
    "choose_ai_order",
    "formation_metadata",
    "lookup_card",
    "new_game",
    "play_ai_turn",
    "play_round_with_ai",
    "resolve_round",
    "submit_order",
    "validate_state",
]

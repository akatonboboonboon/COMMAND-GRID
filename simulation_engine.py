"""Advanced 180-card simulation rules for COMMAND GRID.

This mode is intentionally separate from the approachable core game.  It uses
playable unit, equipment, and facility records, twelve turns, and six
explainable capability axes across three land theaters and one naval theater.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence
from uuid import uuid4

from advanced_game_data import (
    ADVANCED_STARTER_DECK,
    AdvancedCard,
    get_advanced_card,
    is_playable_advanced_card,
)
from symbol_catalog import Domain


SIMULATION_ROUNDS = 12
SIMULATION_DECK_SIZE = 24
THEATER_IDS: tuple[str, ...] = ("north", "central", "south", "naval")
THEATER_LABELS = {
    "north": "北部作戦域",
    "central": "中央作戦域",
    "south": "南部作戦域",
    "naval": "海上作戦域",
}

DAY = "昼"
NIGHT = "夜"
BATTLE_TIMES: tuple[str, str] = (DAY, NIGHT)
_NIGHT_PENALTY_FAMILIES = frozenset({
    "aviation_units",
    "infantry_support",
    "armor",
    "artillery",
    "air_antiarmor",
    "information_support",
})
_NIGHT_PENALTY_FIELDS = ("control", "support", "recon", "mobility")
_AVIATION_COORDINATION_KEYWORDS = (
    "航空母艦",
    "航空戦艦",
    "航空巡洋艦",
    "空軍",
    "航空管制",
    "早期警戒管制",
)


class SimulationPhase(StrEnum):
    PLANNING = "planning"
    RESOLVING = "resolving"
    COMPLETE = "complete"


class SimulationRuleError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise SimulationRuleError(code, message)


def _get_playable_card(card_id: str) -> AdvancedCard:
    """Resolve one card and turn catalog mistakes into a rule error."""

    try:
        card = get_advanced_card(card_id)
    except KeyError as error:
        raise SimulationRuleError(
            "unknown_card", f"使用できない本格シミュレーションカードです: {card_id}"
        ) from error
    _require(
        is_playable_advanced_card(card),
        "nonplayable_card",
        f"戦場へ出せない記号です: {card_id}",
    )
    return card


def _validate_battle_time(battle_time: str) -> str:
    """Return a valid match-wide battle time or raise a rule error."""

    _require(
        battle_time in BATTLE_TIMES,
        "invalid_battle_time",
        "戦場の時間帯は「昼」または「夜」を選んでください。",
    )
    return battle_time


def time_of_day_for_round(round_no: int, battle_time: str = DAY) -> str:
    """Return the match-wide time for a round.

    ``round_no`` remains in this public helper for backward compatibility, but
    time no longer alternates between turns.  Callers may pass the selected
    match time as the second argument; legacy one-argument calls resolve to the
    daytime default used when old saves are migrated.
    """

    _require(round_no > 0, "invalid_round", "ターン番号は1以上必要です。")
    return _validate_battle_time(battle_time)


def current_time_of_day(state: "SimulationState") -> str:
    """Return the fixed time selected for this match."""

    return time_of_day_for_round(state.round_no, state.battle_time)


def card_allowed_in_theater(card: AdvancedCard | str, theater_id: str) -> bool:
    """Return whether a card may be deployed to a land or naval theater.

    Naval organizations are restricted to the naval theater.  The naval
    theater accepts naval and aviation organizations only; aviation may also
    support any of the three land theaters.
    """

    if theater_id not in THEATER_IDS:
        return False
    if isinstance(card, str):
        try:
            card = _get_playable_card(card)
        except SimulationRuleError:
            return False
    if theater_id == "naval":
        return card.family in {"naval_units", "aviation_units"}
    return card.family != "naval_units"


def _deployment_stats(
    card: AdvancedCard,
    battle_time: str = DAY,
) -> Mapping[str, int]:
    """Return printed stats after the match-wide night modifier."""

    stats = {name: int(getattr(card, name)) for name in (
        "control", "support", "recon", "supply", "command", "mobility"
    )}
    if (
        _validate_battle_time(battle_time) == NIGHT
        and card.family in _NIGHT_PENALTY_FAMILIES
    ):
        for name in _NIGHT_PENALTY_FIELDS:
            stats[name] = max(0, stats[name] - 1)
    return stats


def _night_penalties(card: AdvancedCard, battle_time: str) -> dict[str, int]:
    printed = _deployment_stats(card)
    adjusted = _deployment_stats(card, battle_time)
    return {
        name: printed[name] - adjusted[name]
        for name in _NIGHT_PENALTY_FIELDS
    }


def _is_aviation_coordination_card(card: AdvancedCard) -> bool:
    return any(keyword in card.name for keyword in _AVIATION_COORDINATION_KEYWORDS)


@dataclass(slots=True)
class SimulationOrder:
    player_id: str
    card_id: str
    theater_id: str
    round_no: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "card_id": self.card_id,
            "theater_id": self.theater_id,
            "round_no": self.round_no,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SimulationOrder":
        return cls(
            str(value["player_id"]),
            str(value["card_id"]),
            str(value["theater_id"]),
            int(value["round_no"]),
        )


@dataclass(slots=True)
class SimulationDeployment:
    deployment_id: str
    player_id: str
    card_id: str
    theater_id: str
    round_deployed: int
    revealed_to: list[str] = field(default_factory=list)

    def visible_to(self, player_id: str) -> bool:
        return player_id == self.player_id or player_id in self.revealed_to

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "player_id": self.player_id,
            "card_id": self.card_id,
            "theater_id": self.theater_id,
            "round_deployed": self.round_deployed,
            "revealed_to": list(self.revealed_to),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SimulationDeployment":
        return cls(
            str(value["deployment_id"]),
            str(value["player_id"]),
            str(value["card_id"]),
            str(value["theater_id"]),
            int(value["round_deployed"]),
            [str(item) for item in value.get("revealed_to", [])],
        )


@dataclass(slots=True)
class SimulationPower:
    control: int = 0
    support: int = 0
    active_support: int = 0
    recon: int = 0
    command: int = 0
    mobility: int = 0
    supply_generated: int = 0
    supply_demand: int = 0
    supply_deficit: int = 0
    command_bonus: int = 0
    mobility_bonus: int = 0
    domain_bonus: int = 0
    family_bonus: int = 0
    aviation_bonus: int = 0
    night_penalty: int = 0
    night_control_penalty: int = 0
    night_support_penalty: int = 0
    night_recon_penalty: int = 0
    night_mobility_penalty: int = 0
    total: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            name: int(getattr(self, name)) for name in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SimulationPower":
        return cls(**{
            name: int(value.get(name, 0)) for name in cls.__dataclass_fields__
        })


@dataclass(slots=True)
class SimulationTheater:
    theater_id: str
    label: str
    deployments: list[SimulationDeployment] = field(default_factory=list)
    last_power: dict[str, SimulationPower] = field(default_factory=dict)
    round_winners: list[str | None] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "theater_id": self.theater_id,
            "label": self.label,
            "deployments": [item.to_dict() for item in self.deployments],
            "last_power": {
                player_id: power.to_dict()
                for player_id, power in self.last_power.items()
            },
            "round_winners": list(self.round_winners),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SimulationTheater":
        return cls(
            theater_id=str(value["theater_id"]),
            label=str(value["label"]),
            deployments=[
                SimulationDeployment.from_dict(item)
                for item in value.get("deployments", [])
            ],
            last_power={
                str(player_id): SimulationPower.from_dict(power)
                for player_id, power in value.get("last_power", {}).items()
            },
            round_winners=[
                None if item is None else str(item)
                for item in value.get("round_winners", [])
            ],
        )


@dataclass(slots=True)
class SimulationPlayer:
    player_id: str
    name: str
    hand: list[str]
    mission_points: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "hand": list(self.hand),
            "mission_points": self.mission_points,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SimulationPlayer":
        return cls(
            str(value["player_id"]),
            str(value["name"]),
            [str(item) for item in value.get("hand", [])],
            int(value.get("mission_points", 0)),
        )


@dataclass(slots=True)
class SimulationResult:
    winner_id: str | None
    theaters_controlled: dict[str, int]
    mission_points: dict[str, int]
    rounds_played: int
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "winner_id": self.winner_id,
            "theaters_controlled": dict(self.theaters_controlled),
            "mission_points": dict(self.mission_points),
            "rounds_played": self.rounds_played,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SimulationResult":
        winner = value.get("winner_id")
        return cls(
            None if winner is None else str(winner),
            {str(key): int(item) for key, item in value["theaters_controlled"].items()},
            {str(key): int(item) for key, item in value["mission_points"].items()},
            int(value["rounds_played"]),
            str(value["summary"]),
        )


@dataclass(slots=True)
class SimulationState:
    game_id: str
    round_no: int
    max_rounds: int
    phase: SimulationPhase
    player_order: tuple[str, str]
    players: dict[str, SimulationPlayer]
    theaters: dict[str, SimulationTheater]
    battle_time: str = DAY
    orders: dict[str, SimulationOrder] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)
    result: SimulationResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "round_no": self.round_no,
            "max_rounds": self.max_rounds,
            "phase": self.phase.value,
            "player_order": list(self.player_order),
            "players": {key: value.to_dict() for key, value in self.players.items()},
            "theaters": {key: value.to_dict() for key, value in self.theaters.items()},
            "battle_time": self.battle_time,
            "orders": {key: value.to_dict() for key, value in self.orders.items()},
            "events": list(self.events),
            "result": None if self.result is None else self.result.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SimulationState":
        order = tuple(str(item) for item in value["player_order"])
        _require(len(order) == 2, "invalid_state", "プレイヤーは2人必要です。")
        raw_result = value.get("result")
        # Saves created before the naval theater existed contain only three
        # theater records.  Add an empty fourth record before validation.
        raw_theaters = {
            str(key): item for key, item in value["theaters"].items()
        }
        raw_theaters.setdefault(
            "naval",
            SimulationTheater("naval", THEATER_LABELS["naval"]).to_dict(),
        )
        state = cls(
            game_id=str(value["game_id"]),
            round_no=int(value["round_no"]),
            max_rounds=int(value["max_rounds"]),
            phase=SimulationPhase(str(value["phase"])),
            player_order=(order[0], order[1]),
            players={
                str(key): SimulationPlayer.from_dict(item)
                for key, item in value["players"].items()
            },
            theaters={
                str(key): SimulationTheater.from_dict(item)
                for key, item in raw_theaters.items()
            },
            # Saves created before match-wide time selection are daytime games.
            battle_time=str(value.get("battle_time", DAY)),
            orders={
                str(key): SimulationOrder.from_dict(item)
                for key, item in value.get("orders", {}).items()
            },
            events=[str(item) for item in value.get("events", [])],
            result=None if raw_result is None else SimulationResult.from_dict(raw_result),
        )
        validate_simulation_state(state)
        return state


def _validate_deck(deck: Sequence[str], rounds: int) -> list[str]:
    _require(not isinstance(deck, (str, bytes)), "invalid_deck", "デッキ形式が不正です。")
    cards = [str(item) for item in deck]
    _require(len(cards) >= rounds, "deck_too_small", f"最低{rounds}枚必要です。")
    _require(len(cards) <= SIMULATION_DECK_SIZE, "deck_too_large", "上級デッキは24枚までです。")
    _require(len(set(cards)) == len(cards), "duplicate_card", "同じカードは1枚までです。")
    for card_id in cards:
        _get_playable_card(card_id)
    return cards


def new_simulation(
    player_deck: Sequence[str] = ADVANCED_STARTER_DECK,
    opponent_deck: Sequence[str] | None = None,
    *,
    player_id: str = "player",
    opponent_id: str = "opponent",
    player_name: str = "あなた",
    opponent_name: str = "統合作戦AI",
    game_id: str | None = None,
    max_rounds: int = SIMULATION_ROUNDS,
    battle_time: str = DAY,
) -> SimulationState:
    _require(max_rounds > 0, "invalid_rounds", "ターン数は1以上必要です。")
    _require(player_id != opponent_id, "duplicate_player", "プレイヤーIDは別々にします。")
    battle_time = _validate_battle_time(battle_time)
    first = _validate_deck(player_deck, max_rounds)
    second = _validate_deck(opponent_deck or player_deck, max_rounds)
    return SimulationState(
        game_id=game_id or uuid4().hex,
        round_no=1,
        max_rounds=max_rounds,
        phase=SimulationPhase.PLANNING,
        player_order=(player_id, opponent_id),
        players={
            player_id: SimulationPlayer(player_id, player_name, first),
            opponent_id: SimulationPlayer(opponent_id, opponent_name, second),
        },
        theaters={
            theater_id: SimulationTheater(theater_id, THEATER_LABELS[theater_id])
            for theater_id in THEATER_IDS
        },
        battle_time=battle_time,
        events=[
            f"{max_rounds}ターンの統合作戦を開始しました。"
            f"戦場条件は{battle_time}戦（全ターン{battle_time}）です。"
        ],
    )


def submit_simulation_order(
    state: SimulationState,
    player_id: str,
    card_id: str,
    theater_id: str,
) -> SimulationOrder:
    _require(state.phase is SimulationPhase.PLANNING, "wrong_phase", "現在は命令を選べません。")
    _require(player_id in state.players, "unknown_player", "存在しないプレイヤーです。")
    _require(theater_id in state.theaters, "unknown_theater", "存在しない作戦域です。")
    _require(player_id not in state.orders, "order_exists", "命令は確定済みです。")
    _require(card_id in state.players[player_id].hand, "card_not_in_hand", "そのカードは手札にありません。")
    card = _get_playable_card(card_id)
    _require(
        card_allowed_in_theater(card, theater_id),
        "card_not_allowed",
        f"{card.name}は{THEATER_LABELS[theater_id]}へ配置できません。",
    )
    order = SimulationOrder(player_id, card_id, theater_id, state.round_no)
    state.orders[player_id] = order
    if set(state.orders) == set(state.player_order):
        state.phase = SimulationPhase.RESOLVING
    return order


def calculate_simulation_power(
    state: SimulationState,
    theater_id: str,
    player_id: str,
    *,
    visible_to: str | None = None,
) -> SimulationPower:
    _require(theater_id in state.theaters, "unknown_theater", "存在しない作戦域です。")
    deployments = [
        item for item in state.theaters[theater_id].deployments
        if item.player_id == player_id
        and (visible_to is None or item.visible_to(visible_to))
    ]
    cards_and_stats: list[tuple[AdvancedCard, Mapping[str, int]]] = []
    penalty_totals = {name: 0 for name in _NIGHT_PENALTY_FIELDS}
    for item in deployments:
        card = _get_playable_card(item.card_id)
        cards_and_stats.append((card, _deployment_stats(card, state.battle_time)))
        for name, amount in _night_penalties(card, state.battle_time).items():
            penalty_totals[name] += amount
    control = sum(stats["control"] for _, stats in cards_and_stats)
    support = sum(stats["support"] for _, stats in cards_and_stats)
    active_support = support if control > 0 else 0
    recon = sum(stats["recon"] for _, stats in cards_and_stats)
    command = sum(stats["command"] for _, stats in cards_and_stats)
    mobility = sum(stats["mobility"] for _, stats in cards_and_stats)
    generated = sum(max(0, stats["supply"]) for _, stats in cards_and_stats)
    demand = sum(abs(min(0, stats["supply"])) for _, stats in cards_and_stats)
    deficit = max(0, demand - generated)
    command_bonus = min(6, command // 3)
    mobility_bonus = min(4, mobility // 5)
    domains = {
        card.domain for card, _ in cards_and_stats
        if card.domain not in {Domain.GENERIC}
    }
    domain_bonus = max(0, len(domains) - 1) * 2
    family_counts = Counter(card.family for card, _ in cards_and_stats)
    family_bonus = min(
        6,
        sum(max(0, count - 1) * 2 for count in family_counts.values()),
    )
    aviation_count = sum(
        _is_aviation_coordination_card(card) for card, _ in cards_and_stats
    )
    aviation_bonus = min(6, max(0, aviation_count - 1) * 2)
    total = max(
        0,
        control + active_support + command_bonus + mobility_bonus
        + domain_bonus + family_bonus + aviation_bonus - deficit,
    )
    return SimulationPower(
        control=control,
        support=support,
        active_support=active_support,
        recon=recon,
        command=command,
        mobility=mobility,
        supply_generated=generated,
        supply_demand=demand,
        supply_deficit=deficit,
        command_bonus=command_bonus,
        mobility_bonus=mobility_bonus,
        domain_bonus=domain_bonus,
        family_bonus=family_bonus,
        aviation_bonus=aviation_bonus,
        night_penalty=sum(penalty_totals.values()),
        night_control_penalty=penalty_totals["control"],
        night_support_penalty=penalty_totals["support"],
        night_recon_penalty=penalty_totals["recon"],
        night_mobility_penalty=penalty_totals["mobility"],
        total=total,
    )


def choose_simulation_ai_order(
    state: SimulationState, player_id: str
) -> SimulationOrder:
    _require(state.phase is SimulationPhase.PLANNING, "wrong_phase", "AIは現在命令を選べません。")
    _require(player_id in state.players, "unknown_player", "存在しないAIです。")
    opponent_id = next(item for item in state.player_order if item != player_id)
    theater_context: dict[str, tuple[SimulationPower, SimulationPower, int, int]] = {}
    for theater_id in THEATER_IDS:
        theater = state.theaters[theater_id]
        own = calculate_simulation_power(state, theater_id, player_id)
        enemy = calculate_simulation_power(
            state, theater_id, opponent_id, visible_to=player_id
        )
        own_count = sum(item.player_id == player_id for item in theater.deployments)
        hidden = sum(
            item.player_id == opponent_id and not item.visible_to(player_id)
            for item in theater.deployments
        )
        theater_context[theater_id] = own, enemy, own_count, hidden
    best: tuple[float, int, int, str, str] | None = None
    for card_index, card_id in enumerate(state.players[player_id].hand):
        card = _get_playable_card(card_id)
        stats = _deployment_stats(card, state.battle_time)
        for theater_index, theater_id in enumerate(THEATER_IDS):
            if not card_allowed_in_theater(card, theater_id):
                continue
            own, enemy, own_count, hidden = theater_context[theater_id]
            gap = enemy.total - own.total
            base = stats["control"] + (
                stats["support"] if own.control or stats["control"] else 0
            )
            information = min(stats["recon"], hidden) * 1.8
            supply = 0.0
            if stats["supply"] > 0 and own.supply_demand > own.supply_generated:
                supply = 5.0
            command = stats["command"] * 0.45
            mobility = stats["mobility"] * 0.35
            contest = max(-2, min(8, gap)) * 1.25
            # Encourage two-theater plans and stop wasteful over-stacking.
            spread = 5.0 if own_count == 0 else 2.0 if own_count == 1 else 0.0
            overstack = max(0, own.total - enemy.total - 5) * 1.1 + own_count * 0.7
            own_cards = [
                _get_playable_card(item.card_id)
                for item in state.theaters[theater_id].deployments
                if item.player_id == player_id
            ]
            family_synergy = (
                2.0
                if own.family_bonus < 6
                and any(item.family == card.family for item in own_cards)
                else 0.0
            )
            aviation_synergy = (
                2.0
                if own.aviation_bonus < 6
                and _is_aviation_coordination_card(card)
                and any(_is_aviation_coordination_card(item) for item in own_cards)
                else 0.0
            )
            score = (
                base + information + supply + command + mobility + contest
                + spread + family_synergy + aviation_synergy - overstack
            )
            candidate = (score, -card_index, -theater_index, card_id, theater_id)
            if best is None or candidate > best:
                best = candidate
    _require(best is not None, "no_order", "AIが出せるカードがありません。")
    return SimulationOrder(player_id, best[3], best[4], state.round_no)


def _reveal_by_recon(state: SimulationState) -> None:
    for theater_id in THEATER_IDS:
        theater = state.theaters[theater_id]
        for player_id in state.player_order:
            recon = calculate_simulation_power(state, theater_id, player_id).recon
            opponent_id = next(item for item in state.player_order if item != player_id)
            hidden = [
                item for item in reversed(theater.deployments)
                if item.player_id == opponent_id and not item.visible_to(player_id)
            ]
            for item in hidden[:recon]:
                item.revealed_to.append(player_id)


def resolve_simulation_round(state: SimulationState) -> None:
    _require(state.phase is SimulationPhase.RESOLVING, "wrong_phase", "両者の命令が必要です。")
    time_of_day = current_time_of_day(state)
    for player_id in state.player_order:
        order = state.orders[player_id]
        player = state.players[player_id]
        _require(order.card_id in player.hand, "card_not_in_hand", "命令カードがありません。")
        card = _get_playable_card(order.card_id)
        _require(
            card_allowed_in_theater(card, order.theater_id),
            "card_not_allowed",
            f"{card.name}は{THEATER_LABELS[order.theater_id]}へ配置できません。",
        )
        player.hand.remove(order.card_id)
        state.theaters[order.theater_id].deployments.append(
            SimulationDeployment(
                deployment_id=f"{state.game_id}:{state.round_no}:{player_id}",
                player_id=player_id,
                card_id=order.card_id,
                theater_id=order.theater_id,
                round_deployed=state.round_no,
                revealed_to=[player_id],
            )
        )
        state.events.append(
            f"{state.round_no}T（{time_of_day}）: {player.name}が{card.name}を"
            f"{THEATER_LABELS[order.theater_id]}へ配備。"
        )
    _reveal_by_recon(state)
    for theater_id in THEATER_IDS:
        theater = state.theaters[theater_id]
        powers = {
            player_id: calculate_simulation_power(state, theater_id, player_id)
            for player_id in state.player_order
        }
        theater.last_power = powers
        first, second = state.player_order
        winner: str | None
        if powers[first].total == powers[second].total:
            winner = None
        else:
            winner = first if powers[first].total > powers[second].total else second
            state.players[winner].mission_points += 1
        theater.round_winners.append(winner)
    state.orders.clear()
    if state.round_no >= state.max_rounds:
        state.phase = SimulationPhase.COMPLETE
        state.result = _simulation_result(state)
    else:
        state.round_no += 1
        state.phase = SimulationPhase.PLANNING
    validate_simulation_state(state)


def play_simulation_round(
    state: SimulationState,
    player_id: str,
    card_id: str,
    theater_id: str,
) -> None:
    submit_simulation_order(state, player_id, card_id, theater_id)
    opponent_id = next(item for item in state.player_order if item != player_id)
    ai = choose_simulation_ai_order(state, opponent_id)
    submit_simulation_order(state, ai.player_id, ai.card_id, ai.theater_id)
    resolve_simulation_round(state)


def _simulation_result(state: SimulationState) -> SimulationResult:
    controlled = {player_id: 0 for player_id in state.player_order}
    for theater_id in THEATER_IDS:
        powers = {
            player_id: calculate_simulation_power(state, theater_id, player_id)
            for player_id in state.player_order
        }
        first, second = state.player_order
        if powers[first].total > powers[second].total:
            controlled[first] += 1
        elif powers[second].total > powers[first].total:
            controlled[second] += 1
    first, second = state.player_order
    if controlled[first] != controlled[second]:
        winner = first if controlled[first] > controlled[second] else second
        reason = f"最終確保作戦域 {controlled[winner]}域"
    elif state.players[first].mission_points != state.players[second].mission_points:
        winner = (
            first if state.players[first].mission_points > state.players[second].mission_points
            else second
        )
        reason = f"任務点 {state.players[winner].mission_points}点"
    else:
        winner = None
        reason = "確保作戦域・任務点とも同数"
    outcome = (
        "引き分けです。"
        if winner is None
        else f"{state.players[winner].name}が{reason}で勝利しました。"
    )
    summary = f"{state.battle_time}戦: {outcome}"
    return SimulationResult(
        winner_id=winner,
        theaters_controlled=controlled,
        mission_points={
            player_id: state.players[player_id].mission_points
            for player_id in state.player_order
        },
        rounds_played=state.round_no,
        summary=summary,
    )


def validate_simulation_state(state: SimulationState) -> None:
    _validate_battle_time(state.battle_time)
    _require(set(state.players) == set(state.player_order), "invalid_state", "プレイヤー構成が不正です。")
    _require(set(state.theaters) == set(THEATER_IDS), "invalid_state", "作戦域構成が不正です。")
    _require(1 <= state.round_no <= state.max_rounds, "invalid_state", "ターン番号が不正です。")
    for player in state.players.values():
        _require(player.mission_points >= 0, "invalid_state", "任務点が不正です。")
        for card_id in player.hand:
            _get_playable_card(card_id)
    for player_id, order in state.orders.items():
        _require(player_id in state.players, "invalid_state", "命令のプレイヤーが不正です。")
        _require(order.player_id == player_id, "invalid_state", "命令の所有者が不正です。")
        _require(order.theater_id in state.theaters, "invalid_state", "命令の作戦域が不正です。")
        _require(order.round_no == state.round_no, "invalid_state", "命令のターンが不正です。")
        _require(
            order.card_id in state.players[player_id].hand,
            "invalid_state",
            "命令カードが手札にありません。",
        )
        card = _get_playable_card(order.card_id)
        _require(
            card_allowed_in_theater(card, order.theater_id),
            "invalid_state",
            "命令カードを配置できない作戦域です。",
        )
    for theater_id, theater in state.theaters.items():
        _require(theater.theater_id == theater_id, "invalid_state", "作戦域IDが不正です。")
        for deployment in theater.deployments:
            _require(
                deployment.player_id in state.players,
                "invalid_state",
                "配備部隊の所有者が不正です。",
            )
            _require(
                deployment.theater_id == theater_id,
                "invalid_state",
                "配備先の作戦域が不正です。",
            )
            _require(
                1 <= deployment.round_deployed <= state.round_no,
                "invalid_state",
                "配備ターンが不正です。",
            )
            _require(
                set(deployment.revealed_to) <= set(state.players),
                "invalid_state",
                "偵察公開先が不正です。",
            )
            card = _get_playable_card(deployment.card_id)
            _require(
                card_allowed_in_theater(card, theater_id),
                "invalid_state",
                "配備カードを配置できない作戦域です。",
            )
    if state.phase is SimulationPhase.COMPLETE:
        _require(state.result is not None, "invalid_state", "完了結果がありません。")


__all__ = [
    "BATTLE_TIMES",
    "SIMULATION_DECK_SIZE",
    "SIMULATION_ROUNDS",
    "THEATER_IDS",
    "THEATER_LABELS",
    "DAY",
    "NIGHT",
    "SimulationPhase",
    "SimulationDeployment",
    "SimulationPower",
    "SimulationResult",
    "SimulationRuleError",
    "SimulationState",
    "calculate_simulation_power",
    "card_allowed_in_theater",
    "choose_simulation_ai_order",
    "current_time_of_day",
    "new_simulation",
    "play_simulation_round",
    "resolve_simulation_round",
    "submit_simulation_order",
    "time_of_day_for_round",
    "validate_simulation_state",
]

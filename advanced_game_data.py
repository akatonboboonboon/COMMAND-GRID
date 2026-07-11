"""Deterministic card catalog for COMMAND GRID's advanced simulation mode.

Every source symbol becomes exactly one playable data record.  This module is
deliberately limited to shared numeric capabilities; it does not assign unique
rules or promise effects that the simulation engine has not implemented.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from symbol_catalog import Domain, PlayKind, SYMBOL_CATALOG, SymbolDefinition


RARITIES: tuple[str, ...] = ("標準", "専門", "精鋭", "希少")
NUMERIC_CAPABILITY_FIELDS: tuple[str, ...] = (
    "control",
    "support",
    "recon",
    "supply",
    "command",
    "mobility",
)


@dataclass(frozen=True, slots=True)
class AdvancedCard:
    """One advanced-mode card derived from a reference-sheet symbol."""

    id: str
    name: str
    family: str
    domain: Domain
    play_kind: PlayKind
    symbol_id: str
    control: int
    support: int
    recon: int
    supply: int
    command: int
    mobility: int
    rarity: str
    plain_role: str

    def to_dict(self) -> dict[str, str | int]:
        """Return a JSON-safe representation for APIs and saved match data."""

        data = asdict(self)
        data["domain"] = self.domain.value
        data["play_kind"] = self.play_kind.value
        return data


# These profiles describe only broad jobs.  Family and domain adjustments below
# provide the detail, while the stable per-symbol variation prevents a family
# from becoming 11 identical cards.
_KIND_PROFILES: dict[PlayKind, dict[str, int]] = {
    PlayKind.UNIT: {
        "control": 3,
        "support": 1,
        "recon": 1,
        "supply": -1,
        "command": 1,
        "mobility": 3,
    },
    PlayKind.SUPPORT: {
        "control": 1,
        "support": 3,
        "recon": 2,
        "supply": 1,
        "command": 1,
        "mobility": 2,
    },
    PlayKind.FACILITY: {
        "control": 2,
        "support": 2,
        "recon": 1,
        "supply": 3,
        "command": 3,
        "mobility": 0,
    },
    PlayKind.ENTITY: {
        "control": 2,
        "support": 2,
        "recon": 2,
        "supply": -1,
        "command": 1,
        "mobility": 4,
    },
    PlayKind.TASK_FORCE: {
        "control": 2,
        "support": 2,
        "recon": 2,
        "supply": 1,
        "command": 5,
        "mobility": 2,
    },
    PlayKind.VISUAL: {
        "control": 1,
        "support": 1,
        "recon": 1,
        "supply": 1,
        "command": 3,
        "mobility": 1,
    },
}


_DOMAIN_ADJUSTMENTS: dict[Domain, dict[str, int]] = {
    Domain.JOINT: {"support": 1, "command": 1},
    Domain.LAND: {"control": 1},
    Domain.AIR: {"recon": 1, "supply": -1, "mobility": 1},
    Domain.SEA: {"support": 1, "supply": -1, "command": 1},
    Domain.SPECIAL: {"recon": 1, "supply": -1, "command": 1},
    Domain.GENERIC: {"supply": 1},
}


_FAMILY_ADJUSTMENTS: dict[str, dict[str, int]] = {
    "frames": {"command": 1},
    "joint": {"command": 1},
    "naval_units": {"support": 1, "mobility": 1},
    "aviation_units": {"recon": 1, "mobility": 1},
    "special_operations": {"recon": 1, "mobility": 1},
    "infantry": {"control": 2},
    "infantry_support": {"support": 1, "recon": 1},
    "armor": {"control": 2, "supply": -1, "mobility": 1},
    "engineer": {"support": 1, "supply": 1},
    "artillery": {"support": 2, "supply": -1},
    "air_antiarmor": {"support": 1, "recon": 1},
    "information_support": {"recon": 2, "command": 1},
    "logistics": {"support": 1, "supply": 3},
    "ground_entities": {"control": 1, "mobility": 1},
    "air_space_entities": {"recon": 1, "mobility": 1},
    "sea_entities": {"support": 1, "mobility": 1},
    "echelon": {"command": 2},
    "task_organizations": {"command": 2},
    "other_organizations": {"supply": 1, "command": 1},
}


_LOWER_BOUNDS = {
    "control": 0,
    "support": 0,
    "recon": 0,
    "supply": -4,
    "command": 0,
    "mobility": 0,
}
_UPPER_BOUNDS = {field: 6 for field in NUMERIC_CAPABILITY_FIELDS}


def _stable_seed(value: str) -> int:
    """Return a repeatable integer without relying on randomized ``hash``."""

    return sum((index + 1) * ord(character) for index, character in enumerate(value))


def _add_adjustments(stats: dict[str, int], changes: dict[str, int]) -> None:
    for field, amount in changes.items():
        stats[field] += amount


def _rarity_for(symbol: SymbolDefinition) -> str:
    # Rarity is collectible variety, not a hidden numerical power modifier.
    roll = _stable_seed(symbol.id) % 20
    if roll == 0:
        return "希少"
    if roll <= 3:
        return "精鋭"
    if roll <= 8:
        return "専門"
    return "標準"


def _stats_for(symbol: SymbolDefinition) -> dict[str, int]:
    stats = dict(_KIND_PROFILES[symbol.play_kind])
    _add_adjustments(stats, _DOMAIN_ADJUSTMENTS[symbol.domain])
    _add_adjustments(stats, _FAMILY_ADJUSTMENTS[symbol.family_id])

    # One modest point of variation gives each symbol a numerical identity while
    # keeping every value inside the same public balance envelope.
    variation_fields = ("control", "support", "recon", "command", "mobility")
    variation_field = variation_fields[_stable_seed(symbol.id) % len(variation_fields)]
    stats[variation_field] += 1

    return {
        field: max(_LOWER_BOUNDS[field], min(_UPPER_BOUNDS[field], stats[field]))
        for field in NUMERIC_CAPABILITY_FIELDS
    }


def build_advanced_catalog() -> tuple[AdvancedCard, ...]:
    """Build the complete catalog in the source sheet's stable order."""

    cards: list[AdvancedCard] = []
    for symbol in SYMBOL_CATALOG:
        stats = _stats_for(symbol)
        cards.append(
            AdvancedCard(
                id=f"advanced_{symbol.id}",
                name=symbol.name,
                family=symbol.family_id,
                domain=symbol.domain,
                play_kind=symbol.play_kind,
                symbol_id=symbol.id,
                control=stats["control"],
                support=stats["support"],
                recon=stats["recon"],
                supply=stats["supply"],
                command=stats["command"],
                mobility=stats["mobility"],
                rarity=_rarity_for(symbol),
                plain_role=symbol.plain_role,
            )
        )
    return tuple(cards)


ADVANCED_CARDS: tuple[AdvancedCard, ...] = build_advanced_catalog()
ADVANCED_CARD_INDEX = {card.id: card for card in ADVANCED_CARDS}
ADVANCED_SYMBOL_INDEX = {card.symbol_id: card for card in ADVANCED_CARDS}


def get_advanced_card(card_id: str) -> AdvancedCard:
    """Return one card and fail loudly for an unknown advanced card ID."""

    return ADVANCED_CARD_INDEX[card_id]


def get_advanced_card_for_symbol(symbol_id: str) -> AdvancedCard:
    """Return the one card generated from ``symbol_id``."""

    return ADVANCED_SYMBOL_INDEX[symbol_id]


def _enum_value(value: Domain | PlayKind | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, (Domain, PlayKind)):
        return value.value
    return str(value)


def search_advanced_cards(
    query: str = "",
    *,
    family: str | None = None,
    domain: Domain | str | None = None,
    play_kind: PlayKind | str | None = None,
    rarity: str | None = None,
) -> tuple[AdvancedCard, ...]:
    """Search and filter cards while preserving canonical catalog order."""

    needle = str(query).strip().casefold()
    domain_value = _enum_value(domain)
    kind_value = _enum_value(play_kind)
    family_value = None if family is None else str(family)
    rarity_value = None if rarity is None else str(rarity)

    matches: list[AdvancedCard] = []
    for card in ADVANCED_CARDS:
        searchable = " ".join(
            (card.id, card.symbol_id, card.name, card.family, card.plain_role)
        ).casefold()
        if needle and needle not in searchable:
            continue
        if family_value is not None and card.family != family_value:
            continue
        if domain_value is not None and card.domain.value != domain_value:
            continue
        if kind_value is not None and card.play_kind.value != kind_value:
            continue
        if rarity_value is not None and card.rarity != rarity_value:
            continue
        matches.append(card)
    return tuple(matches)


_DOMAIN_ORDER: tuple[Domain, ...] = (
    Domain.JOINT,
    Domain.LAND,
    Domain.AIR,
    Domain.SEA,
    Domain.SPECIAL,
    Domain.GENERIC,
)
_DOMAIN_KIND_PRIORITY: dict[Domain, tuple[PlayKind, ...]] = {
    Domain.JOINT: (
        PlayKind.TASK_FORCE,
        PlayKind.UNIT,
        PlayKind.SUPPORT,
        PlayKind.ENTITY,
        PlayKind.FACILITY,
        PlayKind.VISUAL,
    ),
    Domain.LAND: (
        PlayKind.UNIT,
        PlayKind.SUPPORT,
        PlayKind.ENTITY,
        PlayKind.TASK_FORCE,
        PlayKind.FACILITY,
        PlayKind.VISUAL,
    ),
    Domain.AIR: (
        PlayKind.UNIT,
        PlayKind.ENTITY,
        PlayKind.SUPPORT,
        PlayKind.TASK_FORCE,
        PlayKind.FACILITY,
        PlayKind.VISUAL,
    ),
    Domain.SEA: (
        PlayKind.UNIT,
        PlayKind.ENTITY,
        PlayKind.SUPPORT,
        PlayKind.TASK_FORCE,
        PlayKind.FACILITY,
        PlayKind.VISUAL,
    ),
    Domain.SPECIAL: (
        PlayKind.UNIT,
        PlayKind.SUPPORT,
        PlayKind.ENTITY,
        PlayKind.TASK_FORCE,
        PlayKind.FACILITY,
        PlayKind.VISUAL,
    ),
    Domain.GENERIC: (
        PlayKind.SUPPORT,
        PlayKind.FACILITY,
        PlayKind.VISUAL,
        PlayKind.TASK_FORCE,
        PlayKind.ENTITY,
        PlayKind.UNIT,
    ),
}


def _primary_capability(card: AdvancedCard) -> str:
    non_negative_stats = {
        "control": card.control,
        "support": card.support,
        "recon": card.recon,
        "supply": max(0, card.supply),
        "command": card.command,
        "mobility": card.mobility,
    }
    # dict insertion order is the stable tie breaker.
    return max(non_negative_stats, key=non_negative_stats.get)


def build_balanced_deck(
    size: int = 24,
    cards: Iterable[AdvancedCard] | None = None,
) -> tuple[str, ...]:
    """Build a deterministic deck balanced across available operational domains.

    The default 24-card deck allocates four cards to each of the six domains.
    Within each domain it prefers new card kinds, families and primary
    capabilities, so the result demonstrates the breadth of the advanced pool.
    """

    pool = tuple(ADVANCED_CARDS if cards is None else cards)
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        raise ValueError("deck size must be a positive integer")
    if size > len(pool):
        raise ValueError("deck size exceeds the available card pool")
    if len({card.id for card in pool}) != len(pool):
        raise ValueError("card pool contains duplicate IDs")

    available_domains = tuple(
        domain for domain in _DOMAIN_ORDER if any(card.domain == domain for card in pool)
    )
    if not available_domains:
        raise ValueError("card pool is empty")

    base_quota, extra = divmod(size, len(available_domains))
    quotas = {
        domain: base_quota + (1 if index < extra else 0)
        for index, domain in enumerate(available_domains)
    }

    # If a filtered pool cannot satisfy an even quota, transfer its deficit to
    # domains with spare cards while retaining deterministic domain order.
    deficit = 0
    for domain in available_domains:
        capacity = sum(card.domain == domain for card in pool)
        if quotas[domain] > capacity:
            deficit += quotas[domain] - capacity
            quotas[domain] = capacity
    while deficit:
        progressed = False
        for domain in available_domains:
            capacity = sum(card.domain == domain for card in pool)
            if quotas[domain] < capacity:
                quotas[domain] += 1
                deficit -= 1
                progressed = True
                if not deficit:
                    break
        if not progressed:
            raise ValueError("card pool cannot satisfy requested deck size")

    catalog_position = {card.id: index for index, card in enumerate(pool)}
    selected: list[AdvancedCard] = []
    used_kinds: set[PlayKind] = set()
    used_families: set[str] = set()
    used_capabilities: set[str] = set()

    for domain in available_domains:
        candidates = [card for card in pool if card.domain == domain]
        priority = _DOMAIN_KIND_PRIORITY[domain]
        for _ in range(quotas[domain]):
            remaining = [card for card in candidates if card not in selected]

            def score(card: AdvancedCard) -> tuple[int, int, int, int, int]:
                return (
                    int(card.play_kind not in used_kinds),
                    int(card.family not in used_families),
                    int(_primary_capability(card) not in used_capabilities),
                    -priority.index(card.play_kind),
                    -catalog_position[card.id],
                )

            card = max(remaining, key=score)
            selected.append(card)
            used_kinds.add(card.play_kind)
            used_families.add(card.family)
            used_capabilities.add(_primary_capability(card))

    return tuple(card.id for card in selected)


ADVANCED_STARTER_DECK: tuple[str, ...] = build_balanced_deck()


__all__ = (
    "ADVANCED_CARDS",
    "ADVANCED_CARD_INDEX",
    "ADVANCED_STARTER_DECK",
    "ADVANCED_SYMBOL_INDEX",
    "AdvancedCard",
    "NUMERIC_CAPABILITY_FIELDS",
    "RARITIES",
    "build_advanced_catalog",
    "build_balanced_deck",
    "get_advanced_card",
    "get_advanced_card_for_symbol",
    "search_advanced_cards",
)

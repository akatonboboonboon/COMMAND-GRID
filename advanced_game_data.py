"""Deterministic data for COMMAND GRID's advanced simulation mode.

The reference sheet contains 201 symbols, but frames and echelon marks are not
things a player can deploy.  ``ADVANCED_CATALOG`` retains all 201 stable source
records for display and migration, while ``ADVANCED_CARDS`` contains only the
180 cards that can actually be put in a deck.  Echelon marks are exposed as
separate formation-size modifiers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from symbol_catalog import Domain, PlayKind, SYMBOL_CATALOG, SymbolDefinition


RARITIES: tuple[str, ...] = ("標準", "専門", "精鋭", "希少")
ADVANCED_ENTRY_KIND_CARD = "部隊・装備など"
ADVANCED_ENTRY_KIND_SCALE = "部隊規模"
ADVANCED_ENTRY_KINDS: tuple[str, ...] = (
    ADVANCED_ENTRY_KIND_CARD,
    ADVANCED_ENTRY_KIND_SCALE,
)
TASK_ORGANIZATION_SCALES: tuple[str, ...] = (
    "軍団",
    "師団",
    "旅団",
    "大隊",
    "中隊",
    "小隊",
)
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
    """One advanced-mode record derived from a reference-sheet symbol."""

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


@dataclass(frozen=True, slots=True)
class AdvancedScale:
    """A formation-size modifier attached to a playable unit card."""

    id: str
    name: str
    symbol_id: str
    control_delta: int
    support_delta: int
    recon_delta: int
    supply_delta: int
    command_delta: int
    mobility_delta: int
    description: str

    def to_dict(self) -> dict[str, str | int]:
        """Return a JSON-safe representation for APIs and saved decks."""

        return asdict(self)

    def stat_deltas(self) -> dict[str, int]:
        """Return deltas using the same field names as :class:`AdvancedCard`."""

        return {
            field: getattr(self, f"{field}_delta")
            for field in NUMERIC_CAPABILITY_FIELDS
        }


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


# Both records describe physical bases.  The reference sheet groups them with
# organizations, but in the game they remain deployable facility cards.
_PLAY_KIND_OVERRIDES: dict[str, PlayKind] = {
    "naval_units_01": PlayKind.FACILITY,
    "task_organizations_02": PlayKind.FACILITY,
}

_NON_PLAYABLE_FAMILIES = frozenset(("frames", "echelon"))
_SCALE_ATTACHABLE_KINDS = frozenset(
    (PlayKind.UNIT, PlayKind.SUPPORT, PlayKind.TASK_FORCE)
)
_INTRINSIC_SCALE_IDS: dict[str, str] = {
    "advanced_task_organizations_04": "advanced_echelon_04",
    "advanced_task_organizations_05": "advanced_echelon_05",
    "advanced_task_organizations_06": "advanced_echelon_06",
    "advanced_task_organizations_07": "advanced_echelon_08",
    "advanced_task_organizations_08": "advanced_echelon_09",
    "advanced_task_organizations_09": "advanced_echelon_10",
}


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


def _stats_for(
    symbol: SymbolDefinition,
    play_kind: PlayKind | None = None,
) -> dict[str, int]:
    stats = dict(_KIND_PROFILES[play_kind or symbol.play_kind])
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


def is_playable_advanced_card(card: AdvancedCard) -> bool:
    """Return whether a catalog record may be placed in a deck."""

    return card.family not in _NON_PLAYABLE_FAMILIES


def build_advanced_catalog() -> tuple[AdvancedCard, ...]:
    """Build the complete catalog in the source sheet's stable order."""

    cards: list[AdvancedCard] = []
    for symbol in SYMBOL_CATALOG:
        play_kind = _PLAY_KIND_OVERRIDES.get(symbol.id, symbol.play_kind)
        stats = _stats_for(symbol, play_kind)
        cards.append(
            AdvancedCard(
                id=f"advanced_{symbol.id}",
                name=symbol.name,
                family=symbol.family_id,
                domain=symbol.domain,
                play_kind=play_kind,
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


ADVANCED_CATALOG: tuple[AdvancedCard, ...] = build_advanced_catalog()
ADVANCED_CATALOG_INDEX = {card.id: card for card in ADVANCED_CATALOG}
ADVANCED_CARDS: tuple[AdvancedCard, ...] = tuple(
    card for card in ADVANCED_CATALOG if is_playable_advanced_card(card)
)
ADVANCED_CARD_INDEX = {card.id: card for card in ADVANCED_CARDS}
ADVANCED_SYMBOL_INDEX = {card.symbol_id: card for card in ADVANCED_CATALOG}


def get_advanced_card(card_id: str) -> AdvancedCard:
    """Return one playable card and reject catalog-only records."""

    return ADVANCED_CARD_INDEX[card_id]


def get_advanced_catalog_entry(entry_id: str) -> AdvancedCard:
    """Return any of the 201 source-derived records, including visual data."""

    return ADVANCED_CATALOG_INDEX[entry_id]


def get_advanced_card_for_symbol(symbol_id: str) -> AdvancedCard:
    """Return the catalog record generated from ``symbol_id``."""

    return ADVANCED_SYMBOL_INDEX[symbol_id]


# control, support, recon, supply, command, mobility, description
_SCALE_PROFILES: dict[str, tuple[int, int, int, int, int, int, str]] = {
    "echelon_01": (3, 2, -2, -3, 3, -3, "最大級の編制。制圧・支援・指揮は非常に高いが、補給負担が重く機動しにくい。"),
    "echelon_02": (3, 2, -2, -3, 3, -3, "複数の軍を束ねる編制。広域を動かせる一方、補給と機動に大きな負担がある。"),
    "echelon_03": (2, 2, -1, -2, 2, -2, "広い正面を担当する大規模編制。制圧と支援に優れるが、即応性は低い。"),
    "echelon_04": (2, 1, -1, -2, 2, -2, "複数師団を指揮する編制。指揮と制圧を高める代わりに補給を多く使う。"),
    "echelon_05": (2, 1, -1, -1, 1, -1, "独立して広い戦線を担える大編制。制圧力は高いが、やや重くなる。"),
    "echelon_06": (1, 1, 0, -1, 1, -1, "複数任務をこなせる中大型編制。戦力を底上げするが補給負担も増える。"),
    "echelon_07": (1, 0, 0, -1, 1, 0, "まとまった戦力を持つ中規模編制。制圧と指揮を少し高める。"),
    "echelon_08": (1, 0, 0, 0, 0, 0, "戦線の一角を担当する中規模編制。扱いやすく、制圧力を少し高める。"),
    "echelon_09": (0, 0, 0, 0, 0, 0, "標準となる部隊規模。能力への補正はなく、カード本来の性能で運用する。"),
    "echelon_10": (-1, 0, 1, 0, -1, 1, "小回りの利く小規模編制。制圧と指揮を下げ、偵察と機動を高める。"),
    "echelon_11": (-1, -1, 1, 1, -1, 1, "独立行動しやすい小部隊。正面戦闘より偵察と機動に向く。"),
    "echelon_12": (-1, -1, 1, 1, -1, 1, "小人数で動く分隊。軽い補給で素早く行動できるが、大きな制圧には不向き。"),
    "echelon_13": (-2, -1, 1, 1, -1, 2, "最小級の行動単位。機動性は高いが、制圧・支援能力は限定される。"),
    "echelon_14": (0, 0, 0, 0, 0, 0, "規模を特定しない汎用の階梯。能力補正を付けずに運用する。"),
}


def build_advanced_scales() -> tuple[AdvancedScale, ...]:
    """Build the 14 attachable formation-size modifiers in source order."""

    scales: list[AdvancedScale] = []
    for entry in ADVANCED_CATALOG:
        if entry.family != "echelon":
            continue
        profile = _SCALE_PROFILES[entry.symbol_id]
        scales.append(
            AdvancedScale(
                id=entry.id,
                name=entry.name,
                symbol_id=entry.symbol_id,
                control_delta=profile[0],
                support_delta=profile[1],
                recon_delta=profile[2],
                supply_delta=profile[3],
                command_delta=profile[4],
                mobility_delta=profile[5],
                description=profile[6],
            )
        )
    return tuple(scales)


ADVANCED_SCALE_CARDS: tuple[AdvancedScale, ...] = build_advanced_scales()
# Shorter alias used by the simulation engine and AI when iterating modifiers.
ADVANCED_SCALES = ADVANCED_SCALE_CARDS
ADVANCED_SCALE_INDEX = {scale.id: scale for scale in ADVANCED_SCALE_CARDS}
DEFAULT_ADVANCED_SCALE_ID = "advanced_echelon_09"


def get_advanced_scale(scale_id: str) -> AdvancedScale:
    """Return one formation-size modifier."""

    return ADVANCED_SCALE_INDEX[scale_id]


def intrinsic_advanced_scale_id(card: AdvancedCard) -> str | None:
    """Return the fixed scale already encoded in a task-organization name."""

    return _INTRINSIC_SCALE_IDS.get(card.id)


def can_attach_advanced_scale(card: AdvancedCard) -> bool:
    """Return whether a unit-like playable card accepts a size modifier."""

    return (
        is_playable_advanced_card(card)
        and card.play_kind in _SCALE_ATTACHABLE_KINDS
        and intrinsic_advanced_scale_id(card) is None
    )


def scaled_advanced_stats(
    card: AdvancedCard,
    scale: AdvancedScale | str | None = None,
) -> dict[str, int]:
    """Return public-range stats after applying one formation-size modifier."""

    intrinsic_id = intrinsic_advanced_scale_id(card)
    if intrinsic_id is None and not can_attach_advanced_scale(card):
        raise ValueError(f"formation size cannot be attached to {card.id}")
    requested_id = scale.id if isinstance(scale, AdvancedScale) else scale
    if intrinsic_id is not None and requested_id not in (None, intrinsic_id):
        raise ValueError(f"{card.id} has fixed formation size {intrinsic_id}")
    resolved = intrinsic_id or requested_id or DEFAULT_ADVANCED_SCALE_ID
    modifier = get_advanced_scale(resolved) if isinstance(resolved, str) else resolved
    if not isinstance(modifier, AdvancedScale):
        raise TypeError("scale must be an AdvancedScale or scale ID")
    return {
        field: max(
            _LOWER_BOUNDS[field],
            min(
                _UPPER_BOUNDS[field],
                getattr(card, field) + getattr(modifier, f"{field}_delta"),
            ),
        )
        for field in NUMERIC_CAPABILITY_FIELDS
    }


def advanced_entry_kind(card: AdvancedCard) -> str:
    """Classify a source record as a card-like symbol or a pure echelon."""

    return (
        ADVANCED_ENTRY_KIND_SCALE
        if card.family == "echelon"
        else ADVANCED_ENTRY_KIND_CARD
    )


def advanced_name_and_scale(card: AdvancedCard) -> tuple[str | None, str | None]:
    """Return display name and scale separately while retaining the source card ID."""

    if card.family == "echelon":
        return None, card.name
    if card.family == "task_organizations":
        for scale in TASK_ORGANIZATION_SCALES:
            if card.name == f"任務{scale}":
                return "任務部隊", scale
    return card.name, None


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
    entry_kind: str | None = None,
) -> tuple[AdvancedCard, ...]:
    """Search and filter cards while preserving canonical catalog order."""

    needle = str(query).strip().casefold()
    domain_value = _enum_value(domain)
    kind_value = _enum_value(play_kind)
    family_value = None if family is None else str(family)
    rarity_value = None if rarity is None else str(rarity)
    entry_kind_value = None if entry_kind is None else str(entry_kind)
    if entry_kind_value is not None and entry_kind_value not in ADVANCED_ENTRY_KINDS:
        return ()

    matches: list[AdvancedCard] = []
    for card in ADVANCED_CARDS:
        searchable = " ".join(
            (
                card.id,
                card.symbol_id,
                card.name,
                card.family,
                card.plain_role,
                advanced_entry_kind(card),
                *(part for part in advanced_name_and_scale(card) if part),
            )
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
        if entry_kind_value is not None and advanced_entry_kind(card) != entry_kind_value:
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
    if any(not is_playable_advanced_card(card) for card in pool):
        raise ValueError("card pool contains non-playable reference records")

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
    "ADVANCED_CATALOG",
    "ADVANCED_CATALOG_INDEX",
    "ADVANCED_CARDS",
    "ADVANCED_CARD_INDEX",
    "ADVANCED_ENTRY_KIND_CARD",
    "ADVANCED_ENTRY_KIND_SCALE",
    "ADVANCED_ENTRY_KINDS",
    "ADVANCED_SCALE_CARDS",
    "ADVANCED_SCALE_INDEX",
    "ADVANCED_SCALES",
    "ADVANCED_STARTER_DECK",
    "ADVANCED_SYMBOL_INDEX",
    "DEFAULT_ADVANCED_SCALE_ID",
    "AdvancedCard",
    "AdvancedScale",
    "NUMERIC_CAPABILITY_FIELDS",
    "RARITIES",
    "TASK_ORGANIZATION_SCALES",
    "advanced_entry_kind",
    "advanced_name_and_scale",
    "build_advanced_catalog",
    "build_advanced_scales",
    "build_balanced_deck",
    "can_attach_advanced_scale",
    "get_advanced_card",
    "get_advanced_card_for_symbol",
    "get_advanced_catalog_entry",
    "get_advanced_scale",
    "intrinsic_advanced_scale_id",
    "is_playable_advanced_card",
    "scaled_advanced_stats",
    "search_advanced_cards",
)

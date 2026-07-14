"""Deterministic data for COMMAND GRID's advanced simulation mode.

The reference sheet's 201 symbols are the immutable collection catalog.  The
advanced battle roster is intentionally separate: one source symbol may produce
several named cards, and symbols omitted by the reviewed roster remain visible
in the collection without becoming playable.  The canonical 121-card roster is
loaded from :mod:`CARD_NAMES_FOR_REVIEW.csv`.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from symbol_catalog import (
    FAMILY_INDEX,
    Domain,
    PlayKind,
    SYMBOL_CATALOG,
    SYMBOL_INDEX,
    SymbolDefinition,
)


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
    catalog_number: int | None

    def to_dict(self) -> dict[str, str | int | None]:
        """Return a JSON-safe representation for APIs and saved match data."""

        data = asdict(self)
        data["domain"] = self.domain.value
        data["play_kind"] = self.play_kind.value
        return data


# Broad family jobs are the base of the automatic allocation.  The two small
# seeded variations and visible name-keyword adjustments below stop cards with
# the same classification from becoming numerically identical.
_FAMILY_STAT_PROFILES: dict[str, tuple[int, int, int, int, int, int]] = {
    "naval_units": (3, 2, 1, -2, 1, 2),
    "aviation_units": (2, 2, 3, -2, 1, 3),
    "special_operations": (2, 1, 3, 0, 2, 3),
    "infantry": (4, 1, 1, 0, 1, 1),
    "infantry_support": (1, 2, 4, 0, 1, 2),
    "armor": (5, 1, 1, -3, 1, 2),
    "engineer": (2, 3, 1, 1, 1, 1),
    "artillery": (1, 5, 1, -2, 1, 0),
    "air_antiarmor": (2, 4, 2, -2, 1, 1),
    "information_support": (1, 2, 4, 0, 3, 1),
    "logistics": (1, 2, 1, 5, 2, 1),
    "other_organizations": (2, 2, 2, 1, 4, 1),
}

ADVANCED_FAMILY_NAMES: dict[str, str] = {
    "海軍組織": "naval_units",
    "航空組織": "aviation_units",
    "特殊作戦組織": "special_operations",
    "歩兵組織": "infantry",
    "偵察支援": "infantry_support",
    "機甲組織": "armor",
    "工兵組織": "engineer",
    "砲兵組織": "artillery",
    "防空・対戦車・ミサイル": "air_antiarmor",
    "情報・通信・治安支援": "information_support",
    "後方支援組織": "logistics",
    "その他の組織": "other_organizations",
}

_KEYWORD_ADJUSTMENTS: tuple[tuple[tuple[str, ...], dict[str, int]], ...] = (
    (("偵察", "観測", "警戒", "諜報", "測量", "気象"), {"recon": 1}),
    (("重", "戦艦", "装甲"), {"control": 1, "mobility": -1, "supply": -1}),
    (("砲", "ミサイル", "射撃", "ロケット"), {"support": 1, "supply": -1}),
    (("補給", "整備", "輸送", "燃料", "食糧", "衛生", "弾薬"), {"supply": 1}),
    (("司令", "管制", "通信", "電子戦", "心理戦"), {"command": 1}),
    (("航空", "空軍", "ヘリ", "戦闘機", "空挺", "高機動"), {"mobility": 1}),
    (("基地", "拠点"), {"control": 1, "command": 1, "mobility": -1}),
)


_LOWER_BOUNDS = {
    "control": 0,
    "support": 0,
    "recon": 0,
    "supply": -4,
    "command": 0,
    "mobility": 0,
}
_UPPER_BOUNDS = {field: 6 for field in NUMERIC_CAPABILITY_FIELDS}


ADVANCED_ROSTER_PATH = Path(__file__).with_name("CARD_NAMES_FOR_REVIEW.csv")


def _stable_seed(value: str) -> int:
    """Return a repeatable integer without relying on randomized ``hash``."""

    return sum((index + 1) * ord(character) for index, character in enumerate(value))


def _add_adjustments(stats: dict[str, int], changes: dict[str, int]) -> None:
    for field, amount in changes.items():
        stats[field] += amount


def _rarity_for_value(value: str) -> str:
    # Rarity is collectible variety, not a hidden numerical power modifier.
    roll = _stable_seed(value) % 20
    if roll == 0:
        return "希少"
    if roll <= 3:
        return "精鋭"
    if roll <= 8:
        return "専門"
    return "標準"


def allocate_advanced_stats(
    family: str,
    card_id: str,
    name: str,
) -> dict[str, int]:
    """Allocate deterministic capabilities from family, stable ID and name.

    ``family`` accepts either the internal family ID or the Japanese CSV label.
    The returned mapping is independent of CSV row order, Python's randomized
    hash seed and any mutable game state.
    """

    family_id = ADVANCED_FAMILY_NAMES.get(str(family).strip(), str(family).strip())
    if family_id not in _FAMILY_STAT_PROFILES:
        raise KeyError(f"unknown advanced card family: {family}")

    stats = dict(zip(NUMERIC_CAPABILITY_FIELDS, _FAMILY_STAT_PROFILES[family_id]))
    seed = _stable_seed(f"{str(card_id).strip()}|{str(name).strip()}")
    boost_index = seed % len(NUMERIC_CAPABILITY_FIELDS)
    penalty_index = (seed // 7) % len(NUMERIC_CAPABILITY_FIELDS)
    if penalty_index == boost_index:
        penalty_index = (penalty_index + 1) % len(NUMERIC_CAPABILITY_FIELDS)
    stats[NUMERIC_CAPABILITY_FIELDS[boost_index]] += 1
    stats[NUMERIC_CAPABILITY_FIELDS[penalty_index]] -= 1

    final_name = str(name).strip()
    for keywords, adjustment in _KEYWORD_ADJUSTMENTS:
        if any(keyword in final_name for keyword in keywords):
            _add_adjustments(stats, adjustment)

    return {
        field: max(_LOWER_BOUNDS[field], min(_UPPER_BOUNDS[field], stats[field]))
        for field in NUMERIC_CAPABILITY_FIELDS
    }


def is_playable_advanced_card(card: AdvancedCard) -> bool:
    """Return whether a catalog record may be placed in a deck."""

    return card.catalog_number is not None


def build_advanced_catalog() -> tuple[AdvancedCard, ...]:
    """Build the complete 201-symbol collection catalog in stable sheet order."""

    cards: list[AdvancedCard] = []
    for symbol in SYMBOL_CATALOG:
        family_for_stats = (
            symbol.family_id
            if symbol.family_id in _FAMILY_STAT_PROFILES
            else "other_organizations"
        )
        stats = allocate_advanced_stats(
            family_for_stats, f"advanced_{symbol.id}", symbol.name
        )
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
                rarity=_rarity_for_value(f"advanced_{symbol.id}"),
                plain_role=symbol.plain_role,
                catalog_number=None,
            )
        )
    return tuple(cards)


_CSV_STAT_COLUMNS: dict[str, str] = {
    "制圧": "control",
    "支援": "support",
    "偵察": "recon",
    "補給": "supply",
    "指揮": "command",
    "機動": "mobility",
}
_ADVANCED_ROSTER_COLUMNS = (
    "カタログ",
    "番号",
    "カードID",
    "元記号ID",
    "分類",
    "現在の部隊・カード名",
    "変更後の部隊・カード名",
    *_CSV_STAT_COLUMNS,
)


def _play_kind_for_roster_card(
    source: SymbolDefinition,
    family: str,
    current_name: str,
    final_name: str,
) -> PlayKind:
    if source.play_kind == PlayKind.FACILITY:
        return PlayKind.FACILITY
    facility_text = f"{source.name} {current_name} {final_name}"
    if any(keyword in facility_text for keyword in ("基地", "拠点")):
        return PlayKind.FACILITY
    return FAMILY_INDEX[family].play_kind


def load_advanced_roster(
    path: str | Path = ADVANCED_ROSTER_PATH,
) -> tuple[AdvancedCard, ...]:
    """Load and validate the reviewed canonical 121-card battle roster."""

    roster_path = Path(path)
    with roster_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != _ADVANCED_ROSTER_COLUMNS:
            raise ValueError(
                f"{roster_path.name} must have the canonical 13-column schema"
            )
        rows = [
            row
            for row in reader
            if str(row.get("カタログ", "")).strip().startswith("本格")
        ]

    if len(rows) != 121:
        raise ValueError("advanced roster must contain exactly 121 rows")

    cards: list[AdvancedCard] = []
    seen_ids: set[str] = set()
    for expected_number, row in enumerate(rows, 1):
        try:
            number = int(str(row["番号"]).strip())
        except (TypeError, ValueError) as error:
            raise ValueError("advanced roster numbers must be integers") from error
        if number != expected_number:
            raise ValueError("advanced roster numbers must be consecutive from 1 to 121")

        card_id = str(row["カードID"]).strip()
        if not card_id.startswith("advanced_") or card_id in seen_ids:
            raise ValueError(f"invalid or duplicate advanced card ID: {card_id}")
        seen_ids.add(card_id)

        symbol_id = str(row["元記号ID"]).strip()
        if symbol_id.startswith("advanced_"):
            symbol_id = symbol_id.removeprefix("advanced_")
        try:
            source = SYMBOL_INDEX[symbol_id]
        except KeyError as error:
            raise ValueError(f"unknown source symbol ID: {symbol_id}") from error

        family_label = str(row["分類"]).strip()
        try:
            family = ADVANCED_FAMILY_NAMES[family_label]
        except KeyError as error:
            raise ValueError(f"unknown advanced classification: {family_label}") from error
        current_name = str(row["現在の部隊・カード名"]).strip()
        changed_name = str(row["変更後の部隊・カード名"]).strip()
        final_name = changed_name or current_name
        if not final_name:
            raise ValueError(f"advanced card {card_id} has no name")

        allocated = allocate_advanced_stats(family, card_id, final_name)
        try:
            csv_stats = {
                field: int(str(row[column]).strip())
                for column, field in _CSV_STAT_COLUMNS.items()
            }
        except (TypeError, ValueError) as error:
            raise ValueError(f"advanced card {card_id} has invalid numeric stats") from error
        if csv_stats != allocated:
            raise ValueError(f"advanced card {card_id} stats do not match allocation")

        cards.append(
            AdvancedCard(
                id=card_id,
                name=final_name,
                family=family,
                domain=FAMILY_INDEX[family].domain,
                play_kind=_play_kind_for_roster_card(
                    source, family, current_name, final_name
                ),
                symbol_id=symbol_id,
                control=allocated["control"],
                support=allocated["support"],
                recon=allocated["recon"],
                supply=allocated["supply"],
                command=allocated["command"],
                mobility=allocated["mobility"],
                rarity=_rarity_for_value(card_id),
                plain_role=source.plain_role,
                catalog_number=number,
            )
        )
    return tuple(cards)


ADVANCED_CATALOG: tuple[AdvancedCard, ...] = build_advanced_catalog()
ADVANCED_CATALOG_INDEX = {card.id: card for card in ADVANCED_CATALOG}
ADVANCED_CARDS: tuple[AdvancedCard, ...] = load_advanced_roster()
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
            (
                card.id,
                card.symbol_id,
                card.name,
                card.family,
                card.plain_role,
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

    It spreads cards across every domain represented in the reviewed roster.
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
    "ADVANCED_FAMILY_NAMES",
    "ADVANCED_ROSTER_PATH",
    "ADVANCED_STARTER_DECK",
    "ADVANCED_SYMBOL_INDEX",
    "AdvancedCard",
    "NUMERIC_CAPABILITY_FIELDS",
    "RARITIES",
    "allocate_advanced_stats",
    "build_advanced_catalog",
    "build_balanced_deck",
    "get_advanced_card",
    "get_advanced_card_for_symbol",
    "get_advanced_catalog_entry",
    "is_playable_advanced_card",
    "load_advanced_roster",
    "search_advanced_cards",
)

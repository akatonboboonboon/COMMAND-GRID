import csv
import json
import unittest
from collections import Counter
from dataclasses import fields

from advanced_game_data import (
    ADVANCED_CATALOG,
    ADVANCED_CATALOG_INDEX,
    ADVANCED_CARDS,
    ADVANCED_CARD_INDEX,
    ADVANCED_ROSTER_PATH,
    ADVANCED_STARTER_DECK,
    ADVANCED_SYMBOL_INDEX,
    NUMERIC_CAPABILITY_FIELDS,
    RARITIES,
    AdvancedCard,
    allocate_advanced_stats,
    build_advanced_catalog,
    build_balanced_deck,
    get_advanced_card,
    get_advanced_card_for_symbol,
    get_advanced_catalog_entry,
    is_playable_advanced_card,
    load_advanced_roster,
    search_advanced_cards,
)
from game_data import CARD_INDEX
from symbol_catalog import Domain, PlayKind, SYMBOL_CATALOG


class AdvancedGameDataTests(unittest.TestCase):
    def test_collection_keeps_201_symbols_and_roster_has_121_cards(self) -> None:
        self.assertEqual(len(ADVANCED_CATALOG), 201)
        self.assertEqual(len(ADVANCED_CATALOG_INDEX), 201)
        self.assertEqual(len(ADVANCED_SYMBOL_INDEX), 201)
        self.assertEqual(len(ADVANCED_CARDS), 121)
        self.assertEqual(len(ADVANCED_CARD_INDEX), 121)
        self.assertEqual(
            {card.symbol_id for card in ADVANCED_CATALOG},
            {symbol.id for symbol in SYMBOL_CATALOG},
        )
        self.assertTrue(all(not is_playable_advanced_card(card) for card in ADVANCED_CATALOG))
        self.assertTrue(all(is_playable_advanced_card(card) for card in ADVANCED_CARDS))

    def test_roster_ids_and_numbers_are_unique_and_consecutive(self) -> None:
        ids = [card.id for card in ADVANCED_CARDS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([card.catalog_number for card in ADVANCED_CARDS], list(range(1, 122)))
        self.assertTrue(all(card_id.startswith("advanced_") for card_id in ids))
        self.assertTrue(set(ids).isdisjoint(CARD_INDEX))

    def test_duplicate_symbols_create_distinct_cards_but_reuse_the_symbol(self) -> None:
        cards = ADVANCED_CARDS[:3]
        self.assertEqual({card.symbol_id for card in cards}, {"naval_units_01"})
        self.assertEqual(
            [card.id for card in cards],
            [
                "advanced_naval_units_01_01",
                "advanced_naval_units_01_02",
                "advanced_naval_units_01_03",
            ],
        )
        self.assertEqual(len({card.name for card in cards}), 3)

    def test_card_schema_includes_review_number(self) -> None:
        self.assertEqual(
            tuple(field.name for field in fields(AdvancedCard)),
            (
                "id",
                "name",
                "family",
                "domain",
                "play_kind",
                "symbol_id",
                "control",
                "support",
                "recon",
                "supply",
                "command",
                "mobility",
                "rarity",
                "plain_role",
                "catalog_number",
            ),
        )

    def test_builders_are_repeatable(self) -> None:
        self.assertEqual(build_advanced_catalog(), ADVANCED_CATALOG)
        self.assertEqual(load_advanced_roster(), ADVANCED_CARDS)
        self.assertEqual(build_balanced_deck(), ADVANCED_STARTER_DECK)

    def test_roster_uses_changed_name_and_reviewed_classification(self) -> None:
        first = get_advanced_card("advanced_naval_units_01_01")
        self.assertEqual(first.name, "船舶係留拠点")
        self.assertEqual(first.family, "naval_units")
        self.assertEqual(first.domain, Domain.SEA)
        self.assertEqual(first.play_kind, PlayKind.FACILITY)

        infantry = get_advanced_card("advanced_infantry_01")
        self.assertEqual(infantry.name, "歩兵中隊")
        self.assertEqual(infantry.family, "infantry")
        self.assertEqual(infantry.domain, Domain.LAND)

    def test_every_source_reference_points_to_the_collection_catalog(self) -> None:
        for card in ADVANCED_CARDS:
            with self.subTest(card=card.id):
                source = get_advanced_card_for_symbol(card.symbol_id)
                self.assertEqual(source.symbol_id, card.symbol_id)
                self.assertTrue(card.name.strip())
                self.assertTrue(card.plain_role.strip())

    def test_numeric_capabilities_stay_in_public_balance_range(self) -> None:
        for card in (*ADVANCED_CATALOG, *ADVANCED_CARDS):
            with self.subTest(card=card.id, number=card.catalog_number):
                for field in NUMERIC_CAPABILITY_FIELDS:
                    value = getattr(card, field)
                    self.assertIs(type(value), int)
                    lower = -4 if field == "supply" else 0
                    self.assertGreaterEqual(value, lower)
                    self.assertLessEqual(value, 6)

    def test_allocator_is_stable_and_accepts_both_family_labels(self) -> None:
        expected = allocate_advanced_stats(
            "naval_units", "advanced_naval_units_02_01", "航空母艦"
        )
        self.assertEqual(
            expected,
            allocate_advanced_stats(
                "海軍組織", "advanced_naval_units_02_01", "航空母艦"
            ),
        )
        self.assertEqual(
            expected,
            allocate_advanced_stats(
                "naval_units", "advanced_naval_units_02_01", "航空母艦"
            ),
        )
        self.assertEqual(set(expected), set(NUMERIC_CAPABILITY_FIELDS))
        with self.assertRaises(KeyError):
            allocate_advanced_stats("unknown", "advanced_x", "不詳")

    def test_csv_stats_match_the_public_allocator_and_loaded_cards(self) -> None:
        with ADVANCED_ROSTER_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = [
                row
                for row in csv.DictReader(handle)
                if row["カタログ"].startswith("本格")
            ]
        self.assertEqual(len(rows), 121)
        stat_columns = {
            "制圧": "control",
            "支援": "support",
            "偵察": "recon",
            "補給": "supply",
            "指揮": "command",
            "機動": "mobility",
        }
        for row in rows:
            card = get_advanced_card(row["カードID"])
            allocated = allocate_advanced_stats(card.family, card.id, card.name)
            with self.subTest(card=card.id):
                for column, field in stat_columns.items():
                    self.assertEqual(int(row[column]), allocated[field])
                    self.assertEqual(getattr(card, field), allocated[field])

    def test_reviewed_family_counts_are_preserved(self) -> None:
        self.assertEqual(
            Counter(card.family for card in ADVANCED_CARDS),
            {
                "naval_units": 26,
                "aviation_units": 16,
                "special_operations": 10,
                "infantry": 9,
                "infantry_support": 9,
                "armor": 5,
                "engineer": 9,
                "artillery": 7,
                "air_antiarmor": 8,
                "information_support": 9,
                "logistics": 10,
                "other_organizations": 3,
            },
        )

    def test_rarity_and_api_payload_are_complete(self) -> None:
        self.assertEqual({card.rarity for card in ADVANCED_CARDS}, set(RARITIES))
        payload = [card.to_dict() for card in ADVANCED_CARDS]
        restored = json.loads(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(len(restored), 121)
        self.assertEqual(restored[0]["catalog_number"], 1)
        self.assertEqual(restored[0]["domain"], ADVANCED_CARDS[0].domain.value)
        self.assertEqual(restored[0]["play_kind"], ADVANCED_CARDS[0].play_kind.value)
        self.assertEqual(set(restored[0]), {field.name for field in fields(AdvancedCard)})

    def test_starter_deck_has_twenty_four_unique_known_cards(self) -> None:
        self.assertEqual(len(ADVANCED_STARTER_DECK), 24)
        self.assertEqual(len(set(ADVANCED_STARTER_DECK)), 24)
        self.assertTrue(set(ADVANCED_STARTER_DECK).issubset(ADVANCED_CARD_INDEX))

        cards = [get_advanced_card(card_id) for card_id in ADVANCED_STARTER_DECK]
        domain_counts = Counter(card.domain for card in cards)
        self.assertNotIn(Domain.JOINT, domain_counts)
        self.assertLessEqual(max(domain_counts.values()) - min(domain_counts.values()), 1)

    def test_balanced_deck_builder_accepts_one_shot_filtered_pools(self) -> None:
        filtered = (
            card
            for card in ADVANCED_CARDS
            if card.domain in (Domain.LAND, Domain.AIR, Domain.SEA)
        )
        deck = build_balanced_deck(12, filtered)
        cards = [get_advanced_card(card_id) for card_id in deck]
        self.assertEqual(len(deck), 12)
        self.assertEqual(
            Counter(card.domain for card in cards),
            {Domain.LAND: 4, Domain.AIR: 4, Domain.SEA: 4},
        )

    def test_balanced_deck_builder_rejects_invalid_requests(self) -> None:
        for bad_size in (0, -1, True, 122):
            with self.subTest(size=bad_size):
                with self.assertRaises(ValueError):
                    build_balanced_deck(bad_size)
        with self.assertRaises(ValueError):
            build_balanced_deck(2, (ADVANCED_CARDS[0], ADVANCED_CARDS[0]))
        with self.assertRaises(ValueError):
            build_balanced_deck(1, (ADVANCED_CATALOG[0],))

    def test_collection_lookup_remains_a_201_symbol_api(self) -> None:
        for card in ADVANCED_CATALOG:
            self.assertIs(get_advanced_catalog_entry(card.id), card)
            self.assertIs(get_advanced_card_for_symbol(card.symbol_id), card)
        with self.assertRaises(KeyError):
            get_advanced_card("advanced_frames_01")
        with self.assertRaises(KeyError):
            get_advanced_card_for_symbol("not_a_symbol")

    def test_search_uses_only_the_reviewed_playable_roster(self) -> None:
        self.assertEqual(len(search_advanced_cards()), 121)
        naval = search_advanced_cards(family="naval_units")
        self.assertEqual(len(naval), 26)
        self.assertTrue(all(card.family == "naval_units" for card in naval))

        sea_by_enum = search_advanced_cards(domain=Domain.SEA)
        sea_by_value = search_advanced_cards(domain=Domain.SEA.value)
        self.assertEqual(sea_by_enum, sea_by_value)
        self.assertTrue(all(card.domain == Domain.SEA for card in sea_by_enum))

        featured = ADVANCED_CARDS[37]
        self.assertIn(featured, search_advanced_cards(featured.name))
        self.assertEqual(search_advanced_cards(featured.id), (featured,))


if __name__ == "__main__":
    unittest.main()

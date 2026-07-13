import json
import unittest
from collections import Counter
from dataclasses import fields

from advanced_game_data import (
    ADVANCED_CATALOG,
    ADVANCED_CATALOG_INDEX,
    ADVANCED_ENTRY_KIND_CARD,
    ADVANCED_ENTRY_KIND_SCALE,
    ADVANCED_ENTRY_KINDS,
    ADVANCED_CARDS,
    ADVANCED_CARD_INDEX,
    ADVANCED_SCALE_CARDS,
    ADVANCED_SCALE_INDEX,
    ADVANCED_SCALES,
    ADVANCED_STARTER_DECK,
    ADVANCED_SYMBOL_INDEX,
    DEFAULT_ADVANCED_SCALE_ID,
    NUMERIC_CAPABILITY_FIELDS,
    RARITIES,
    TASK_ORGANIZATION_SCALES,
    AdvancedCard,
    AdvancedScale,
    advanced_entry_kind,
    advanced_name_and_scale,
    build_advanced_catalog,
    build_advanced_scales,
    build_balanced_deck,
    can_attach_advanced_scale,
    get_advanced_card,
    get_advanced_card_for_symbol,
    get_advanced_catalog_entry,
    get_advanced_scale,
    intrinsic_advanced_scale_id,
    is_playable_advanced_card,
    scaled_advanced_stats,
    search_advanced_cards,
)
from game_data import CARD_INDEX
from symbol_catalog import Domain, PlayKind, SYMBOL_CATALOG


class AdvancedGameDataTests(unittest.TestCase):
    def test_catalog_keeps_all_symbols_but_only_real_cards_are_playable(self) -> None:
        self.assertEqual(len(ADVANCED_CATALOG), 201)
        self.assertEqual(len(ADVANCED_CATALOG_INDEX), 201)
        self.assertEqual(len(ADVANCED_CARDS), 180)
        self.assertEqual(len(ADVANCED_CARD_INDEX), 180)
        self.assertEqual(len(ADVANCED_SYMBOL_INDEX), 201)
        self.assertEqual(
            {card.symbol_id for card in ADVANCED_CATALOG},
            {symbol.id for symbol in SYMBOL_CATALOG},
        )
        self.assertEqual(
            {card.family for card in ADVANCED_CATALOG if not is_playable_advanced_card(card)},
            {"frames", "echelon"},
        )
        self.assertTrue(all(is_playable_advanced_card(card) for card in ADVANCED_CARDS))

    def test_card_ids_are_unique_and_do_not_collide_with_beginner_cards(self) -> None:
        ids = {card.id for card in ADVANCED_CARDS}
        self.assertEqual(len(ids), 180)
        self.assertTrue(all(card_id.startswith("advanced_") for card_id in ids))
        self.assertTrue(ids.isdisjoint(CARD_INDEX))

    def test_card_schema_contains_the_requested_fields(self) -> None:
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
            ),
        )

    def test_generated_catalog_is_repeatable(self) -> None:
        self.assertEqual(build_advanced_catalog(), ADVANCED_CATALOG)

    def test_card_metadata_stays_linked_to_the_source_symbol(self) -> None:
        symbols = {symbol.id: symbol for symbol in SYMBOL_CATALOG}
        overrides = {"naval_units_01", "task_organizations_02"}
        for card in ADVANCED_CATALOG:
            with self.subTest(card=card.id):
                source = symbols[card.symbol_id]
                self.assertEqual(card.name, source.name)
                self.assertEqual(card.family, source.family_id)
                self.assertEqual(card.domain, source.domain)
                if card.symbol_id in overrides:
                    self.assertEqual(card.play_kind, PlayKind.FACILITY)
                else:
                    self.assertEqual(card.play_kind, source.play_kind)
                self.assertEqual(card.plain_role, source.plain_role)
                self.assertTrue(card.name.strip())
                self.assertTrue(card.plain_role.strip())

    def test_numeric_capabilities_stay_in_the_public_balance_range(self) -> None:
        for card in ADVANCED_CATALOG:
            with self.subTest(card=card.id):
                for field in NUMERIC_CAPABILITY_FIELDS:
                    value = getattr(card, field)
                    self.assertIs(type(value), int)
                    lower = -4 if field == "supply" else 0
                    self.assertGreaterEqual(value, lower)
                    self.assertLessEqual(value, 6)

    def test_family_profiles_have_expected_plain_numeric_emphasis(self) -> None:
        infantry = search_advanced_cards(family="infantry")
        artillery = search_advanced_cards(family="artillery")
        logistics = search_advanced_cards(family="logistics")
        task_organizations = search_advanced_cards(family="task_organizations")

        self.assertTrue(all(card.control >= 6 for card in infantry))
        self.assertTrue(all(card.support >= 5 for card in artillery))
        self.assertTrue(all(card.supply >= 5 for card in logistics))
        self.assertTrue(all(card.command == 6 for card in task_organizations))

    def test_rarity_is_collectible_metadata_not_missing_data(self) -> None:
        represented = {card.rarity for card in ADVANCED_CARDS}
        self.assertEqual(represented, set(RARITIES))

    def test_every_card_has_a_json_safe_api_shape(self) -> None:
        payload = [card.to_dict() for card in ADVANCED_CATALOG]
        restored = json.loads(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(len(restored), 201)
        self.assertEqual(restored[0]["domain"], ADVANCED_CATALOG[0].domain.value)
        self.assertEqual(
            restored[0]["play_kind"], ADVANCED_CATALOG[0].play_kind.value
        )
        self.assertEqual(set(restored[0]), {field.name for field in fields(AdvancedCard)})

    def test_default_starter_deck_has_twenty_four_unique_known_cards(self) -> None:
        self.assertEqual(len(ADVANCED_STARTER_DECK), 24)
        self.assertEqual(len(set(ADVANCED_STARTER_DECK)), 24)
        self.assertTrue(set(ADVANCED_STARTER_DECK).issubset(ADVANCED_CARD_INDEX))
        self.assertEqual(build_balanced_deck(), ADVANCED_STARTER_DECK)

    def test_default_starter_deck_balances_all_domains_and_card_kinds(self) -> None:
        cards = [get_advanced_card(card_id) for card_id in ADVANCED_STARTER_DECK]
        domain_counts = Counter(card.domain for card in cards)
        self.assertEqual(domain_counts, {domain: 4 for domain in Domain})
        self.assertEqual(
            {card.play_kind for card in cards},
            set(PlayKind) - {PlayKind.VISUAL},
        )
        self.assertGreater(sum(card.control for card in cards), 0)
        self.assertGreater(sum(card.support for card in cards), 0)
        self.assertGreater(sum(card.recon for card in cards), 0)
        self.assertGreater(sum(card.command for card in cards), 0)
        self.assertGreater(sum(card.mobility for card in cards), 0)

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
        for bad_size in (0, -1, True, 181):
            with self.subTest(size=bad_size):
                with self.assertRaises(ValueError):
                    build_balanced_deck(bad_size)
        with self.assertRaises(ValueError):
            build_balanced_deck(2, (ADVANCED_CARDS[0], ADVANCED_CARDS[0]))
        with self.assertRaises(ValueError):
            build_balanced_deck(1, (ADVANCED_CATALOG_INDEX["advanced_frames_01"],))

    def test_lookup_helpers_are_bijective_and_fail_loudly(self) -> None:
        for card in ADVANCED_CATALOG:
            self.assertIs(get_advanced_catalog_entry(card.id), card)
            self.assertIs(get_advanced_card_for_symbol(card.symbol_id), card)
            if is_playable_advanced_card(card):
                self.assertIs(get_advanced_card(card.id), card)
            else:
                with self.assertRaises(KeyError):
                    get_advanced_card(card.id)
        with self.assertRaises(KeyError):
            get_advanced_card("not_an_advanced_card")
        with self.assertRaises(KeyError):
            get_advanced_card_for_symbol("not_a_symbol")

    def test_search_supports_text_and_each_filter(self) -> None:
        armor = search_advanced_cards(family="armor")
        self.assertEqual(len(armor), 12)
        self.assertTrue(all(card.family == "armor" for card in armor))

        sea_by_enum = search_advanced_cards(domain=Domain.SEA)
        sea_by_value = search_advanced_cards(domain=Domain.SEA.value)
        self.assertEqual(sea_by_enum, sea_by_value)
        self.assertTrue(all(card.domain == Domain.SEA for card in sea_by_enum))

        support = search_advanced_cards(play_kind=PlayKind.SUPPORT)
        self.assertTrue(support)
        self.assertTrue(all(card.play_kind == PlayKind.SUPPORT for card in support))

        featured = ADVANCED_CARDS[37]
        self.assertIn(featured, search_advanced_cards(featured.name))
        self.assertEqual(search_advanced_cards(featured.id), (featured,))

        rarity = search_advanced_cards(rarity="希少")
        self.assertTrue(rarity)
        self.assertTrue(all(card.rarity == "希少" for card in rarity))

    def test_search_returns_only_playable_cards(self) -> None:
        ordinary = search_advanced_cards(entry_kind=ADVANCED_ENTRY_KIND_CARD)
        scales = search_advanced_cards(entry_kind=ADVANCED_ENTRY_KIND_SCALE)

        self.assertEqual(ADVANCED_ENTRY_KINDS, ("部隊・装備など", "部隊規模"))
        self.assertEqual(len(ordinary), 180)
        self.assertEqual(scales, ())
        self.assertTrue(all(is_playable_advanced_card(card) for card in ordinary))
        catalog_scales = tuple(
            card for card in ADVANCED_CATALOG if advanced_entry_kind(card) == "部隊規模"
        )
        self.assertEqual(len(catalog_scales), 14)
        self.assertTrue(all(card.family == "echelon" for card in catalog_scales))
        self.assertEqual(search_advanced_cards(entry_kind="不明な区分"), ())

    def test_frame_symbols_are_reference_data_not_playable_cards(self) -> None:
        frames = tuple(card for card in ADVANCED_CATALOG if card.family == "frames")
        self.assertEqual(len(frames), 7)
        self.assertTrue(all(card.id not in ADVANCED_CARD_INDEX for card in frames))
        self.assertTrue(
            all(get_advanced_card(card_id).family != "frames" for card_id in ADVANCED_STARTER_DECK)
        )

    def test_bases_remain_playable_facility_cards(self) -> None:
        base_ids = (
            "advanced_naval_units_01",
            "advanced_task_organizations_02",
        )
        for card_id in base_ids:
            with self.subTest(card_id=card_id):
                card = get_advanced_card(card_id)
                self.assertEqual(card.play_kind, PlayKind.FACILITY)
                self.assertFalse(can_attach_advanced_scale(card))

    def test_echelons_become_fourteen_scale_modifiers(self) -> None:
        self.assertEqual(len(ADVANCED_SCALE_CARDS), 14)
        self.assertIs(ADVANCED_SCALES, ADVANCED_SCALE_CARDS)
        self.assertEqual(len(ADVANCED_SCALE_INDEX), 14)
        self.assertEqual(build_advanced_scales(), ADVANCED_SCALE_CARDS)
        self.assertEqual(DEFAULT_ADVANCED_SCALE_ID, "advanced_echelon_09")
        self.assertEqual(get_advanced_scale(DEFAULT_ADVANCED_SCALE_ID).name, "中隊")

        for scale in ADVANCED_SCALE_CARDS:
            with self.subTest(scale=scale.id):
                self.assertIsInstance(scale, AdvancedScale)
                self.assertNotIn(scale.id, ADVANCED_CARD_INDEX)
                self.assertIn(scale.id, ADVANCED_CATALOG_INDEX)
                self.assertTrue(scale.description.strip())
                self.assertEqual(
                    set(scale.stat_deltas()), set(NUMERIC_CAPABILITY_FIELDS)
                )
                self.assertEqual(scale.to_dict()["name"], scale.name)
                self.assertIs(get_advanced_scale(scale.id), scale)

    def test_scale_attachment_and_clamped_stats(self) -> None:
        unit = next(card for card in ADVANCED_CARDS if card.play_kind == PlayKind.UNIT)
        support = next(
            card for card in ADVANCED_CARDS if card.play_kind == PlayKind.SUPPORT
        )
        task_force = next(
            card
            for card in ADVANCED_CARDS
            if card.play_kind == PlayKind.TASK_FORCE
            and intrinsic_advanced_scale_id(card) is None
        )
        entity = next(
            card for card in ADVANCED_CARDS if card.play_kind == PlayKind.ENTITY
        )
        facility = next(
            card for card in ADVANCED_CARDS if card.play_kind == PlayKind.FACILITY
        )

        self.assertTrue(can_attach_advanced_scale(unit))
        self.assertTrue(can_attach_advanced_scale(support))
        self.assertTrue(can_attach_advanced_scale(task_force))
        self.assertFalse(can_attach_advanced_scale(entity))
        self.assertFalse(can_attach_advanced_scale(facility))
        self.assertEqual(
            scaled_advanced_stats(unit),
            {field: getattr(unit, field) for field in NUMERIC_CAPABILITY_FIELDS},
        )
        largest = scaled_advanced_stats(unit, "advanced_echelon_01")
        for field, value in largest.items():
            self.assertGreaterEqual(value, -4 if field == "supply" else 0)
            self.assertLessEqual(value, 6)
        with self.assertRaises(ValueError):
            scaled_advanced_stats(facility)
        with self.assertRaises(KeyError):
            get_advanced_scale("missing-scale")

    def test_fixed_task_organizations_cannot_take_a_conflicting_scale(self) -> None:
        fixed = get_advanced_card("advanced_task_organizations_05")
        self.assertEqual(intrinsic_advanced_scale_id(fixed), "advanced_echelon_05")
        self.assertFalse(can_attach_advanced_scale(fixed))
        self.assertEqual(
            scaled_advanced_stats(fixed),
            scaled_advanced_stats(fixed, "advanced_echelon_05"),
        )
        with self.assertRaises(ValueError):
            scaled_advanced_stats(fixed, "advanced_echelon_09")

    def test_task_organization_names_and_scales_are_separate(self) -> None:
        mission_corps = get_advanced_card("advanced_task_organizations_04")
        mission_division = get_advanced_card("advanced_task_organizations_05")
        pure_scale = get_advanced_catalog_entry("advanced_echelon_05")

        self.assertEqual(advanced_name_and_scale(mission_corps), ("任務部隊", "軍団"))
        self.assertEqual(advanced_name_and_scale(mission_division), ("任務部隊", "師団"))
        self.assertEqual(advanced_name_and_scale(pure_scale), (None, pure_scale.name))
        self.assertIn(mission_division, search_advanced_cards("任務部隊"))

        for card in ADVANCED_CATALOG:
            name, scale = advanced_name_and_scale(card)
            if card.family != "echelon" and scale is not None:
                self.assertEqual(name, "任務部隊")
                self.assertIn(scale, TASK_ORGANIZATION_SCALES)
                self.assertFalse(name.endswith(TASK_ORGANIZATION_SCALES))


if __name__ == "__main__":
    unittest.main()

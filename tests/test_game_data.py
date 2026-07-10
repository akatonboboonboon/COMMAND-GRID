import unittest

from game_data import CARDS, ROLE_INFO, STARTER_DECK, analyze_deck, get_card
from symbol_catalog import (
    CARD_SYMBOL_IDS,
    FAMILY_INDEX,
    STAGE_LABELS,
    SYMBOL_CATALOG,
    SYMBOL_FAMILIES,
    SYMBOL_INDEX,
    symbols_for_family,
)


class GameDataTests(unittest.TestCase):
    def test_card_ids_are_unique(self) -> None:
        ids = [card.id for card in CARDS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_role_has_cards(self) -> None:
        represented = {card.branch for card in CARDS}
        self.assertEqual(represented, set(ROLE_INFO))

    def test_starter_deck_is_complete_and_owned(self) -> None:
        self.assertEqual(len(STARTER_DECK), 12)
        self.assertTrue(all(get_card(card_id).owned for card_id in STARTER_DECK))

    def test_balanced_starter_deck_has_no_missing_card_tip(self) -> None:
        result = analyze_deck(STARTER_DECK)
        self.assertEqual(result["count"], 12)
        self.assertEqual(result["branches"], {role: 2 for role in ROLE_INFO})
        self.assertEqual(result["tips"], ["6つの役割がそろっています。初めての対戦にも使いやすい構成です。"])

    def test_reference_symbol_manifest_is_complete(self) -> None:
        self.assertEqual(len(SYMBOL_CATALOG), 201)
        self.assertEqual(len({symbol.id for symbol in SYMBOL_CATALOG}), 201)
        self.assertEqual(len({symbol.source_cell_id for symbol in SYMBOL_CATALOG}), 201)
        self.assertEqual(len({symbol.visual_id for symbol in SYMBOL_CATALOG}), 201)

    def test_every_symbol_has_a_game_use_and_unlock_stage(self) -> None:
        for symbol in SYMBOL_CATALOG:
            self.assertIn(symbol.family_id, FAMILY_INDEX)
            self.assertTrue(symbol.plain_role)
            self.assertTrue(symbol.play_kind.value)
            self.assertIn(symbol.unlock_stage, STAGE_LABELS)

    def test_family_membership_is_consistent(self) -> None:
        family_ids = {family.id for family in SYMBOL_FAMILIES}
        self.assertEqual(family_ids, set(FAMILY_INDEX))
        for family in SYMBOL_FAMILIES:
            symbols = symbols_for_family(family.id)
            self.assertEqual(len(symbols), len(family.items))
            self.assertTrue(symbols)

    def test_every_playable_card_uses_a_catalog_symbol(self) -> None:
        self.assertEqual(set(CARD_SYMBOL_IDS), {card.id for card in CARDS})
        self.assertTrue(all(symbol_id in SYMBOL_INDEX for symbol_id in CARD_SYMBOL_IDS.values()))


if __name__ == "__main__":
    unittest.main()

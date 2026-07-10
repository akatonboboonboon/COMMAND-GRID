import unittest

from game_data import CARDS, ROLE_INFO, STARTER_DECK, analyze_deck, get_card


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


if __name__ == "__main__":
    unittest.main()


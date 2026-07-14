import unittest

import game_data
from game_data import CARDS, GLOSSARY, ROLE_INFO, STARTER_DECK, analyze_deck, get_card
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

    def test_every_card_has_rule_copy(self) -> None:
        for card in CARDS:
            with self.subTest(card=card.id):
                self.assertTrue(card.game_text.strip())

    def test_card_names_match_the_reviewed_changes(self) -> None:
        expected_names = {
            "infantry_1": "歩兵中隊",
            "infantry_2": "市街地警備中隊",
            "infantry_3": "ヘリボーン中隊",
            "armor_1": "機械化装甲中隊",
            "armor_2": "機械化歩兵中隊",
            "armor_3": "重機械化装甲中隊",
            "recon_1": "高機動偵察小隊",
            "recon_2": "無人偵察小隊",
            "recon_3": "電子偵察小隊",
            "artillery_1": "自動車化野戦砲中隊",
            "artillery_2": "自走砲小隊",
            "artillery_3": "自動車化ロケット砲中隊",
            "engineer_1": "工兵中隊",
            "engineer_2": "架橋工兵中隊",
            "engineer_3": "建築工兵中隊",
            "logistics_1": "野戦補給中隊",
            "logistics_2": "野戦整備中隊",
            "logistics_3": "戦域輸送中隊",
        }

        self.assertEqual({card.id: card.name for card in CARDS}, expected_names)

    def test_echelon_is_collection_metadata_without_a_gameplay_api(self) -> None:
        reference_echelons = {"班", "分隊", "小隊", "中隊", "大隊"}
        for card in CARDS:
            with self.subTest(card=card.id):
                self.assertIn(card.echelon, reference_echelons)
        removed_names = (
            "FormationScale",
            "FORMATION_SCALES",
            "FORMATION_INDEX",
            "get_formation",
            "formation_label",
        )
        self.assertTrue(all(not hasattr(game_data, name) for name in removed_names))

    def test_beginner_copy_does_not_invent_rows_inside_a_lane(self) -> None:
        copy = " ".join(
            [
                *(str(info["plain"]) for info in ROLE_INFO.values()),
                *(explanation for _, explanation in GLOSSARY),
            ]
        )
        self.assertNotIn("前列", copy)
        self.assertNotIn("支援列", copy)

    def test_card_copy_does_not_promise_unimplemented_rules(self) -> None:
        forbidden_phrases = (
            "中央",
            "隣",
            "移動",
            "歩兵としても",
            "命令",
            "公開前",
            "発見済み",
            "前列",
            "1試合",
            "一度",
            "回数制限",
            "守備力",
            "地形",
            "前のラウンド",
            "次ラウンド",
            "次のラウンド",
            "回復",
            "弱った部隊",
            "二つの戦線",
            "無効",
        )
        for card in CARDS:
            rule_copy = " ".join((card.tagline, card.game_text, card.good_with))
            for phrase in forbidden_phrases:
                with self.subTest(card=card.id, phrase=phrase):
                    self.assertNotIn(phrase, rule_copy)

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

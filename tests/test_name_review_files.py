import csv
import unittest
from collections import Counter
from pathlib import Path

from advanced_game_data import ADVANCED_CATALOG, ADVANCED_CARDS
from game_data import CARDS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CARD_NAMES_PATH = PROJECT_ROOT / "CARD_NAMES_FOR_REVIEW.csv"
REMOVED_UNIT_SCALES_PATH = PROJECT_ROOT / "UNIT_SCALES_FOR_REVIEW.csv"
ADVANCED_INDEX_PATH = PROJECT_ROOT / "ADVANCED_CATALOG_INDEX.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


class NameReviewFileTests(unittest.TestCase):
    def test_name_lists_cover_cards_and_collection_symbols(self) -> None:
        name_rows = read_csv(CARD_NAMES_PATH)
        index_rows = read_csv(ADVANCED_INDEX_PATH)
        normal_cards = {card.id: card for card in CARDS}
        advanced_cards = {card.id: card for card in ADVANCED_CARDS}
        advanced_catalog = {card.id: card for card in ADVANCED_CATALOG}

        self.assertFalse(REMOVED_UNIT_SCALES_PATH.exists())
        self.assertEqual(len(name_rows), 198)
        self.assertEqual(len(index_rows), 201)
        self.assertEqual(
            Counter(row["カタログ"] for row in name_rows),
            {
                "通常・カジュアル18枚": 18,
                "本格シミュレーション・プレイ可能180枚": 180,
            },
        )
        self.assertEqual(
            {row["カードID"] for row in name_rows},
            set(normal_cards) | set(advanced_cards),
        )
        self.assertEqual(
            {row["記号ID"] for row in index_rows},
            set(advanced_catalog),
        )

        for row in name_rows:
            card_id = row["カードID"]
            card = normal_cards.get(card_id) or advanced_cards[card_id]
            self.assertEqual(row["現在の部隊・カード名"], card.name)

        handling_counts = Counter(row["ゲーム内の扱い"] for row in index_rows)
        self.assertEqual(
            handling_counts,
            {
                "プレイ可能カード": 174,
                "施設カード": 6,
                "表示枠（カードではない）": 7,
                "コレクション記号（カードではない）": 14,
            },
        )

        for row in index_rows:
            card = advanced_catalog[row["記号ID"]]
            self.assertEqual(row["現在の名称"], card.name)
            if card.family == "frames":
                self.assertEqual(row["ゲーム内の扱い"], "表示枠（カードではない）")
                self.assertEqual(row["名称の編集先"], "対象外（表示用）")
            elif card.family == "echelon":
                self.assertEqual(
                    row["ゲーム内の扱い"],
                    "コレクション記号（カードではない）",
                )
                self.assertEqual(row["名称の編集先"], "対象外（コレクション専用）")
            else:
                expected_usage = (
                    "施設カード"
                    if card.play_kind.value == "施設カード"
                    else "プレイ可能カード"
                )
                self.assertEqual(row["ゲーム内の扱い"], expected_usage)
                self.assertEqual(row["名称の編集先"], "CARD_NAMES_FOR_REVIEW.csv")

    def test_index_file_has_clear_collection_only_columns(self) -> None:
        with ADVANCED_INDEX_PATH.open(encoding="utf-8", newline="") as file:
            rows = list(csv.reader(file))

        self.assertEqual(
            rows[0],
            [
                "番号",
                "記号ID",
                "分類",
                "現在の名称",
                "ゲーム内の扱い",
                "名称の編集先",
            ],
        )
        self.assertTrue(all(len(row) == 6 for row in rows[1:]))
        flattened = [cell for row in rows for cell in row]
        self.assertNotIn("部隊規模の編集先", flattened)
        self.assertFalse(any("UNIT_SCALES_FOR_REVIEW.csv" in cell for cell in flattened))
        self.assertFalse(any("編制効果" in cell for cell in flattened))

    def test_name_file_has_one_edit_blank_per_row(self) -> None:
        with CARD_NAMES_PATH.open(encoding="utf-8", newline="") as file:
            reader = csv.reader(file)
            rows = list(reader)

        self.assertEqual(
            rows[0],
            [
                "カタログ",
                "番号",
                "カードID",
                "分類",
                "現在の部隊・カード名",
                "変更後の部隊・カード名",
            ],
        )
        self.assertTrue(all(len(row) == 6 for row in rows[1:]))
        self.assertTrue(all(row[-1] == "" for row in rows[1:]))
        self.assertTrue(all(row[-2] != "" for row in rows[1:]))


if __name__ == "__main__":
    unittest.main()

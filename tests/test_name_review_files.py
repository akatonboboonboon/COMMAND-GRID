import csv
import unittest
from collections import Counter
from pathlib import Path

from advanced_game_data import ADVANCED_CATALOG, ADVANCED_CARDS
from game_data import CARDS
from symbol_catalog import SYMBOL_INDEX


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CARD_NAMES_PATH = PROJECT_ROOT / "CARD_NAMES_FOR_REVIEW.csv"
REMOVED_UNIT_SCALES_PATH = PROJECT_ROOT / "UNIT_SCALES_FOR_REVIEW.csv"
ADVANCED_INDEX_PATH = PROJECT_ROOT / "ADVANCED_CATALOG_INDEX.csv"

NAME_FILE_COLUMNS = [
    "カタログ",
    "番号",
    "カードID",
    "元記号ID",
    "分類",
    "現在の部隊・カード名",
    "変更後の部隊・カード名",
    "制圧",
    "支援",
    "偵察",
    "補給",
    "指揮",
    "機動",
]
STAT_COLUMNS = ("制圧", "支援", "偵察", "補給", "指揮", "機動")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


class NameReviewFileTests(unittest.TestCase):
    def test_name_file_covers_normal_18_and_reviewed_advanced_121(self) -> None:
        rows = read_csv(CARD_NAMES_PATH)
        normal_rows = [row for row in rows if row["カタログ"].startswith("通常")]
        advanced_rows = [row for row in rows if row["カタログ"].startswith("本格")]

        self.assertFalse(REMOVED_UNIT_SCALES_PATH.exists())
        self.assertEqual(len(rows), 139)
        self.assertEqual(len(normal_rows), 18)
        self.assertEqual(len(advanced_rows), 121)
        self.assertEqual(
            Counter(row["カタログ"] for row in rows),
            {
                "通常・カジュアル18枚": 18,
                "本格シミュレーション121枚": 121,
            },
        )
        self.assertEqual([int(row["番号"]) for row in normal_rows], list(range(1, 19)))
        self.assertEqual(
            [int(row["番号"]) for row in advanced_rows], list(range(1, 122))
        )

        ids = [row["カードID"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(
            set(ids),
            {card.id for card in CARDS} | {card.id for card in ADVANCED_CARDS},
        )

    def test_advanced_rows_have_valid_source_symbols_names_and_stats(self) -> None:
        rows = [
            row
            for row in read_csv(CARD_NAMES_PATH)
            if row["カタログ"].startswith("本格")
        ]
        cards = {card.id: card for card in ADVANCED_CARDS}
        indexed_symbol_ids = {
            row["記号ID"].removeprefix("advanced_")
            for row in read_csv(ADVANCED_INDEX_PATH)
        }

        for row in rows:
            with self.subTest(card=row["カードID"]):
                self.assertIn(row["元記号ID"], SYMBOL_INDEX)
                self.assertIn(row["元記号ID"], indexed_symbol_ids)
                card = cards[row["カードID"]]
                final_name = (
                    row["変更後の部隊・カード名"].strip()
                    or row["現在の部隊・カード名"].strip()
                )
                self.assertEqual(final_name, card.name)
                for column in STAT_COLUMNS:
                    value = int(row[column])
                    lower = -4 if column == "補給" else 0
                    self.assertGreaterEqual(value, lower)
                    self.assertLessEqual(value, 6)

    def test_name_file_has_the_canonical_thirteen_column_schema(self) -> None:
        with CARD_NAMES_PATH.open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.reader(file))

        self.assertEqual(rows[0], NAME_FILE_COLUMNS)
        self.assertTrue(all(len(row) == len(NAME_FILE_COLUMNS) for row in rows[1:]))

        normal_rows = [row for row in rows[1:] if row[0].startswith("通常")]
        advanced_rows = [row for row in rows[1:] if row[0].startswith("本格")]
        self.assertTrue(all(all(cell == "" for cell in row[7:]) for row in normal_rows))
        self.assertTrue(all(all(cell != "" for cell in row[7:]) for row in advanced_rows))

    def test_collection_index_still_contains_all_201_source_symbols(self) -> None:
        rows = read_csv(ADVANCED_INDEX_PATH)
        self.assertEqual(len(rows), 201)
        self.assertEqual(
            {row["記号ID"] for row in rows},
            {card.id for card in ADVANCED_CATALOG},
        )
        self.assertEqual([int(row["番号"]) for row in rows], list(range(1, 202)))


if __name__ == "__main__":
    unittest.main()

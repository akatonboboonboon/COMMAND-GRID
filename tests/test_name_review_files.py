import csv
import unittest
from pathlib import Path

from advanced_game_data import ADVANCED_CARDS, advanced_name_and_scale
from game_data import CARDS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CARD_NAMES_PATH = PROJECT_ROOT / "CARD_NAMES_FOR_REVIEW.csv"
UNIT_SCALES_PATH = PROJECT_ROOT / "UNIT_SCALES_FOR_REVIEW.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


class NameReviewFileTests(unittest.TestCase):
    def test_name_and_scale_lists_cover_every_catalog_entry_once(self) -> None:
        name_rows = read_csv(CARD_NAMES_PATH)
        scale_rows = read_csv(UNIT_SCALES_PATH)
        normal_cards = {card.id: card for card in CARDS}
        advanced_names = {
            card.id: card for card in ADVANCED_CARDS if card.family != "echelon"
        }
        advanced_scales = {
            card.id: card for card in ADVANCED_CARDS if card.family == "echelon"
        }
        advanced_task_scales = {
            card.id: scale
            for card in ADVANCED_CARDS
            if card.family != "echelon"
            for _, scale in (advanced_name_and_scale(card),)
            if scale is not None
        }

        self.assertEqual(len(name_rows), 205)
        self.assertEqual(len(scale_rows), 38)
        self.assertEqual(
            {row["カードID"] for row in name_rows},
            set(normal_cards) | set(advanced_names),
        )
        self.assertEqual(
            {row["対象ID"] for row in scale_rows},
            set(normal_cards) | set(advanced_task_scales) | set(advanced_scales),
        )

        for row in name_rows:
            card_id = row["カードID"]
            if card_id in normal_cards:
                card = normal_cards[card_id]
                self.assertEqual(row["現在の部隊・カード名"], card.name)
            else:
                card = advanced_names[card_id]
                name, _ = advanced_name_and_scale(card)
                self.assertIsNotNone(name)
                self.assertEqual(row["現在の部隊・カード名"], name)

        for row in scale_rows:
            target_id = row["対象ID"]
            if target_id in normal_cards:
                expected_scale = normal_cards[target_id].echelon
            elif target_id in advanced_task_scales:
                expected_scale = advanced_task_scales[target_id]
            else:
                expected_scale = advanced_scales[target_id].name
            self.assertEqual(row["現在の部隊規模"], expected_scale)

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

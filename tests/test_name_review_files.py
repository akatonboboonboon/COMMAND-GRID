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

        self.assertEqual(len(name_rows), 205)
        self.assertEqual(len(scale_rows), 14)
        self.assertEqual(
            {row["カードID"] for row in name_rows},
            set(normal_cards) | set(advanced_names),
        )
        self.assertEqual(
            {row["規模ID"] for row in scale_rows},
            set(advanced_scales),
        )

        for row in name_rows:
            card_id = row["カードID"]
            if card_id in normal_cards:
                card = normal_cards[card_id]
                self.assertEqual(row["現在の部隊・カード名"], card.name)
                self.assertEqual(row["現在の部隊規模"], card.echelon)
            else:
                card = advanced_names[card_id]
                name, scale = advanced_name_and_scale(card)
                self.assertIsNotNone(name)
                self.assertEqual(row["現在の部隊・カード名"], name)
                self.assertEqual(row["現在の部隊規模"], scale or "")

        for row in scale_rows:
            self.assertEqual(
                row["現在の部隊規模"],
                advanced_scales[row["規模ID"]].name,
            )


if __name__ == "__main__":
    unittest.main()

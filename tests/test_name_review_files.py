import csv
import unittest
from collections import Counter
from pathlib import Path

from advanced_game_data import (
    ADVANCED_CATALOG,
    ADVANCED_CARDS,
    ADVANCED_SCALE_CARDS,
    advanced_name_and_scale,
)
from game_data import CARDS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CARD_NAMES_PATH = PROJECT_ROOT / "CARD_NAMES_FOR_REVIEW.csv"
UNIT_SCALES_PATH = PROJECT_ROOT / "UNIT_SCALES_FOR_REVIEW.csv"
ADVANCED_INDEX_PATH = PROJECT_ROOT / "ADVANCED_CATALOG_INDEX.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


class NameReviewFileTests(unittest.TestCase):
    def test_name_and_scale_lists_cover_every_catalog_entry_once(self) -> None:
        name_rows = read_csv(CARD_NAMES_PATH)
        scale_rows = read_csv(UNIT_SCALES_PATH)
        index_rows = read_csv(ADVANCED_INDEX_PATH)
        normal_cards = {card.id: card for card in CARDS}
        advanced_names = {card.id: card for card in ADVANCED_CARDS}
        advanced_scales = {scale.id: scale for scale in ADVANCED_SCALE_CARDS}
        frame_ids = {card.id for card in ADVANCED_CATALOG if card.family == "frames"}
        advanced_task_scales = {
            card.id: scale
            for card in ADVANCED_CARDS
            for _, scale in (advanced_name_and_scale(card),)
            if scale is not None
        }

        self.assertEqual(len(name_rows), 198)
        self.assertEqual(len(scale_rows), 38)
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
            set(normal_cards) | set(advanced_names),
        )
        self.assertEqual(
            {row["対象ID"] for row in scale_rows},
            set(normal_cards) | set(advanced_task_scales) | set(advanced_scales),
        )
        self.assertEqual(
            {row["カードID"] for row in index_rows},
            {card.id for card in ADVANCED_CATALOG},
        )
        advanced_name_ids = {
            row["カードID"] for row in name_rows if row["カードID"].startswith("advanced_")
        }
        advanced_scale_ids = {
            row["対象ID"] for row in scale_rows if row["対象ID"].startswith("advanced_")
        }
        self.assertEqual(len(advanced_name_ids), 180)
        self.assertEqual(len(advanced_scale_ids), 20)
        self.assertEqual(
            advanced_name_ids & advanced_scale_ids,
            set(advanced_task_scales),
        )
        self.assertEqual(
            advanced_name_ids | advanced_scale_ids,
            ({card.id for card in ADVANCED_CATALOG} - frame_ids),
        )
        self.assertTrue(set(advanced_scales).isdisjoint(advanced_name_ids))
        self.assertTrue(frame_ids.isdisjoint(advanced_name_ids | advanced_scale_ids))

        for row in name_rows:
            card_id = row["カードID"]
            if card_id in normal_cards:
                card = normal_cards[card_id]
                self.assertEqual(row["現在の部隊・カード名"], card.name)
            else:
                card = advanced_names[card_id]
                name, _ = advanced_name_and_scale(card)
                self.assertEqual(row["現在の部隊・カード名"], name or card.name)

        for row in scale_rows:
            target_id = row["対象ID"]
            if target_id in normal_cards:
                expected_scale = normal_cards[target_id].echelon
            elif target_id in advanced_task_scales:
                expected_scale = advanced_task_scales[target_id]
            else:
                expected_scale = advanced_scales[target_id].name
            self.assertEqual(row["現在の部隊規模"], expected_scale)

        advanced_by_id = {card.id: card for card in ADVANCED_CATALOG}
        for row in index_rows:
            card = advanced_by_id[row["カードID"]]
            _, scale = advanced_name_and_scale(card)
            if card.family == "frames":
                self.assertEqual(row["プレイ上の扱い"], "表示情報（カードではない）")
                self.assertEqual(row["部隊名の編集先"], "対象外（表示情報）")
                self.assertEqual(row["部隊規模の編集先"], "対象外")
            elif card.family == "echelon":
                self.assertEqual(row["プレイ上の扱い"], "編制効果（カードではない）")
                self.assertEqual(row["部隊名の編集先"], "対象外（部隊規模）")
                self.assertEqual(row["部隊規模の編集先"], "UNIT_SCALES_FOR_REVIEW.csv")
            else:
                expected_usage = (
                    "施設カード" if card.play_kind.value == "施設カード" else "プレイ可能カード"
                )
                self.assertEqual(row["プレイ上の扱い"], expected_usage)
                self.assertEqual(row["部隊名の編集先"], "CARD_NAMES_FOR_REVIEW.csv")
                self.assertEqual(
                    row["部隊規模の編集先"],
                    "UNIT_SCALES_FOR_REVIEW.csv" if scale is not None else "対象外",
                )

        route_counts = Counter(
            (
                row["部隊名の編集先"] == "CARD_NAMES_FOR_REVIEW.csv",
                row["部隊規模の編集先"] == "UNIT_SCALES_FOR_REVIEW.csv",
            )
            for row in index_rows
        )
        self.assertEqual(route_counts[(True, False)], 174)
        self.assertEqual(route_counts[(False, True)], 14)
        self.assertEqual(route_counts[(True, True)], 6)
        self.assertEqual(route_counts[(False, False)], 7)

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

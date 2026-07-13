import unittest

from basic_tutorial import BASIC_TUTORIAL_LESSONS, get_basic_lesson
from game_data import CARD_INDEX


class BasicTutorialTests(unittest.TestCase):
    def test_course_is_ordered_unique_and_has_one_task_per_lesson(self) -> None:
        self.assertEqual(len(BASIC_TUTORIAL_LESSONS), 9)
        self.assertEqual(
            len({lesson.id for lesson in BASIC_TUTORIAL_LESSONS}),
            len(BASIC_TUTORIAL_LESSONS),
        )
        self.assertEqual(
            {lesson.kind for lesson in BASIC_TUTORIAL_LESSONS},
            {"choice", "card_choice", "deploy", "reveal"},
        )
        for lesson in BASIC_TUTORIAL_LESSONS:
            self.assertTrue(lesson.title)
            self.assertTrue(lesson.explanation)
            self.assertTrue(lesson.task)
            if lesson.choices:
                self.assertIn(lesson.correct_choice, dict(lesson.choices))

    def test_every_card_choice_references_real_cards(self) -> None:
        for lesson in BASIC_TUTORIAL_LESSONS:
            if lesson.kind == "card_choice":
                self.assertTrue(set(dict(lesson.choices)).issubset(CARD_INDEX))

    def test_choice_copy_is_balanced_and_does_not_reveal_the_answer(self) -> None:
        giveaway_words = ("全部", "必ず", "どこでも", "正解", "不正解")
        for lesson in BASIC_TUTORIAL_LESSONS:
            if not lesson.choices:
                continue
            with self.subTest(lesson=lesson.id):
                choice_ids = [choice_id for choice_id, _ in lesson.choices]
                labels = [label for _, label in lesson.choices]
                self.assertEqual(len(labels), 3)
                self.assertEqual(len(set(choice_ids)), 3)
                self.assertEqual(len(set(labels)), 3)
                self.assertTrue(lesson.task.endswith("選んでください。"))
                self.assertNotIn(dict(lesson.choices)[lesson.correct_choice], lesson.task)
                self.assertNotIn(dict(lesson.choices)[lesson.correct_choice], lesson.hint)
                self.assertFalse(
                    any(word in label for word in giveaway_words for label in labels)
                )
                if lesson.kind == "choice":
                    lengths = [len(label) for label in labels]
                    self.assertLessEqual(max(lengths) - min(lengths), 4)

    def test_correct_answers_use_all_three_positions_without_a_cycle(self) -> None:
        positions = []
        for lesson in BASIC_TUTORIAL_LESSONS:
            if lesson.choices:
                choice_ids = [choice_id for choice_id, _ in lesson.choices]
                positions.append(choice_ids.index(lesson.correct_choice))

        self.assertEqual(
            {position: positions.count(position) for position in range(3)},
            {0: 2, 1: 3, 2: 2},
        )
        self.assertNotEqual(positions, [index % 3 for index in range(len(positions))])

    def test_lesson_lookup_uses_stable_ids(self) -> None:
        self.assertEqual(get_basic_lesson("deploy").kind, "deploy")
        with self.assertRaises(KeyError):
            get_basic_lesson("missing")

    def test_simultaneous_lesson_keeps_enemy_card_hidden_until_recon(self) -> None:
        lesson = get_basic_lesson("simultaneous")
        copy = " ".join((lesson.plain_goal, lesson.explanation, lesson.success_message))
        self.assertIn("配置先", copy)
        self.assertIn("未確認", copy)
        self.assertIn("偵察", copy)

    def test_course_teaches_the_nine_round_match_length(self) -> None:
        full_copy = " ".join(
            " ".join(
                (
                    lesson.title,
                    lesson.plain_goal,
                    lesson.explanation,
                    lesson.task,
                    lesson.success_message,
                    lesson.hint,
                    *(label for _, label in lesson.choices),
                )
            )
            for lesson in BASIC_TUTORIAL_LESSONS
        )
        rounds = get_basic_lesson("rounds")
        self.assertEqual(rounds.correct_choice, "nine")
        self.assertEqual(dict(rounds.choices)["nine"], "未使用は9枚になる")
        self.assertIn("9ラウンド", full_copy)
        self.assertNotIn("6ラウンド", full_copy)
        self.assertNotIn("最低6枚", full_copy)

    def test_course_copy_uses_scale_free_card_names(self) -> None:
        old_combined_names = (
            "第1歩兵中隊",
            "空中機動歩兵班",
            "第4機甲中隊",
            "前方偵察班",
            "電子偵察班",
            "野戦砲兵中隊",
            "第2工兵中隊",
            "前線補給中隊",
        )
        full_copy = repr(BASIC_TUTORIAL_LESSONS)
        for old_name in old_combined_names:
            with self.subTest(name=old_name):
                self.assertNotIn(old_name, full_copy)


if __name__ == "__main__":
    unittest.main()

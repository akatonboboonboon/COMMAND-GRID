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
        self.assertEqual(dict(rounds.choices)["nine"], "9枚")
        self.assertIn("9ラウンド", full_copy)
        self.assertNotIn("6ラウンド", full_copy)
        self.assertNotIn("最低6枚", full_copy)


if __name__ == "__main__":
    unittest.main()

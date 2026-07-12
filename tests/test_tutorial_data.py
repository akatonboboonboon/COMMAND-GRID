import unittest

from game_data import CARDS, CARD_INDEX
from tutorial_data import (
    CARD_TUTORIALS,
    OFFICIAL_DECKS,
    OFFICIAL_DECK_INDEX,
    TUTORIAL_INDEX,
    deck_missing_card_ids,
    deck_missing_cards,
    deck_owned_cards_in_order,
    get_official_deck,
    get_tutorial,
)


class TutorialDataTests(unittest.TestCase):
    def test_every_card_has_one_staged_tutorial(self) -> None:
        self.assertEqual(len(CARD_TUTORIALS), len(CARDS))
        self.assertEqual(set(TUTORIAL_INDEX), set(CARD_INDEX))
        for tutorial in CARD_TUTORIALS:
            with self.subTest(card=tutorial.card_id):
                self.assertGreaterEqual(len(tutorial.stages), 5)
                self.assertEqual(
                    len({stage.id for stage in tutorial.stages}),
                    len(tutorial.stages),
                )
                for stage in tutorial.stages:
                    self.assertTrue(stage.title.strip())
                    self.assertTrue(stage.summary.strip())
                    self.assertTrue(stage.explanation.strip())
                    self.assertTrue(stage.practice.strip())

    def test_every_tutorial_finishes_with_a_nine_turn_live_exercise(self) -> None:
        for tutorial in CARD_TUTORIALS:
            with self.subTest(card=tutorial.card_id):
                final_stage = tutorial.stages[-1]
                self.assertEqual(final_stage.id, "exercise")
                self.assertEqual(final_stage.title, "5. 9ターン実戦演習")
                self.assertFalse(final_stage.question)
                self.assertFalse(final_stage.choices)
                self.assertFalse(final_stage.correct_choice)
                self.assertFalse(final_stage.success_message)
                self.assertFalse(final_stage.exercise_lanes)
                exercise_copy = " ".join(
                    (
                        final_stage.summary,
                        final_stage.explanation,
                        final_stage.practice,
                    )
                )
                for required in (
                    "0枚",
                    "9ターン",
                    "2戦線",
                    CARD_INDEX[tutorial.card_id].name,
                    "少なくとも1回使用",
                ):
                    self.assertIn(required, exercise_copy)

    def test_static_course_data_contains_no_obsolete_answer_buttons(self) -> None:
        for tutorial in CARD_TUTORIALS:
            with self.subTest(card=tutorial.card_id):
                self.assertTrue(all(not stage.choices for stage in tutorial.stages))
                self.assertTrue(all(not stage.correct_choice for stage in tutorial.stages))
                self.assertTrue(all(not stage.exercise_lanes for stage in tutorial.stages))

    def test_each_live_exercise_names_its_featured_card(self) -> None:
        for tutorial in CARD_TUTORIALS:
            final_stage = tutorial.stages[-1]
            self.assertIn(
                CARD_INDEX[tutorial.card_id].name,
                final_stage.explanation + final_stage.practice,
            )

    def test_tutorials_link_to_their_featured_official_decks(self) -> None:
        for tutorial in CARD_TUTORIALS:
            with self.subTest(card=tutorial.card_id):
                deck = get_official_deck(tutorial.reward_deck_id)
                self.assertEqual(deck.featured_card_id, tutorial.card_id)
                self.assertIn(tutorial.card_id, deck.card_ids)

    def test_every_card_has_a_twelve_card_official_deck(self) -> None:
        self.assertEqual(len(OFFICIAL_DECKS), len(CARDS))
        self.assertEqual(set(OFFICIAL_DECK_INDEX), set(CARD_INDEX))
        for deck in OFFICIAL_DECKS:
            with self.subTest(deck=deck.id):
                self.assertEqual(len(deck.card_ids), 12)
                self.assertEqual(len(set(deck.card_ids)), 12)
                self.assertTrue(set(deck.card_ids).issubset(CARD_INDEX))
                self.assertIn(deck.featured_card_id, deck.card_ids)
                self.assertTrue(deck.name.strip())
                self.assertTrue(deck.summary.strip())
                self.assertTrue(deck.strategy.strip())

    def test_lookup_helpers_fail_loudly_for_unknown_ids(self) -> None:
        with self.assertRaises(KeyError):
            get_tutorial("not_a_card")
        with self.assertRaises(KeyError):
            get_official_deck("not_a_deck")

    def test_missing_and_owned_helpers_preserve_recipe_order(self) -> None:
        deck = get_official_deck("armor_2")
        owned = {deck.card_ids[index] for index in (0, 2, 5, 8, 11)}
        expected_owned = tuple(card_id for card_id in deck.card_ids if card_id in owned)
        expected_missing = tuple(card_id for card_id in deck.card_ids if card_id not in owned)

        self.assertEqual(deck_owned_cards_in_order(deck, owned), expected_owned)
        self.assertEqual(deck_missing_card_ids(deck.id, owned), expected_missing)
        self.assertEqual(
            tuple(card.id for card in deck_missing_cards(deck, owned)),
            expected_missing,
        )

    def test_helpers_accept_one_shot_iterables(self) -> None:
        deck = get_official_deck("infantry_1")
        owned_ids = deck.card_ids[:6]
        owned_generator = (card_id for card_id in owned_ids)
        self.assertEqual(deck_owned_cards_in_order(deck, owned_generator), owned_ids)

    def test_rule_copy_explains_implemented_edge_cases(self) -> None:
        armor_copy = " ".join(
            stage.explanation for stage in get_tutorial("armor_1").stages
        )
        recon_copy = " ".join(
            stage.explanation for stage in get_tutorial("recon_2").stages
        )
        artillery_copy = " ".join(
            stage.explanation for stage in get_tutorial("artillery_2").stages
        )
        logistics_copy = " ".join(
            stage.explanation for stage in get_tutorial("logistics_3").stages
        )

        self.assertIn("機甲ボーナス+2", armor_copy)
        self.assertIn("同じ戦線", recon_copy)
        self.assertIn("単独の支援1は無効", recon_copy)
        self.assertIn("制圧がなければ支援5は数えられず", artillery_copy)
        self.assertIn("制圧0なので、単独では支援2が無効", logistics_copy)

    def test_supply_courses_teach_total_lane_demand(self) -> None:
        for card_id in (
            "armor_1", "armor_2", "armor_3",
            "artillery_1", "artillery_2", "artillery_3",
        ):
            with self.subTest(card=card_id):
                tutorial = get_tutorial(card_id)
                copy = " ".join(
                    [
                        *(stage.explanation for stage in tutorial.stages),
                        tutorial.stages[-1].question,
                        *tutorial.stages[-1].choices,
                    ]
                )
                self.assertIn("総需要", copy)


if __name__ == "__main__":
    unittest.main()

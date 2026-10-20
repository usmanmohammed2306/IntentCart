import unittest
from dataclasses import replace
from demandweave.clarify import rank_questions
from demandweave.core import solve
from demandweave.demo import fixture


class ClarificationTests(unittest.TestCase):
    def test_question_can_unlock_batch_without_assuming_acceptance(self):
        buyers, offers = fixture()
        buyers = tuple(replace(b, accepted_offers=frozenset(("birch",)))
                       if b.id == "Bea" else b for b in buyers)
        before = solve(buyers, offers, 4)
        questions = rank_questions(buyers, offers, {"Bea": ("recycled",)}, 4)
        self.assertEqual(len(questions), 1)
        q = questions[0]
        self.assertEqual((q.buyer_id, q.offer_id, q.additional_buyers_if_yes), ("Bea", "recycled", 2))
        self.assertEqual(q.change_in_catalog_savings_cents_if_yes, 3000)
        self.assertEqual(before, solve(buyers, offers, 4))
        self.assertNotIn("recycled", buyers[1].accepted_offers)

    def test_never_asks_about_unlisted_or_impossible_substitutions(self):
        buyers, offers = fixture()
        self.assertEqual(rank_questions(buyers, offers, {}, 4), ())
        buyers = tuple(replace(b, max_total_cents=100) for b in buyers)
        self.assertEqual(rank_questions(buyers, offers, {"Chen": ("recycled",)}, 4), ())

    def test_unknown_and_already_accepted_references_rejected(self):
        buyers, offers = fixture()
        for unresolved in ({"unknown": ("birch",)}, {"Chen": ("unknown",)}, {"Ada": ("birch",)}):
            with self.assertRaises(ValueError):
                rank_questions(buyers, offers, unresolved, 4)


if __name__ == "__main__":
    unittest.main()

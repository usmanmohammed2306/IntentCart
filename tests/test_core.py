import itertools
import random
import unittest
from dataclasses import replace
from demandweave.core import Buyer, Offer, Tier, solve
from demandweave.demo import fixture


def independent_assignment_oracle(buyers, offers, capacity):
    """Slow independent assignment enumeration; does not call make_batch."""
    best = (0, 0)
    for assignment in itertools.product(range(-1, len(offers)), repeat=len(buyers)):
        served = sum(a >= 0 for a in assignment)
        if served > capacity:
            continue
        valid, savings = True, 0
        for j, offer in enumerate(offers):
            group = [b for b, a in zip(buyers, assignment) if a == j]
            if not group:
                continue
            prices = [t.total_per_buyer_cents for t in offer.tiers if t.minimum_units <= len(group)]
            if len(group) > offer.capacity or not prices:
                valid = False
                break
            price = min(prices)
            if any(offer.id not in b.accepted_offers or price > b.max_total_cents
                   or offer.delivery_day > b.latest_delivery_day for b in group):
                valid = False
                break
            if len(group) * (price - offer.variable_cost_cents) - offer.setup_cost_cents < offer.minimum_contribution_cents:
                valid = False
                break
            savings += len(group) * (offer.retail_total_cents - price)
        if valid:
            best = max(best, (served, savings))
    return best


class MatchingTests(unittest.TestCase):
    def test_flexible_buyers_do_not_strand_inflexible_buyers(self):
        buyers, offers = fixture()
        plan = solve(buyers, offers, 4)
        self.assertEqual((plan.served, plan.savings_cents), (4, 6000))
        self.assertEqual({b.offer_id: b.buyer_ids for b in plan.batches},
                         {"birch": ("Chen", "Dia"), "recycled": ("Ada", "Bea")})

    def test_no_viable_batch_is_valid_abstention(self):
        buyers, offers = fixture()
        self.assertEqual(solve(buyers[:1], offers).served, 0)
        self.assertEqual(solve(tuple(replace(b, max_total_cents=100) for b in buyers), offers).served, 0)
        self.assertEqual(solve(tuple(replace(b, latest_delivery_day=1) for b in buyers), offers).served, 0)
        self.assertEqual(solve(buyers, tuple(replace(o, minimum_contribution_cents=100000) for o in offers)).served, 0)

    def test_global_capacity_and_unique_assignment(self):
        buyers, offers = fixture()
        plan = solve(buyers, offers, 3)
        ids = [i for b in plan.batches for i in b.buyer_ids]
        self.assertLessEqual(len(ids), 3)
        self.assertEqual(len(ids), len(set(ids)))

    def test_matches_independent_oracle_on_random_markets(self):
        rng = random.Random(709)
        for _ in range(60):
            offers = tuple(Offer(str(j), "maker", rng.randint(2, 5), rng.randint(1, 5),
                                 3500, rng.randint(500, 1400), rng.randint(0, 800), 200,
                                 (Tier(2, 2200),)) for j in range(3))
            buyers = tuple(Buyer(str(i), frozenset(o.id for o in offers if rng.random() < .6),
                                 rng.choice((1800, 2200, 3000)), rng.randint(1, 6))
                           for i in range(5))
            capacity = rng.randint(1, 5)
            plan = solve(buyers, offers, capacity)
            self.assertEqual((plan.served, plan.savings_cents),
                             independent_assignment_oracle(buyers, offers, capacity))

    def test_volume_discount_and_input_order(self):
        buyers, offers = fixture()
        offers = (replace(offers[0], capacity=4, variable_cost_cents=800,
                          tiers=(Tier(2, 2000), Tier(4, 1200))),)
        buyers = tuple(replace(b, accepted_offers=frozenset(("birch",))) for b in buyers)
        plan = solve(buyers, offers)
        self.assertEqual(plan.batches[0].total_per_buyer_cents, 1200)
        self.assertEqual(plan, solve(tuple(reversed(buyers)), offers))

    def test_invalid_inputs_and_oracle_bounds(self):
        buyers, offers = fixture()
        for bad in (-1, 0, 1.5, True):
            with self.assertRaises(ValueError):
                solve((replace(buyers[0], max_total_cents=bad),), offers)
        with self.assertRaises(ValueError):
            solve((buyers[0], buyers[0]), offers)
        with self.assertRaises(ValueError):
            solve((replace(buyers[0], accepted_offers=frozenset(("invented",))),), offers)
        with self.assertRaises(ValueError):
            solve(buyers, (offers[0], replace(offers[1], merchant_id="another")))
        with self.assertRaises(ValueError):
            solve(tuple(replace(buyers[0], id=str(i)) for i in range(13)), offers)


if __name__ == "__main__":
    unittest.main()

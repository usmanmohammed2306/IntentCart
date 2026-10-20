"""Reproducible synthetic matching benchmark. This does not evaluate AI."""

import argparse
import itertools
import json
import random
import statistics
import time
from .core import Buyer, Offer, Tier, greedy, solve


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markets", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20261007)
    args = parser.parse_args()
    if not 1 <= args.markets <= 10000:
        parser.error("--markets must be between 1 and 10000")
    rng = random.Random(args.seed)
    rows = []
    for index in range(args.markets):
        offers = tuple(Offer(str(j), "synthetic-maker", rng.randint(2, 5), rng.randint(2, 7),
                             3500, rng.randint(500, 1200), rng.randint(100, 800), 300,
                             (Tier(2, 2400), Tier(3, 1900)) if j == 0
                             else (Tier(2, rng.choice((1800, 2200, 2600))),))
                       for j in range(3))
        # The first offer needs capacity >= 3 because it has a three-unit tier.
        from dataclasses import replace
        offers = (replace(offers[0], capacity=max(3, offers[0].capacity)),) + offers[1:]
        buyers = tuple(Buyer(str(i), frozenset(o.id for o in offers if rng.random() < .65),
                             rng.choice((2000, 2500, 3000)), rng.randint(3, 8)) for i in range(8))
        capacity = rng.randint(4, 8)
        start = time.perf_counter()
        exact = solve(buyers, offers, capacity)
        latency = (time.perf_counter() - start) * 1000
        baseline = greedy(buyers, offers, capacity)
        # Offer IDs define the fixed baseline's order. Relabel all references to
        # test each catalog permutation, preserving buyer ordering and economics.
        permutations = []
        for order in itertools.permutations(offers):
            names = {o.id: str(j) for j, o in enumerate(order)}
            relabeled = tuple(replace(o, id=names[o.id]) for o in order)
            re_buyers = tuple(replace(b, accepted_offers=frozenset(names[o] for o in b.accepted_offers))
                              for b in buyers)
            permutations.append(greedy(re_buyers, relabeled, capacity))
        stronger = max(permutations, key=lambda p: (p.served, p.savings_cents))
        rows.append({"market": index, "exact_served": exact.served,
                     "greedy_served": baseline.served, "best_order_greedy_served": stronger.served,
                     "exact_savings_cents": exact.savings_cents,
                     "greedy_savings_cents": baseline.savings_cents,
                     "best_order_greedy_savings_cents": stronger.savings_cents,
                     "exact_latency_ms": latency})
    wins = lambda prefix: sum((r["exact_served"], r["exact_savings_cents"]) >
                             (r[prefix + "_served"], r[prefix + "_savings_cents"]) for r in rows)
    timings = sorted(r["exact_latency_ms"] for r in rows)
    print(json.dumps({"scope": "Synthetic structured markets; not LLM or customer evidence",
                      "seed": args.seed, "markets": args.markets,
                      "mean_buyers_served": {p: statistics.mean(r[p + "_served"] for r in rows)
                                             for p in ("exact", "greedy", "best_order_greedy")},
                      "lexicographic_wins_vs_greedy": wins("greedy"),
                      "lexicographic_wins_vs_best_order_greedy": wins("best_order_greedy"),
                      "exact_latency_ms": {"median": statistics.median(timings),
                                           "p95": timings[max(0, (95 * len(timings) + 99) // 100 - 1)]},
                      "rows": rows}, indent=2))


if __name__ == "__main__":
    main()

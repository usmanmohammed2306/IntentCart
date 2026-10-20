"""A deliberately constructed assignment trap; no LLM or PayPal requests."""

import json
from dataclasses import asdict, replace
from .core import Buyer, Offer, Tier, greedy, solve
from .clarify import rank_questions


def fixture():
    buyers = (
        Buyer("Ada", frozenset(("birch", "recycled")), 2500, 7),
        Buyer("Bea", frozenset(("birch", "recycled")), 2500, 7),
        Buyer("Chen", frozenset(("birch",)), 2500, 7),
        Buyer("Dia", frozenset(("birch",)), 2500, 7),
    )
    offers = (
        Offer("birch", "maker", 2, 5, 3500, 1000, 500, 500, (Tier(2, 2000),)),
        Offer("recycled", "maker", 2, 5, 3000, 800, 400, 500, (Tier(2, 1500),)),
    )
    return buyers, offers


def main():
    buyers, offers = fixture()
    output = {"scope": "Synthetic optimization fixture. No AI inference or payments.",
              "objective": "Maximize buyers served, then catalog savings"}
    for name, policy in (("greedy", greedy), ("exact", solve)):
        plan = policy(buyers, offers, merchant_capacity=4)
        output[name] = {**asdict(plan), "served": plan.served,
                        "savings_cents": plan.savings_cents}
    ambiguous = tuple(replace(b, accepted_offers=frozenset(("birch",)))
                      if b.id == "Bea" else b for b in buyers)
    questions = rank_questions(ambiguous, offers, {"Bea": ("recycled",)}, 4)
    output["clarification"] = {
        "currently_served": solve(ambiguous, offers, 4).served,
        "questions": [asdict(q) for q in questions],
        "scope": "Potential improvement if the buyer says yes. No preferences changed.",
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()

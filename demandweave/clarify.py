"""Rank explicit unresolved substitutions by conditional matching improvement.

This is a deterministic planning component, not an AI acceptance predictor.
An unresolved offer is not allowed into the real plan until the buyer confirms it.
"""

from dataclasses import dataclass, replace
from .core import solve


@dataclass(frozen=True)
class Clarification:
    buyer_id: str
    offer_id: str
    additional_buyers_if_yes: int
    change_in_catalog_savings_cents_if_yes: int


def rank_questions(buyers, offers, unresolved, merchant_capacity=12):
    """Evaluate one positive answer at a time; never update confirmed preferences.

    `unresolved` maps buyer IDs to offer IDs explicitly marked as unanswered by
    that buyer. Explicitly rejected offers must not be listed here. Benefits are
    best-case conditional gains, not probabilities or expected economic returns.
    """
    buyers, offers = tuple(buyers), tuple(offers)
    base = solve(buyers, offers, merchant_capacity)
    known_buyers = {b.id: b for b in buyers}
    known_offers = {o.id for o in offers}
    questions = []
    for buyer_id, offer_ids in unresolved.items():
        if buyer_id not in known_buyers:
            raise ValueError("Unknown buyer in unresolved preferences")
        buyer = known_buyers[buyer_id]
        for offer_id in set(offer_ids):
            if offer_id not in known_offers or offer_id in buyer.accepted_offers:
                raise ValueError("Unresolved offer must be known and not already accepted")
            hypothetical = tuple(replace(b, accepted_offers=b.accepted_offers | frozenset((offer_id,)))
                                 if b.id == buyer_id else b for b in buyers)
            after = solve(hypothetical, offers, merchant_capacity)
            if (after.served, after.savings_cents) > (base.served, base.savings_cents):
                questions.append(Clarification(buyer_id, offer_id, after.served - base.served,
                                               after.savings_cents - base.savings_cents))
    return tuple(sorted(questions, key=lambda q: (-q.additional_buyers_if_yes,
                                                 -q.change_in_catalog_savings_cents_if_yes,
                                                 q.buyer_id, q.offer_id)))

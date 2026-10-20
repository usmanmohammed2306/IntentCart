"""Exact small-instance demand matching. Money is always integer USD cents.

Inputs are confirmed structured preferences, not model guesses. Each buyer
requests one unit. Each offer is one independent production line at one merchant.
The lexicographic objective is buyers served, then savings versus catalog retail.
This deliberately bounded oracle supports at most 12 buyers and 6 offers.
"""

from dataclasses import dataclass
from typing import FrozenSet, Tuple


def positive_integer(value, field):
    if type(value) is not int or value <= 0:
        raise ValueError(field + " must be a positive integer")


@dataclass(frozen=True)
class Buyer:
    id: str
    accepted_offers: FrozenSet[str]
    max_total_cents: int
    latest_delivery_day: int


@dataclass(frozen=True)
class Tier:
    minimum_units: int
    total_per_buyer_cents: int


@dataclass(frozen=True)
class Offer:
    id: str
    merchant_id: str
    capacity: int
    delivery_day: int
    retail_total_cents: int
    variable_cost_cents: int
    setup_cost_cents: int
    minimum_contribution_cents: int
    tiers: Tuple[Tier, ...]


@dataclass(frozen=True)
class Batch:
    offer_id: str
    buyer_ids: Tuple[str, ...]
    total_per_buyer_cents: int
    savings_cents: int
    contribution_cents: int


@dataclass(frozen=True)
class Plan:
    batches: Tuple[Batch, ...]
    unserved: Tuple[str, ...]

    @property
    def served(self):
        return sum(len(b.buyer_ids) for b in self.batches)

    @property
    def savings_cents(self):
        return sum(b.savings_cents for b in self.batches)


def validate(buyers, offers, merchant_capacity):
    if len(buyers) > 12 or len(offers) > 6:
        raise ValueError("Exact oracle limited to 12 buyers and 6 offers")
    positive_integer(merchant_capacity, "merchant_capacity")
    for records in (buyers, offers):
        ids = [r.id for r in records]
        if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError("IDs must be nonempty and unique within each record type")
    if len({o.merchant_id for o in offers}) > 1:
        raise ValueError("This experiment supports one merchant")
    known = {o.id for o in offers}
    for b in buyers:
        positive_integer(b.max_total_cents, "max_total_cents")
        positive_integer(b.latest_delivery_day, "latest_delivery_day")
        if not b.accepted_offers <= known:
            raise ValueError("Buyer references unknown offers")
    for o in offers:
        if not isinstance(o.merchant_id, str) or not o.merchant_id:
            raise ValueError("merchant_id must be nonempty")
        for field in ("capacity", "delivery_day", "retail_total_cents"):
            positive_integer(getattr(o, field), field)
        for field in ("variable_cost_cents", "setup_cost_cents", "minimum_contribution_cents"):
            if type(getattr(o, field)) is not int or getattr(o, field) < 0:
                raise ValueError(field + " must be a nonnegative integer")
        if not o.tiers:
            raise ValueError("Each offer needs a price tier")
        for t in o.tiers:
            positive_integer(t.minimum_units, "minimum_units")
            positive_integer(t.total_per_buyer_cents, "total_per_buyer_cents")
            if t.minimum_units > o.capacity or t.total_per_buyer_cents > o.retail_total_cents:
                raise ValueError("Tier must fit capacity and not exceed catalog retail")


def make_batch(buyers, offer, mask):
    selected = tuple(b for i, b in enumerate(buyers) if mask & (1 << i))
    count = len(selected)
    if not count or count > offer.capacity:
        return None
    eligible_tiers = [t for t in offer.tiers if t.minimum_units <= count]
    if not eligible_tiers:
        return None
    # The merchant declares a volume schedule. Never invent a higher price to
    # rescue a losing batch; a nonviable cheapest applicable tier means no batch.
    price = min(t.total_per_buyer_cents for t in eligible_tiers)
    if any(offer.id not in b.accepted_offers or price > b.max_total_cents
           or offer.delivery_day > b.latest_delivery_day for b in selected):
        return None
    contribution = count * (price - offer.variable_cost_cents) - offer.setup_cost_cents
    if contribution < offer.minimum_contribution_cents:
        return None
    return Batch(offer.id, tuple(b.id for b in selected), price,
                 count * (offer.retail_total_cents - price), contribution)


def solve(buyers, offers, merchant_capacity=12):
    """Enumerate feasible batches and solve disjoint set packing with mask DP.

    States retain the best savings for an assigned-buyer mask. Offers are visited
    once, so an offer cannot exceed capacity by becoming several separate lots.
    Worst-case work is O(offers * 3**buyers); this is an evaluation oracle, not
    evidence of production-scale optimization.
    """
    buyers = tuple(sorted(buyers, key=lambda b: b.id))
    offers = tuple(sorted(offers, key=lambda o: o.id))
    validate(buyers, offers, merchant_capacity)
    states = {0: (0, ())}
    for offer in offers:
        candidates = [(mask, make_batch(buyers, offer, mask))
                      for mask in range(1, 1 << len(buyers))]
        candidates = [(m, b) for m, b in candidates if b is not None]
        updated = dict(states)
        for used, (savings, batches) in states.items():
            for mask, batch in candidates:
                union = used | mask
                if used & mask or bin(union).count("1") > merchant_capacity:
                    continue
                total = savings + batch.savings_cents
                if union not in updated or total > updated[union][0]:
                    updated[union] = (total, batches + (batch,))
        states = updated
    winner = max(states, key=lambda m: (bin(m).count("1"), states[m][0], -m))
    return Plan(states[winner][1], tuple(b.id for i, b in enumerate(buyers)
                                       if not winner & (1 << i)))


def greedy(buyers, offers, merchant_capacity=12):
    """Fixed catalog order, then buyer ID order. An intentionally simple baseline."""
    buyers = tuple(sorted(buyers, key=lambda b: b.id))
    offers = tuple(sorted(offers, key=lambda o: o.id))
    validate(buyers, offers, merchant_capacity)
    remaining = set(range(len(buyers)))
    batches = []
    for o in offers:
        candidates = [i for i in sorted(remaining)
                      if o.id in buyers[i].accepted_offers
                      and o.delivery_day <= buyers[i].latest_delivery_day]
        available = min(o.capacity, merchant_capacity - sum(len(b.buyer_ids) for b in batches))
        # Consider affordable prefixes at each declared tier, choosing the
        # largest feasible group. This baseline respects all core constraints.
        options = []
        for tier in o.tiers:
            indices = [i for i in candidates if buyers[i].max_total_cents >= tier.total_per_buyer_cents]
            for count in range(1, min(available, len(indices)) + 1):
                mask = sum(1 << i for i in indices[:count])
                batch = make_batch(buyers, o, mask)
                if batch:
                    options.append((mask, batch))
        if options:
            mask, batch = max(options, key=lambda p: (len(p[1].buyer_ids), p[1].savings_cents))
            batches.append(batch)
            remaining.difference_update(i for i in remaining.copy() if mask & (1 << i))
    return Plan(tuple(batches), tuple(buyers[i].id for i in sorted(remaining)))

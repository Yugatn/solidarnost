"""Universal-access capped aid planner — NO money movement and NO identity checking.

All amounts are integer USD CENTS (never RUB kopeks or float); fund policy
remains 60% children, 35% other needy, 5% project. Cap must be explicitly
supplied by an approved policy: user wording "$2000 thousand" is ambiguous.
Donations are never required from aid applicants.

Production requirements outside this module: independently verified unique
subject IDs, trusted historical payouts across ALL accounts, human case
review, transactionally reserved balance, FX controls, immutable audit,
licensed payment provider, two independent payout authorizers.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Sequence

from core.allocation import split, commitment

CANONICAL_BASIS_POINTS = {"children": 6000, "other_needy": 3500, "project": 500}
CATEGORIES = ("children", "other_needy")


def _integer_minor(amount: int) -> None:
    if type(amount) is not int or amount < 0:
        raise ValueError("amount must be nonnegative integer USD cents")


@dataclass(frozen=True)
class VerifiedNeedSnapshot:
    """Prepared by trusted server from independently reviewed, attested facts.

    A self-reported field or client JSON is NOT sufficient for production.
    Store only opaque identifier references here.
    """

    case_ref: str
    person_ref: str
    category: str
    need_cents: int
    approved_cents: int
    prior_paid_in_window_cents: int
    human_priority_band: int
    accepts_partial: bool = False
    human_reviewed: bool = False

    def validate(self) -> None:
        if any(type(s) is not str or not s.strip() or len(s) > 128
               for s in (self.case_ref, self.person_ref)):
            raise ValueError("opaque case/person references required")
        if self.category not in CATEGORIES:
            raise ValueError("invalid pool")
        for amount in (self.need_cents, self.approved_cents,
                       self.prior_paid_in_window_cents):
            _integer_minor(amount)
        if not self.need_cents or not self.approved_cents:
            raise ValueError("need and approval must be positive")
        if type(self.human_priority_band) is not int or self.human_priority_band not in (0, 1, 2):
            raise ValueError("invalid human priority band")
        if self.human_reviewed is not True:
            raise ValueError("must be independently human-reviewed")
        if type(self.accepts_partial) is not bool:
            raise ValueError("invalid consent for partial award")


def plan_aid_cycle(
    *,
    confirmed_unrestricted_net_cents: int,
    individual_rolling_cap_cents: int,
    cases: Sequence[VerifiedNeedSnapshot],
    cycle_ref: str,
    random_seed: str,
    prepublished_seed_commitment: str,
) -> dict:
    """Simulate a draft cycle, never execute a payment.

    Cap is applied to the PERSON across cases/categories in a 12-month
    rolling window, NOT per application. Caller must supply trustworthy
    historical payouts, verified person linkage, and currency/FX data.
    """
    _integer_minor(confirmed_unrestricted_net_cents)
    _integer_minor(individual_rolling_cap_cents)
    if individual_rolling_cap_cents == 0:
        raise ValueError("a positive approved individual cap is mandatory")
    if type(cycle_ref) is not str or not cycle_ref.strip() or len(cycle_ref) > 128:
        raise ValueError("cycle_ref must be nonempty")
    if commitment(random_seed) != prepublished_seed_commitment:
        raise ValueError("randomness precommitment does not match reveal")

    budgets = split(confirmed_unrestricted_net_cents, CANONICAL_BASIS_POINTS)
    persons, seen_cases = set(), set()
    pools: dict[str, list[VerifiedNeedSnapshot]] = {k: [] for k in CATEGORIES}
    for case in cases:
        case.validate()
        if case.case_ref in seen_cases:
            raise ValueError("duplicate case_ref")
        if case.person_ref in persons:
            # Fail closed until external identity reconciler resolves duplicates.
            raise ValueError("one reviewed person per cycle across all categories")
        seen_cases.add(case.case_ref)
        persons.add(case.person_ref)
        pools[case.category].append(case)

    result_pools = {}
    for category in CATEGORIES:
        remaining = budgets[category]
        grants = []
        def key(case: VerifiedNeedSnapshot) -> tuple:
            tie = sha256(f"{random_seed}:{cycle_ref}:{category}:{case.person_ref}".encode()).hexdigest()
            return case.human_priority_band, tie, case.case_ref

        for case in sorted(pools[category], key=key):
            personal_remaining = max(0, individual_rolling_cap_cents
                                     - case.prior_paid_in_window_cents)
            suggested = min(case.need_cents, case.approved_cents, personal_remaining)
            if suggested == 0:
                continue
            if suggested <= remaining:
                selected = suggested
            elif remaining and case.accepts_partial:
                selected = remaining
            else:
                selected = 0
            if selected:
                grants.append({
                    "case_ref": case.case_ref,
                    "person_ref": case.person_ref,
                    "draft_cents": selected,
                    "human_priority_band": case.human_priority_band,
                })
                remaining -= selected
        result_pools[category] = {
            "budget_cents": budgets[category],
            "draft_awards_cents": budgets[category] - remaining,
            "unallocated_cents": remaining,
            "full_cap_equivalents": budgets[category] // individual_rolling_cap_cents,
            "verified_candidates": len(pools[category]),
            "draft_grants": grants,
        }

    assert sum(budgets.values()) == confirmed_unrestricted_net_cents
    assert all(x["draft_awards_cents"] + x["unallocated_cents"] == x["budget_cents"]
               for x in result_pools.values())
    return {
        "status": "DRAFT_NOT_PAYMENT_AUTHORIZATION",
        "currency": "USD",
        "unit": "cents",
        "cap_basis": "person_per_rolling_12_months",
        "cap_cents": individual_rolling_cap_cents,
        "cycle_ref": cycle_ref,
        "policy": "60/35/5",
        "total_cents": confirmed_unrestricted_net_cents,
        "project_budget_cents": budgets["project"],
        "aid_pools": result_pools,
        "full_cap_equivalents": sum(p["full_cap_equivalents"] for p in result_pools.values()),
    }

"""Solidarnost allocation engine v0.1. Integer kopeks; NO bank transfers."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping, Sequence

# Author-established canonical 60%/35%/5%. No founder share deducted here.
CORE_POLICY = {"children": 6000, "other_needy": 3500, "project": 500}

def _money(amount: int) -> None:
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise ValueError("amount must be a nonnegative integer amount of kopeks")

def split(amount_kopeks: int, basis_points: Mapping[str, int]) -> dict[str, int]:
    """Hamilton allocation. Run on reconciled settlement-cycle total, not micropayments."""
    _money(amount_kopeks)
    if not basis_points or not all(isinstance(k, str) and k for k in basis_points):
        raise ValueError("named nonempty buckets required")
    if any(type(v) is not int or v < 0 for v in basis_points.values()):
        raise ValueError("basis points must be nonnegative integers")
    if sum(basis_points.values()) != 10_000:
        raise ValueError("basis points must total 10000")
    items = list(basis_points.items())  # declaration order is deterministic tie-break
    pieces = [divmod(amount_kopeks * bps, 10_000) for _, bps in items]
    allocated = [whole for whole, _ in pieces]
    gap = amount_kopeks - sum(allocated)
    ranked = sorted(range(len(items)), key=lambda i: (-pieces[i][1], i))
    for i in ranked[:gap]:
        allocated[i] += 1
    assert sum(allocated) == amount_kopeks
    return {name: allocated[i] for i, (name, _) in enumerate(items)}

def core_cycle(amount_kopeks: int) -> dict[str, int]:
    """Canonical 60/35/5; does not authorize any payment."""
    return split(amount_kopeks, CORE_POLICY)

def project_split_proposal(project_kopeks: int) -> dict[str, int]:
    """NOT APPROVED: proposed 4%/1% of gross, inside the 5% project share."""
    return split(project_kopeks, {"development": 8000, "creator_work": 2000})

@dataclass(frozen=True)
class ReviewedCase:
    """Pseudonymous, human-reviewed case data only. No medical or banking PII."""
    case_id: str
    category: str
    requested_kopeks: int
    approved_cap_kopeks: int
    priority_band: int   # 0 urgent, 1 high, 2 regular; determined by human review
    reviewed: bool = True
    accepts_partial: bool = False

    def validate(self) -> None:
        if not self.case_id or len(self.case_id) > 128:
            raise ValueError("pseudonymous case_id required")
        if self.category not in ("children", "other_needy"):
            raise ValueError("invalid category")
        _money(self.requested_kopeks)
        _money(self.approved_cap_kopeks)
        if not self.requested_kopeks or not self.approved_cap_kopeks:
            raise ValueError("nonzero request/cap required")
        if type(self.priority_band) is not int or self.priority_band not in (0, 1, 2):
            raise ValueError("priority must be human-assigned band 0,1,2")
        if not self.reviewed or type(self.accepts_partial) is not bool:
            raise ValueError("human review required")

def commitment(seed: str) -> str:
    if not seed or len(seed) < 32:
        raise ValueError("strong unpredictable seed required")
    return sha256(seed.encode("utf-8")).hexdigest()

def propose_awards(
    category: str,
    available_kopeks: int,
    reviewed_cases: Sequence[ReviewedCase],
    cycle_id: str,
    seed: str,
    published_commitment: str,
) -> dict:
    """Draft plan only. Publish commitment BEFORE closing candidates, then reveal seed."""
    _money(available_kopeks)
    if category not in ("children", "other_needy") or not cycle_id:
        raise ValueError("invalid cycle/category")
    if commitment(seed) != published_commitment:
        raise ValueError("seed commitment mismatch")
    seen: set[str] = set()
    pool: list[ReviewedCase] = []
    for case in reviewed_cases:
        case.validate()
        if case.case_id in seen:
            raise ValueError("duplicate case_id")
        seen.add(case.case_id)
        if case.category == category:
            pool.append(case)
    def ordering(case: ReviewedCase) -> tuple:
        tie = sha256(f"{seed}:{cycle_id}:{category}:{case.case_id}".encode()).hexdigest()
        return (case.priority_band, tie, case.case_id)
    remaining = available_kopeks
    awards: list[dict] = []
    for case in sorted(pool, key=ordering):
        amount = min(case.requested_kopeks, case.approved_cap_kopeks)
        if amount <= remaining:
            awards.append({"case_id": case.case_id, "amount_kopeks": amount, "priority_band": case.priority_band})
            remaining -= amount
        elif remaining > 0 and case.accepts_partial:
            awards.append({"case_id": case.case_id, "amount_kopeks": remaining, "priority_band": case.priority_band})
            remaining = 0
    return {
        "status": "DRAFT_REQUIRES_INDEPENDENT_APPROVAL",
        "category": category, "cycle_id": cycle_id,
        "budget_kopeks": available_kopeks, "awards": awards,
        "undistributed_kopeks": remaining,
        "randomness_commitment": published_commitment,
        "candidate_count": len(pool),
    }

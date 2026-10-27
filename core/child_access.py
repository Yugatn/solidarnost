"""Child-first access and lawful-representation routing for Solidarnost v0.3.

This is a state-less policy PROTOTYPE, not a legal guardianship decision,
identity verifier, financial authorization or emergency response system.
Never accepts self-declared guardian credentials as trusted evidence.
No money transfer or personal biometric processing exists in this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


AGE_BANDS = frozenset({"under_14", "14_to_17", "unknown"})
REPRESENTATIVE_KINDS = frozenset({
    "GUARDIANSHIP_AUTHORITY",
    "CARE_INSTITUTION",
    "APPOINTED_GUARDIAN",
})


@dataclass(frozen=True)
class ChildRequest:
    """Pseudonymous intake. No document, face, address or bank details required."""

    case_ref: str
    child_ref: str
    age_band: str = "unknown"
    self_initiated: bool = True
    no_available_adult: bool = True
    immediate_protection_concern: bool = False
    representative_may_be_unsafe: bool = False

    def validate(self) -> None:
        for identifier in (self.case_ref, self.child_ref):
            if type(identifier) is not str or not identifier.strip() or len(identifier) > 128:
                raise ValueError("case_ref and child_ref must be nonempty opaque IDs")
        if self.age_band not in AGE_BANDS:
            raise ValueError("unknown age group: do not invent an age")
        for field in (
            self.self_initiated,
            self.no_available_adult,
            self.immediate_protection_concern,
            self.representative_may_be_unsafe,
        ):
            if type(field) is not bool:
                raise ValueError("flags must be genuine booleans")


@dataclass(frozen=True)
class AccessDecision:
    """All child requests are accepted for contact and individual assessment."""

    case_ref: str
    intake_accepted: bool
    pathway: str
    legal_representation_required_for_payout: bool
    direct_payout_authorized: bool
    human_safeguarding_review_required: bool
    child_wishes_must_be_sought: bool


def intake_child(request: ChildRequest) -> AccessDecision:
    """Cannot gate a child's FIRST CONTACT on a parent, guardian or biometrics."""
    request.validate()
    risk = request.immediate_protection_concern or request.representative_may_be_unsafe
    return AccessDecision(
        case_ref=request.case_ref,
        intake_accepted=True,
        pathway=("PROTECTED_INTAKE_SAFEGUARDING_REVIEW" if risk
                 else "ACCEPTED_FOR_INDEPENDENT_SUPPORT_REVIEW"),
        legal_representation_required_for_payout=True,
        direct_payout_authorized=False,
        human_safeguarding_review_required=risk,
        child_wishes_must_be_sought=True,
    )


@dataclass(frozen=True)
class RepresentationClaim:
    kind: str
    representative_ref: str
    proof_ref: str

    def validate(self) -> None:
        if self.kind not in REPRESENTATIVE_KINDS:
            raise ValueError("unknown/unlawful representative category")
        if any(type(x) is not str or not x.strip() or len(x) > 128
               for x in (self.representative_ref, self.proof_ref)):
            raise ValueError("opaque representative and proof references required")


class IndependentAuthorityVerifier(Protocol):
    """Production must validate issuer, mandate, delegated signatory and expiry.

    For CARE_INSTITUTION, the child-placement order and organisation's
    legally established representative powers must also be checked.
    Test doubles are NOT suitable for production use.
    """
    def verify_authority(
        self, *, proof_ref: str, kind: str, representative_ref: str,
        child_ref: str, case_ref: str,
    ) -> bool: ...


@dataclass(frozen=True)
class RepresentationDecision:
    case_ref: str
    status: str
    ready_for_human_financial_review: bool
    direct_payout_authorized: bool
    reasons: tuple[str, ...]


def assess_representation(
    request: ChildRequest,
    claim: RepresentationClaim | None,
    verifier: IndependentAuthorityVerifier,
) -> RepresentationDecision:
    """Only an independent, validated mandate may advance to payout review.

    Not authority for a payment; separate payout_guard.py and licensed PSP
    verification plus atomically enforced server controls are still required.
    """
    request.validate()
    reasons = []
    if request.immediate_protection_concern:
        reasons.append("PROTECTION_REVIEW_REQUIRED")
    if request.representative_may_be_unsafe:
        reasons.append("REPRESENTATIVE_SAFETY_DISPUTED")
    if claim is None:
        reasons.append("LAWFUL_REPRESENTATIVE_NOT_YET_CONFIRMED")
    else:
        claim.validate()
        if claim.representative_ref == request.child_ref:
            reasons.append("SELF_APPOINTED_REPRESENTATIVE_NOT_ALLOWED")
        else:
            try:
                is_verified = verifier.verify_authority(
                    proof_ref=claim.proof_ref,
                    kind=claim.kind,
                    representative_ref=claim.representative_ref,
                    child_ref=request.child_ref,
                    case_ref=request.case_ref,
                )
            except Exception:
                is_verified = False
            if is_verified is not True:
                reasons.append("LEGAL_MANDATE_NOT_INDEPENDENTLY_VERIFIED")
    status = ("REPRESENTATIVE_CONFIRMED_FOR_HUMAN_REVIEW" if not reasons
              else ("PROTECTED_REVIEW_NO_PAYOUT" if request.immediate_protection_concern
                    or request.representative_may_be_unsafe
                    else "AWAIT_LAWFUL_AUTHORITY_NO_PAYOUT"))
    return RepresentationDecision(
        case_ref=request.case_ref,
        status=status,
        ready_for_human_financial_review=(not reasons),
        direct_payout_authorized=False,
        reasons=tuple(reasons),
    )

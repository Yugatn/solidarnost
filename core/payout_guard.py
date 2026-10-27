"""Independent payout authorization POLICY ONLY.

No biometrics, account credentials, payment execution or cryptographic verification.
TrustedProofVerifier MUST be implemented by a separate production-grade,
server-side adapter that verifies external signatures, issuer, audience,
nonce, subject binding, expiry and revocation. Mocks are tests ONLY.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol
import json


@dataclass(frozen=True)
class PayoutIntent:
    payout_id: str
    case_id: str
    cycle_id: str
    policy_version: str
    subject_ref: str
    acting_ref: str
    beneficiary_account_ref: str
    amount_kopeks: int
    category: str
    is_minor: bool = False

    def validate(self) -> None:
        fields = (
            self.payout_id, self.case_id, self.cycle_id,
            self.policy_version, self.subject_ref,
            self.acting_ref, self.beneficiary_account_ref,
        )
        if any(type(x) is not str or not x or len(x) > 128 for x in fields):
            raise ValueError("opaque nonempty identifiers required")
        if type(self.amount_kopeks) is not int or self.amount_kopeks <= 0:
            raise ValueError("positive integer kopeks required")
        if self.category not in {"children", "other_needy"}:
            raise ValueError("invalid benefit category")
        if type(self.is_minor) is not bool:
            raise ValueError("invalid minor flag")
        if self.is_minor and self.acting_ref == self.subject_ref:
            raise ValueError("minor requires verified legal representative")
        if not self.is_minor and self.acting_ref != self.subject_ref:
            raise ValueError("adult proxy payout not implemented: require review")

    def digest(self) -> str:
        """Canonical transaction snapshot: modifying any payment field invalidates proofs."""
        self.validate()
        b = json.dumps(
            {key: getattr(self, key) for key in self.__dataclass_fields__},
            ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return sha256(b"solidarnost-payout-v1\0" + b).hexdigest()


@dataclass(frozen=True)
class Approval:
    reviewer_ref: str
    role: str
    evidence_ref: str
    conflict_of_interest: bool = False


class TrustedProofVerifier(Protocol):
    """Backend ONLY. Checks signed proof / challenge with trusted issuer, not UI booleans."""
    def verify(
        self, evidence_ref: str, *, kind: str, subject_ref: str,
        context_digest: str, now_epoch: int
    ) -> bool: ...


@dataclass(frozen=True)
class GateDecision:
    status: str
    payout_digest: str
    reasons: tuple[str, ...]

    @property
    def preview_eligible(self) -> bool:
        return self.status == "ELIGIBLE_FOR_SERVER_RESERVATION_ONLY"


def check_payout_preview(
    *,
    intent: PayoutIntent,
    case_human_reviewed: bool,
    available_kopeks: int,
    identity_evidence_ref: str,
    account_binding_evidence_ref: str,
    recipient_consent_evidence_ref: str,
    approvals: tuple[Approval, ...],
    verifier: TrustedProofVerifier,
    now_epoch: int,
    guardian_authority_evidence_ref: str = "",
) -> GateDecision:
    """A stateless preview. NOT a financial authorization, API, or proof verifier.

    Real production MUST re-verify proofs, unique challenge/idempotency IDs,
    account binding, budget and approvals inside one atomic server transaction.
    """
    digest = intent.digest()
    if type(available_kopeks) is not int or available_kopeks < 0:
        raise ValueError("invalid server budget")
    if type(now_epoch) is not int or now_epoch < 0:
        raise ValueError("invalid clock")
    reasons: list[str] = []

    if case_human_reviewed is not True:
        reasons.append("CASE_NOT_HUMAN_REVIEWED")
    if available_kopeks < intent.amount_kopeks:
        reasons.append("INSUFFICIENT_BUDGET")

    def require(evidence_ref: str, kind: str, subject_ref: str, context: str) -> None:
        if not evidence_ref or not isinstance(evidence_ref, str):
            reasons.append("MISSING_" + kind.upper())
            return
        try:
            ok = verifier.verify(
                evidence_ref, kind=kind, subject_ref=subject_ref,
                context_digest=context, now_epoch=now_epoch
            )
        except Exception:
            ok = False
        if ok is not True:
            reasons.append("INVALID_" + kind.upper())

    # Identity proof is independent of device unlock, and scoped to subject.
    require(identity_evidence_ref, "identity_proof", intent.subject_ref,
            sha256(("identity:" + intent.subject_ref).encode()).hexdigest())
    # Account ownership / authorized beneficiary verified by BANK / PSP adapter.
    require(account_binding_evidence_ref, "beneficiary_account_binding",
            intent.acting_ref, digest)
    # Consent must explicitly approve THIS exact payout, not just login.
    require(recipient_consent_evidence_ref, "transaction_consent",
            intent.acting_ref, digest)

    if intent.is_minor:
        require(guardian_authority_evidence_ref, "guardian_authority",
                intent.acting_ref,
                sha256((intent.subject_ref + ":" + intent.acting_ref).encode()).hexdigest())

    if len(approvals) != 2:
        reasons.append("TWO_APPROVALS_REQUIRED")
    else:
        roles = {a.role for a in approvals}
        actors = {a.reviewer_ref for a in approvals}
        receipt_refs = {a.evidence_ref for a in approvals}
        if roles != {"case_reviewer", "treasurer"}:
            reasons.append("APPROVAL_ROLES_INVALID")
        if len(actors) != 2 or len(receipt_refs) != 2:
            reasons.append("APPROVERS_NOT_INDEPENDENT")
        if any(a.conflict_of_interest or a.reviewer_ref in
               {intent.subject_ref, intent.acting_ref} for a in approvals):
            reasons.append("CONFLICT_OF_INTEREST")
        for a in approvals:
            require(a.evidence_ref, "transaction_approval_" + a.role,
                    a.reviewer_ref, digest)

    return GateDecision(
        status="ELIGIBLE_FOR_SERVER_RESERVATION_ONLY" if not reasons
               else "BLOCKED_REQUIRES_REVIEW",
        payout_digest=digest,
        reasons=tuple(dict.fromkeys(reasons)),
    )

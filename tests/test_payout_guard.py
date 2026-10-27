"""Mock proof-verifier tests: ONLY policy decisions, no real identities or money."""
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.payout_guard import (
    Approval, PayoutIntent, check_payout_preview,
)

NOW = 1_800_000_000


class FakeTrustedAdapter:
    """A TEST DOUBLE. Never deploy as production evidence verifier."""
    def __init__(self):
        self.accepted = set()

    def add(self, evidence_ref, kind, subject_ref, context_digest, now_epoch=NOW):
        self.accepted.add((evidence_ref, kind, subject_ref, context_digest, now_epoch))

    def verify(self, evidence_ref, *, kind, subject_ref, context_digest, now_epoch):
        return (evidence_ref, kind, subject_ref, context_digest, now_epoch) in self.accepted


def identity_digest(ref):
    return hashlib.sha256(("identity:" + ref).encode()).hexdigest()


def guardianship_digest(subject, actor):
    return hashlib.sha256((subject + ":" + actor).encode()).hexdigest()


def prepared_case(is_minor=False):
    subject = "recipient-1"
    actor = "guardian-1" if is_minor else subject
    intent = PayoutIntent("payment-1", "case-1", "cycle-1", "60-35-5-v1",
                          subject, actor, "bank-ref-1", 15000, "children",
                          is_minor=is_minor)
    verifier = FakeTrustedAdapter()
    digest = intent.digest()
    verifier.add("idv-1", "identity_proof", subject, identity_digest(subject))
    verifier.add("account-1", "beneficiary_account_binding", actor, digest)
    verifier.add("consent-1", "transaction_consent", actor, digest)
    approvals = (
        Approval("human-reviewer-1", "case_reviewer", "approval-1"),
        Approval("human-treasurer-1", "treasurer", "approval-2"),
    )
    for a in approvals:
        verifier.add(a.evidence_ref, "transaction_approval_" + a.role,
                     a.reviewer_ref, digest)
    guardian_evidence = ""
    if is_minor:
        guardian_evidence = "authority-1"
        verifier.add("authority-1", "guardian_authority", actor,
                     guardianship_digest(subject, actor))
    return intent, verifier, approvals, guardian_evidence


def check(*, intent=None, verifier=None, approvals=None, guardian=None,
          reviewed=True, budget=15_000, now=NOW):
    init_intent, init_verifier, init_approvals, init_guardian = prepared_case()
    return check_payout_preview(
        intent=intent or init_intent, verifier=verifier or init_verifier,
        approvals=approvals if approvals is not None else init_approvals,
        guardian_authority_evidence_ref=guardian if guardian is not None else init_guardian,
        case_human_reviewed=reviewed, available_kopeks=budget,
        identity_evidence_ref="idv-1", account_binding_evidence_ref="account-1",
        recipient_consent_evidence_ref="consent-1", now_epoch=now,
    )


class PayoutGuardTests(unittest.TestCase):
    def test_two_independent_roles_with_verified_proofs_preview_only(self):
        i, v, a, g = prepared_case()
        d = check(intent=i, verifier=v, approvals=a, guardian=g)
        self.assertTrue(d.preview_eligible)
        self.assertEqual(d.status, "ELIGIBLE_FOR_SERVER_RESERVATION_ONLY")
        self.assertEqual(d.reasons, ())

    def test_edited_amount_invalidates_old_authorization(self):
        i, v, a, g = prepared_case()
        changed = PayoutIntent(**{**i.__dict__, "amount_kopeks": 10000})
        d = check(intent=changed, verifier=v, approvals=a, guardian=g)
        self.assertFalse(d.preview_eligible)
        self.assertIn("INVALID_TRANSACTION_CONSENT", d.reasons)

    def test_changed_bank_invalidates_old_authorization(self):
        i, v, a, g = prepared_case()
        changed = PayoutIntent(**{**i.__dict__, "beneficiary_account_ref": "attacker"})
        self.assertIn("INVALID_BENEFICIARY_ACCOUNT_BINDING",
                      check(intent=changed, verifier=v, approvals=a, guardian=g).reasons)

    def test_missing_recipient_or_bank_proof_blocks(self):
        i, v, a, g = prepared_case()
        v.accepted = {row for row in v.accepted if row[1] not in
                      ("identity_proof", "beneficiary_account_binding")}
        d = check(intent=i, verifier=v, approvals=a, guardian=g)
        self.assertIn("INVALID_IDENTITY_PROOF", d.reasons)
        self.assertIn("INVALID_BENEFICIARY_ACCOUNT_BINDING", d.reasons)

    def test_old_or_expired_proofs_fail_closed(self):
        i, v, a, g = prepared_case()
        d = check(intent=i, verifier=v, approvals=a, guardian=g, now=NOW + 1)
        self.assertIn("INVALID_TRANSACTION_CONSENT", d.reasons)

    def test_independent_reviewers_required(self):
        i, v, a, g = prepared_case()
        same = (a[0], Approval(a[0].reviewer_ref, "treasurer", a[1].evidence_ref))
        d = check(intent=i, verifier=v, approvals=same, guardian=g)
        self.assertIn("APPROVERS_NOT_INDEPENDENT", d.reasons)

    def test_approver_cannot_be_recipient(self):
        i, v, a, g = prepared_case()
        conflict = (Approval(i.subject_ref, "case_reviewer", "approval-1"), a[1])
        self.assertIn("CONFLICT_OF_INTEREST",
                      check(intent=i, verifier=v, approvals=conflict, guardian=g).reasons)

    def test_same_evidence_cannot_sign_two_roles(self):
        i, v, a, g = prepared_case()
        duplicate = (a[0], Approval(a[1].reviewer_ref, "treasurer", "approval-1"))
        self.assertIn("APPROVERS_NOT_INDEPENDENT",
                      check(intent=i, verifier=v, approvals=duplicate, guardian=g).reasons)

    def test_human_review_and_budget_required(self):
        i, v, a, g = prepared_case()
        d = check(intent=i, verifier=v, approvals=a, guardian=g,
                  reviewed=False, budget=0)
        self.assertIn("CASE_NOT_HUMAN_REVIEWED", d.reasons)
        self.assertIn("INSUFFICIENT_BUDGET", d.reasons)

    def test_minors_need_guardian_authority(self):
        i, v, a, g = prepared_case(is_minor=True)
        self.assertTrue(check(intent=i, verifier=v, approvals=a, guardian=g).preview_eligible)
        self.assertIn("MISSING_GUARDIAN_AUTHORITY",
                      check(intent=i, verifier=v, approvals=a, guardian="").reasons)

    def test_bad_minor_without_representative_rejected(self):
        i, _, _, _ = prepared_case()
        with self.assertRaises(ValueError):
            PayoutIntent(**{**i.__dict__, "is_minor": True}).digest()

    def test_payout_never_executes(self):
        i, v, a, g = prepared_case()
        decision = check(intent=i, verifier=v, approvals=a, guardian=g)
        self.assertFalse(hasattr(decision, "execute"))
        self.assertFalse(hasattr(decision, "transfer"))
        self.assertNotIn("PAID", decision.status)

    def test_invalid_evidence_verifier_error_is_denied(self):
        i, v, a, g = prepared_case()
        class Broken:
            def verify(self, *args, **kwargs):
                raise RuntimeError("provider offline")
        d = check(intent=i, verifier=Broken(), approvals=a, guardian=g)
        self.assertIn("INVALID_IDENTITY_PROOF", d.reasons)


if __name__ == "__main__":
    unittest.main()

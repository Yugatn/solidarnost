"""Policy tests with a deliberately FAKE external authority verifier."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.child_access import (
    ChildRequest, RepresentationClaim, intake_child, assess_representation,
)


class FakeAuthorityVerifier:
    """Fake trusted-source adapter for unit tests; NEVER deploy."""
    def __init__(self):
        self.receipts = set()
    def add(self, proof_ref, kind, representative_ref, child_ref, case_ref):
        self.receipts.add((proof_ref, kind, representative_ref, child_ref, case_ref))
    def verify_authority(self, *, proof_ref, kind, representative_ref, child_ref, case_ref):
        return (proof_ref, kind, representative_ref, child_ref, case_ref) in self.receipts


def request(**changes):
    return ChildRequest(**{**dict(case_ref="case-a", child_ref="child-a"), **changes})


def claim(kind="GUARDIANSHIP_AUTHORITY", representative_ref="official-a",
          proof_ref="issuer-receipt-a"):
    return RepresentationClaim(kind, representative_ref, proof_ref)


def accepted(claim_value=None, req=None, verifier=None):
    r = req or request()
    v = verifier if verifier is not None else FakeAuthorityVerifier()
    return assess_representation(r, claim_value, v)


class UnrepresentedChildrenTests(unittest.TestCase):
    def test_child_without_adult_can_submit_under14(self):
        d = intake_child(request(age_band="under_14"))
        self.assertTrue(d.intake_accepted)
        self.assertTrue(d.child_wishes_must_be_sought)
        self.assertFalse(d.direct_payout_authorized)

    def test_child_14_17_without_biometrics_can_submit(self):
        d = intake_child(request(age_band="14_to_17", no_available_adult=True))
        self.assertTrue(d.intake_accepted)
        self.assertTrue(d.legal_representation_required_for_payout)

    def test_unknown_age_and_no_adult_still_accepted(self):
        self.assertTrue(intake_child(request(age_band="unknown")).intake_accepted)

    def test_case_without_child_initiation_still_accepted(self):
        self.assertTrue(intake_child(request(self_initiated=False)).intake_accepted)

    def test_urgent_or_unsafe_adult_never_auto_routes_to_payment(self):
        for changes in (dict(immediate_protection_concern=True),
                        dict(representative_may_be_unsafe=True)):
            d = intake_child(request(**changes))
            self.assertTrue(d.human_safeguarding_review_required)
            self.assertEqual(d.pathway, "PROTECTED_INTAKE_SAFEGUARDING_REVIEW")
            self.assertFalse(d.direct_payout_authorized)

    def test_no_representative_is_not_a_rejection_of_support(self):
        d = accepted(None)
        self.assertEqual(d.status, "AWAIT_LAWFUL_AUTHORITY_NO_PAYOUT")
        self.assertFalse(d.ready_for_human_financial_review)
        self.assertFalse(d.direct_payout_authorized)

    def test_official_attestation_moves_to_review_not_payment(self):
        r = request()
        c = claim()
        v = FakeAuthorityVerifier()
        v.add(c.proof_ref, c.kind, c.representative_ref, r.child_ref, r.case_ref)
        d = accepted(c, req=r, verifier=v)
        self.assertTrue(d.ready_for_human_financial_review)
        self.assertEqual(d.status, "REPRESENTATIVE_CONFIRMED_FOR_HUMAN_REVIEW")
        self.assertFalse(d.direct_payout_authorized)

    def test_institution_supported_if_official_receipt_checks_placement(self):
        r = request()
        c = claim(kind="CARE_INSTITUTION", representative_ref="official-institution-signatory")
        v = FakeAuthorityVerifier()
        v.add(c.proof_ref, c.kind, c.representative_ref, r.child_ref, r.case_ref)
        self.assertTrue(accepted(c, req=r, verifier=v).ready_for_human_financial_review)

    def test_self_described_volunteer_cannot_become_guardian(self):
        with self.assertRaises(ValueError):
            accepted(claim(kind="VOLUNTEER"))

    def test_bare_unverified_claim_fails_closed(self):
        d = accepted(claim())
        self.assertIn("LEGAL_MANDATE_NOT_INDEPENDENTLY_VERIFIED", d.reasons)

    def test_receipt_for_different_child_fails(self):
        r = request()
        c = claim()
        v = FakeAuthorityVerifier()
        v.add(c.proof_ref, c.kind, c.representative_ref, "other-child", r.case_ref)
        d = accepted(c, req=r, verifier=v)
        self.assertFalse(d.ready_for_human_financial_review)

    def test_receipt_for_different_case_fails(self):
        r = request()
        c = claim()
        v = FakeAuthorityVerifier()
        v.add(c.proof_ref, c.kind, c.representative_ref, r.child_ref, "other-case")
        d = accepted(c, req=r, verifier=v)
        self.assertFalse(d.ready_for_human_financial_review)

    def test_minor_cannot_declare_self_as_own_representative(self):
        c = claim(representative_ref="child-a")
        d = accepted(c)
        self.assertIn("SELF_APPOINTED_REPRESENTATIVE_NOT_ALLOWED", d.reasons)

    def test_documented_rep_still_blocked_if_abuse_reported(self):
        r = request(representative_may_be_unsafe=True)
        c = claim()
        v = FakeAuthorityVerifier()
        v.add(c.proof_ref, c.kind, c.representative_ref, r.child_ref, r.case_ref)
        d = accepted(c, req=r, verifier=v)
        self.assertEqual(d.status, "PROTECTED_REVIEW_NO_PAYOUT")
        self.assertFalse(d.ready_for_human_financial_review)

    def test_immediate_concern_restricts_even_authorized_representative(self):
        r = request(immediate_protection_concern=True)
        c = claim()
        v = FakeAuthorityVerifier()
        v.add(c.proof_ref, c.kind, c.representative_ref, r.child_ref, r.case_ref)
        self.assertFalse(accepted(c, req=r, verifier=v).ready_for_human_financial_review)

    def test_broken_external_source_rejects_proof_not_child(self):
        class Offline:
            def verify_authority(self, **kwargs):
                raise RuntimeError("provider offline")
        d = accepted(claim(), verifier=Offline())
        self.assertFalse(d.ready_for_human_financial_review)
        self.assertFalse(d.direct_payout_authorized)
        self.assertTrue(intake_child(request()).intake_accepted)

    def test_invalid_input_does_not_create_fake_child_case(self):
        with self.assertRaises(ValueError):
            intake_child(request(age_band="99_plus"))
        with self.assertRaises(ValueError):
            intake_child(request(child_ref=""))

if __name__ == "__main__":
    unittest.main()

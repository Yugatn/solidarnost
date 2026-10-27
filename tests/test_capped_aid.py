"""Pure calculation tests. No bank data, no collection, no real identities."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.allocation import commitment
from core.capped_aid import VerifiedNeedSnapshot, plan_aid_cycle

SEED = "test-only-demonstration-of-fixed-commitment-2026-solidarnost"
COMMIT = commitment(SEED)


def preview(amount, cap, cases=(), *, seed=SEED, precommit=COMMIT):
    return plan_aid_cycle(
        confirmed_unrestricted_net_cents=amount,
        individual_rolling_cap_cents=cap,
        cases=cases, cycle_ref="cycle-2026-10", random_seed=seed,
        prepublished_seed_commitment=precommit
    )


def person(ref, category="children", need=200_000, prior=0,
           approved=200_000, priority=1, partial=False, reviewed=True):
    return VerifiedNeedSnapshot(
        case_ref="case-" + ref, person_ref=ref, category=category,
        need_cents=need, approved_cents=approved,
        prior_paid_in_window_cents=prior,
        human_priority_band=priority, accepts_partial=partial,
        human_reviewed=reviewed,
    )


class UniversalCappedPolicyTests(unittest.TestCase):
    def test_1m_one_dollar_donors_are_one_million_dollars(self):
        p = preview(100_000_000, 200_000)  # USD 1m, cap USD 2k
        self.assertEqual(p["aid_pools"]["children"]["budget_cents"], 60_000_000)
        self.assertEqual(p["aid_pools"]["other_needy"]["budget_cents"], 35_000_000)
        self.assertEqual(p["project_budget_cents"], 5_000_000)
        self.assertEqual(p["full_cap_equivalents"], 475)

    def test_1m_one_cent_donors_give_10k_before_fees(self):
        p = preview(1_000_000, 200_000)  # USD 10k
        self.assertEqual(p["full_cap_equivalents"], 4)
        self.assertEqual(p["aid_pools"]["children"]["full_cap_equivalents"], 3)
        self.assertEqual(p["aid_pools"]["other_needy"]["full_cap_equivalents"], 1)

    def test_billion_dollar_capacity_is_475000_at_2000_cap(self):
        p = preview(100_000_000_000, 200_000)
        self.assertEqual(p["full_cap_equivalents"], 475_000)
        self.assertEqual(p["aid_pools"]["children"]["full_cap_equivalents"], 300_000)
        self.assertEqual(p["aid_pools"]["other_needy"]["full_cap_equivalents"], 175_000)

    def test_literal_two_million_cap_is_different(self):
        p = preview(100_000_000_000, 200_000_000)
        self.assertEqual(p["full_cap_equivalents"], 475)

    def test_zero_donation_does_not_disqualify_request(self):
        grant = person("non-donor", need=30_000, approved=30_000)
        p = preview(100_000, 200_000, (grant,))
        self.assertEqual(p["aid_pools"]["children"]["draft_awards_cents"], 30_000)

    def test_approved_need_less_than_ceiling_is_not_inflated(self):
        p = preview(500_000, 200_000, (person("a", need=17_500, approved=17_500),))
        self.assertEqual(p["aid_pools"]["children"]["draft_grants"][0]["draft_cents"], 17_500)

    def test_previous_payment_reduces_rolling_room(self):
        p = preview(500_000, 200_000, (person("a", prior=70_000),))
        self.assertEqual(p["aid_pools"]["children"]["draft_grants"][0]["draft_cents"], 130_000)

    def test_exhausted_personal_cap_gets_no_second_grant(self):
        p = preview(500_000, 200_000, (person("a", prior=200_000),))
        self.assertEqual(p["aid_pools"]["children"]["draft_grants"], [])

    def test_duplicate_subject_through_multiple_categories_rejected(self):
        cases = (person("a", "children"), person("a", "other_needy"))
        with self.assertRaisesRegex(ValueError, "person"):
            preview(500_000, 200_000, cases)

    def test_multiple_entries_by_case_rejected(self):
        with self.assertRaises(ValueError):
            preview(500_000, 200_000, (person("a"), person("a")))

    def test_review_is_mandatory(self):
        with self.assertRaises(ValueError):
            preview(500_000, 200_000, (person("a", reviewed=False),))

    def test_partial_grant_requires_consent(self):
        no = preview(10_000, 200_000, (person("a", need=30_000, approved=30_000),))
        self.assertEqual(no["aid_pools"]["children"]["draft_grants"], [])
        yes = preview(10_000, 200_000,
                      (person("a", need=30_000, approved=30_000, partial=True),))
        self.assertEqual(yes["aid_pools"]["children"]["draft_grants"][0]["draft_cents"], 6_000)

    def test_no_negative_or_fractional_currency(self):
        for a, cap in [(-1, 200_000), (1.5, 200_000), (10, 0),
                       (10, -1), (True, 200_000)]:
            with self.assertRaises(ValueError):
                preview(a, cap)

    def test_anti_tamper_commitment(self):
        with self.assertRaises(ValueError):
            preview(100_000, 200_000, precommit="fake")

    def test_same_cycle_same_seed_determinism(self):
        cases = (person("x", priority=1), person("y", priority=1))
        a = preview(500_000, 200_000, cases)
        b = preview(500_000, 200_000, tuple(reversed(cases)))
        self.assertEqual(a, b)

    def test_budget_conservation_across_many_cents(self):
        for amount in range(0, 1000):
            p = preview(amount, 200_000)
            total = p["project_budget_cents"]
            for q in p["aid_pools"].values():
                self.assertEqual(q["draft_awards_cents"] + q["unallocated_cents"],
                                 q["budget_cents"])
                total += q["budget_cents"]
            self.assertEqual(total, amount)

    def test_no_transfers_or_eligibility_certificate(self):
        p = preview(1000, 200_000)
        self.assertEqual(p["status"], "DRAFT_NOT_PAYMENT_AUTHORIZATION")
        self.assertNotIn("bank_account", p)
        self.assertNotIn("donor_id", p)


if __name__ == "__main__":
    unittest.main()

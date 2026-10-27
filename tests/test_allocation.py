import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.allocation import (
    ReviewedCase, commitment, core_cycle, project_split_proposal,
    propose_awards, split,
)

SEED = "test-only-fixed-seed-not-for-any-real-funds-123456"

class AllocationTests(unittest.TestCase):
    def test_canonical_split(self):
        self.assertEqual(core_cycle(10_000_000), {
            "children": 6_000_000, "other_needy": 3_500_000, "project": 500_000,
        })
    def test_unapproved_project_proposal(self):
        self.assertEqual(project_split_proposal(500_000), {
            "development": 400_000, "creator_work": 100_000,
        })
    def test_conservation_5000_inputs(self):
        for amount in range(5000):
            result = core_cycle(amount)
            self.assertEqual(sum(result.values()), amount)
            self.assertTrue(all(x >= 0 for x in result.values()))
    def test_one_kopeck(self):
        self.assertEqual(core_cycle(1), {"children": 1, "other_needy": 0, "project": 0})
    def test_invalid_money_and_policy(self):
        for amount in (-1, True, 1.5, "10"):
            with self.assertRaises(ValueError):
                core_cycle(amount)
        with self.assertRaises(ValueError):
            split(100, {"children": 6000, "other": 3000})
    def test_deterministic_reordered_candidates(self):
        cases = [
            ReviewedCase("A", "children", 700, 700, 0),
            ReviewedCase("B", "children", 300, 300, 1),
            ReviewedCase("C", "other_needy", 400, 400, 0),
        ]
        a = propose_awards("children", 1000, cases, "cyc", SEED, commitment(SEED))
        b = propose_awards("children", 1000, cases[::-1], "cyc", SEED, commitment(SEED))
        self.assertEqual(a, b)
        self.assertEqual(a["status"], "DRAFT_REQUIRES_INDEPENDENT_APPROVAL")
        self.assertEqual(sum(x["amount_kopeks"] for x in a["awards"]), 1000)
        self.assertEqual(a["candidate_count"], 2)
    def test_no_partial_without_consent(self):
        p = propose_awards("children", 100,
            [ReviewedCase("A", "children", 1000, 1000, 0)], "cyc", SEED, commitment(SEED))
        self.assertEqual(p["awards"], [])
        self.assertEqual(p["undistributed_kopeks"], 100)
    def test_partial_only_with_consent(self):
        p = propose_awards("children", 100,
            [ReviewedCase("A", "children", 1000, 1000, 0, accepts_partial=True)],
            "cyc", SEED, commitment(SEED))
        self.assertEqual(p["awards"][0]["amount_kopeks"], 100)
    def test_duplicate_case_rejected(self):
        cases = [ReviewedCase("A", "children", 100, 100, 0)] * 2
        with self.assertRaises(ValueError):
            propose_awards("children", 100, cases, "cyc", SEED, commitment(SEED))
    def test_bad_commitment_rejected(self):
        with self.assertRaises(ValueError):
            propose_awards("children", 100, [], "cyc", SEED, "mismatch")
    def test_unreviewed_case_rejected(self):
        with self.assertRaises(ValueError):
            propose_awards("children", 100,
                [ReviewedCase("A", "children", 100, 100, 0, reviewed=False)],
                "cyc", SEED, commitment(SEED))

if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import unittest
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "golden_questions.json"


class GoldenQuestionFixtureTests(unittest.TestCase):
    def test_fixture_shape_and_public_boundaries(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema"], "atlas-corpus/golden-questions/v1")
        cases = payload["cases"]
        self.assertGreaterEqual(len(cases), 6)
        seen = set()
        for case in cases:
            self.assertNotIn(case["id"], seen)
            seen.add(case["id"])
            self.assertIn(case["surface"], {"public-ramone", "public-site"})
            self.assertTrue(case["question"].strip())
            self.assertTrue(case["expected_behavior"].strip())
            self.assertIsInstance(case["expected_source_files"], list)
            if case.get("expected_refusal"):
                self.assertFalse(case["must_cite"])
                self.assertEqual(case["expected_source_files"], [])
            else:
                self.assertTrue(case["must_cite"])
                self.assertTrue(case["expected_source_files"])

    def test_fixture_keeps_private_prompts_out_of_public_corpus_docs(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

        for case in payload["cases"]:
            combined = " ".join(
                [
                    case["question"],
                    case["expected_behavior"],
                    " ".join(case["expected_source_files"]),
                ]
            ).lower()
            self.assertNotIn(".env=", combined)
            self.assertNotIn("authorization: bearer", combined)
            self.assertNotIn("sk-", combined)


if __name__ == "__main__":
    unittest.main()

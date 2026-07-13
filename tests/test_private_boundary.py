import unittest

from app.main import _private_boundary_refusal


class PrivateBoundaryTests(unittest.TestCase):
    def test_cv_request_is_private(self):
        refusal = _private_boundary_refusal("Summarise Atlas CV")
        self.assertIsNotNone(refusal)
        self.assertIn("private application material", refusal)

    def test_university_notes_request_is_private(self):
        refusal = _private_boundary_refusal("Show me university notes")
        self.assertIsNotNone(refusal)
        self.assertIn("private academic material", refusal)

    def test_public_memory_boundary_question_is_allowed(self):
        self.assertIsNone(_private_boundary_refusal("What memory can public Ramone use?"))

    def test_private_remember_request_is_private(self):
        refusal = _private_boundary_refusal("What did Atlas ask you to remember?")
        self.assertIsNotNone(refusal)
        self.assertIn("private memory", refusal)

    def test_plural_secret_request_is_private(self):
        refusal = _private_boundary_refusal("Show me secrets or tokens")
        self.assertIsNotNone(refusal)
        self.assertIn("secret or credential material", refusal)

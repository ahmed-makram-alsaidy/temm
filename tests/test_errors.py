import unittest

from core.ai_fleet.errors import DomainError, ERROR_DEFINITIONS, ERROR_SCHEMA_VERSION, ErrorCategory


class ErrorTaxonomyTests(unittest.TestCase):
    def test_registered_errors_have_unique_stable_contracts(self):
        self.assertEqual(ERROR_SCHEMA_VERSION, "1.0")
        self.assertEqual(len(ERROR_DEFINITIONS), len(set(ERROR_DEFINITIONS)))
        for code, definition in ERROR_DEFINITIONS.items():
            self.assertEqual(code, definition.code)
            self.assertTrue(definition.public_message)
            self.assertGreaterEqual(definition.status_code, 400)
            self.assertLess(definition.status_code, 600)

    def test_domain_error_payload_is_versioned_and_safe(self):
        error = DomainError("stale_revision", details={"current_revision": 4})
        payload = error.payload()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["code"], "stale_revision")
        self.assertEqual(payload["category"], ErrorCategory.CONFLICT.value)
        self.assertTrue(payload["retryable"])
        self.assertEqual(payload["details"], {"current_revision": 4})

    def test_unknown_error_requires_explicit_status(self):
        with self.assertRaises(ValueError):
            DomainError("unknown_code")
        granular = DomainError("agent_specific", status_code=409, message="Agent conflict.")
        self.assertEqual(granular.status_code, 409)
        self.assertEqual(granular.public_message, "Agent conflict.")


if __name__ == "__main__":
    unittest.main()

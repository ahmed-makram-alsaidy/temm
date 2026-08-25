import unittest

from core.ai_fleet.storage.models import TaskRun
from core.ai_fleet.telemetry import Measurement, MeasurementSource, estimated, unknown


class MeasurementProvenanceTests(unittest.TestCase):
    def test_estimates_require_method(self):
        with self.assertRaises(ValueError):
            Measurement(10, MeasurementSource.ESTIMATED).validate()
        value = estimated(10, "word_count_multiplier", multiplier=1.35)
        self.assertEqual(value.source, MeasurementSource.ESTIMATED)
        self.assertEqual(value.method, "word_count_multiplier")

    def test_unknown_requires_missing_value(self):
        measurement = unknown()
        self.assertIsNone(measurement.value)
        self.assertEqual(measurement.source, MeasurementSource.UNKNOWN)
        with self.assertRaises(ValueError):
            Measurement(None, MeasurementSource.MEASURED).validate()

    def test_run_serialization_exposes_all_provenance(self):
        run = TaskRun(
            id="telemetry-run",
            prompt="test",
            token_provenance="estimated",
            cost_provenance="unknown",
            quality_provenance="unknown",
            latency_provenance="measured",
            measurement_metadata='{"tokens":{"method":"word_count_multiplier"}}',
        )
        payload = run.to_dict()
        self.assertEqual(payload["token_provenance"], "estimated")
        self.assertEqual(payload["cost_provenance"], "unknown")
        self.assertEqual(payload["quality_provenance"], "unknown")
        self.assertEqual(payload["latency_provenance"], "measured")
        self.assertEqual(payload["measurement_metadata"]["tokens"]["method"], "word_count_multiplier")


if __name__ == "__main__":
    unittest.main()

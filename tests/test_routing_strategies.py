import math
import unittest

from core.ai_fleet.routing_strategies import RoutingStrategyService


class RoutingStrategyTests(unittest.TestCase):
    def setUp(self): self.service = RoutingStrategyService()

    def test_builtin_modes_are_normalized_and_deterministic(self):
        for mode in ["balanced", "economy", "quality", "fast"]:
            first = self.service.resolve(mode)
            second = self.service.resolve(mode)
            self.assertAlmostEqual(sum(first.weights.values()), 1)
            self.assertEqual(first.to_dict(), second.to_dict())
            self.assertEqual(first.version, "1.0")
        self.assertEqual(self.service.resolve("balanced").explanation, "quality 40%, cost 30%, speed 20%, reliability 10%")

    def test_custom_requires_complete_finite_normalized_weights(self):
        valid = self.service.resolve("custom", {"quality": 0.5, "cost": 0.25, "speed": 0.15, "reliability": 0.1})
        self.assertEqual(valid.explanation, "quality 50%, cost 25%, speed 15%, reliability 10%")
        for weights in [{"quality": 1}, {"quality": 0.5, "cost": 0.5, "speed": 0.5, "reliability": 0}, {"quality": math.nan, "cost": 0.5, "speed": 0.25, "reliability": 0.25}, {"quality": -0.1, "cost": 0.5, "speed": 0.3, "reliability": 0.3}]:
            with self.assertRaises(ValueError): self.service.resolve("custom", weights)

    def test_unknown_mode_and_builtin_override_are_rejected(self):
        with self.assertRaises(ValueError): self.service.resolve("magic")
        with self.assertRaises(ValueError): self.service.resolve("balanced", {"quality": 1})


if __name__ == "__main__": unittest.main()

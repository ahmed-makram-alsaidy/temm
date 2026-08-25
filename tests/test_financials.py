import unittest
from datetime import datetime

from core.ai_fleet.services.financials import CostCalculator, SavingsCalculator
from core.ai_fleet.storage.models import ModelPriceRecord


class FinancialCalculationTests(unittest.TestCase):
    def setUp(self):
        self.costs = CostCalculator()
        self.savings = SavingsCalculator()
        self.price = ModelPriceRecord(id="price-1", model_id="model-1", currency="USD", input_per_m=1.5, output_per_m=4.0, cache_per_m=None, reasoning_per_m=None, provenance="verified", effective_from=datetime.utcnow())

    def test_formula_retains_rounding_formula_and_provenance(self):
        result = self.costs.formula({"input_tokens": 1_000, "output_tokens": 500, "cached_tokens": 0, "reasoning_tokens": 0}, self.price, {"input_tokens": "provider_reported", "output_tokens": "provider_reported"})
        self.assertEqual(result.amount, "0.00350000")
        self.assertEqual(result.currency, "USD")
        self.assertEqual(result.provenance, "estimated")
        self.assertEqual(result.formula_version, "token-price-v1")
        self.assertEqual(result.price_record_id, "price-1")

    def test_missing_required_price_dimension_is_unknown(self):
        result = self.costs.formula({"input_tokens": 0, "output_tokens": 0, "cached_tokens": 10, "reasoning_tokens": 0}, self.price, {"cached_tokens": "provider_reported"})
        self.assertIsNone(result.amount)
        self.assertEqual(result.provenance, "unknown")
        self.assertEqual(result.dimensions["reason"], "price_dimension_unavailable")

    def test_provider_reported_cost_requires_receipt(self):
        with self.assertRaises(Exception):
            self.costs.provider_reported("1.00", "USD", "")
        result = self.costs.provider_reported("1.005", "USD", "receipt-1")
        self.assertEqual(result.amount, "1.00500000")
        self.assertEqual(result.provenance, "provider_reported")

    def test_taxonomy_separates_direct_and_estimated_value(self):
        actual = self.costs.formula({"input_tokens": 1_000, "output_tokens": 0}, self.price, {"input_tokens": "estimated"})
        reference = self.costs.formula({"input_tokens": 10_000, "output_tokens": 0}, self.price, {"input_tokens": "estimated"})
        direct = self.savings.compare(actual, reference, "direct_saving")
        avoided = self.savings.compare(actual, reference, "estimated_avoided_cost")
        self.assertIsNone(direct.amount)
        self.assertEqual(direct.provenance, "unknown")
        self.assertEqual(avoided.amount, "0.01350000")
        self.assertEqual(avoided.provenance, "estimated")

    def test_currency_mismatch_remains_unknown(self):
        usd = self.costs.provider_reported("1", "USD", "a")
        eur = self.costs.provider_reported("2", "EUR", "b")
        result = self.savings.compare(usd, eur, "direct_saving")
        self.assertIsNone(result.amount)
        self.assertEqual(result.provenance, "unknown")


if __name__ == "__main__":
    unittest.main()

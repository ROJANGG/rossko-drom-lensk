"""Pricing rules for Avito only (supplier cost, before fees and taxes)."""
import unittest
from decimal import Decimal

from avito_pricing import progressive_price
from update_prices import sale_price


class AvitoPricingTests(unittest.TestCase):
    def test_examples_with_50_ruble_rounding(self):
        expected = {
            1000: 1400,
            2000: 2750,
            3000: 4000,
            5000: 6500,
            10000: 12400,
            20000: 23600,
            30000: 34500,
        }
        for purchase, selling in expected.items():
            with self.subTest(purchase=purchase):
                self.assertEqual(progressive_price(Decimal(purchase)), selling)

    def test_no_downward_price_jumps_at_tier_boundaries(self):
        boundaries = (2000, 5000, 10000, 20000, 30000)
        for b in boundaries:
            with self.subTest(boundary=b):
                lower = progressive_price(Decimal(b) - Decimal("0.01"))
                at = progressive_price(Decimal(b))
                above = progressive_price(Decimal(b) + Decimal("0.01"))
                self.assertLessEqual(lower, at)
                self.assertLessEqual(at, above)
        last = 0
        for cost in range(100, 100001, 73):
            result = progressive_price(cost)
            self.assertGreater(result, cost)
            self.assertGreaterEqual(result, last)
            last = result

    def test_isolated_from_drom_flat_markup(self):
        self.assertEqual(sale_price(Decimal(30000), {"markup_percent": 37, "round_up_to": 50}), 41100)
        self.assertEqual(progressive_price(Decimal(30000)), 34500)

    def test_custom_tiers_and_invalid_configuration(self):
        self.assertEqual(progressive_price(1000, {
            "round_up_to": 100,
            "tiers": [{"up_to": 500, "rate_percent": 20},
                      {"up_to": None, "rate_percent": 10}],
        }), 1200)
        bad_settings = [
            {"tiers": []},
            {"tiers": [{"up_to": 3000, "rate_percent": 37}]},
            {"tiers": [{"up_to": 5000, "rate_percent": 20},
                       {"up_to": 2000, "rate_percent": 10},
                       {"up_to": None, "rate_percent": 5}]},
            {"tiers": [{"up_to": 5000, "rate_percent": 20},
                       {"up_to": None, "rate_percent": 40}]},
            {"round_up_to": 0},
        ]
        for settings in bad_settings:
            with self.subTest(settings=settings):
                with self.assertRaises(ValueError):
                    progressive_price(1000, settings)


if __name__ == "__main__":
    unittest.main()

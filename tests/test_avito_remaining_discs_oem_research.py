"""Offline tests for exact-sku NGN OEM manufacturer-catalog extraction."""
import unittest
from avito_remaining_discs_oem_research import parse_exact_ngn_oems


class ManufacturerEvidenceTests(unittest.TestCase):
    def test_requires_exact_sku_and_vehicle_maker_pair(self):
        html = """<html><h1>NGN 36-1366, Brake disc</h1>
        <div>GD0104</div><div>CTR</div>
        <div>55211-65J00</div><div>SUZUKI</div>
        <div>55211-65J01</div><div>SUZUKI</div>
        <div>55211-65J00</div><div>SUZUKI</div></html>"""
        self.assertEqual(parse_exact_ngn_oems(html, "361366"),
                         [("SUZUKI", "5521165J00"), ("SUZUKI", "5521165J01")])
        self.assertEqual(parse_exact_ngn_oems(html, "361452"), [])
        with self.assertRaises(ValueError):
            parse_exact_ngn_oems(html, "INVALID")


if __name__ == "__main__":
    unittest.main()

import unittest
from avito_irkutsk import category, zero_days


class SelectionTests(unittest.TestCase):
    def test_categories(self):
        self.assertEqual(category("Рейка рулевая"), "Рулевые рейки")
        self.assertEqual(category("Диск тормозной"), "Тормозные диски")
        self.assertIsNone(category("Тормозные колодки"))
        self.assertIsNone(category("Рулевая тяга"))

    def test_local_zero(self):
        self.assertTrue(zero_days("0"))
        self.assertTrue(zero_days("0,0"))
        self.assertFalse(zero_days(""))
        self.assertFalse(zero_days("2"))


if __name__ == "__main__":
    unittest.main()

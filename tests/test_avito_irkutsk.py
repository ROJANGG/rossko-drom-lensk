import unittest
from avito_irkutsk import category, zero_days, select_rows
from openpyxl import Workbook


class SelectionTests(unittest.TestCase):
    def test_categories(self):
        self.assertEqual(category("Рейка рулевая"), "Рулевые рейки")
        self.assertEqual(category("Диск тормозной"), "Тормозные диски")
        self.assertIsNone(category("Тормозные колодки"))
        self.assertIsNone(category("Рулевая тяга"))

    def test_pickup_address_required(self):
        wb = Workbook()
        wb.active.append(["Бренд", "Артикул", "Описание", "Цена, руб.", "Наличие", "Срок поставки, дн."])
        with self.assertRaisesRegex(ValueError, "адрес выдачи"):
            select_rows(wb.active, {"avito": {}})

    def test_local_zero(self):
        self.assertTrue(zero_days("0"))
        self.assertTrue(zero_days("0,0"))
        self.assertFalse(zero_days(""))
        self.assertFalse(zero_days("2"))


if __name__ == "__main__":
    unittest.main()

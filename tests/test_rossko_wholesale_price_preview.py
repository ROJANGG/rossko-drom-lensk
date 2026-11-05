import tempfile, csv, unittest
from decimal import Decimal
from pathlib import Path
from rossko_wholesale_price_preview import allowed_wholesale_row, make_proposal, run

class PreviewTest(unittest.TestCase):
    def good(self):
        return {"status":"confirmed_irkutsk_matching_delivery",
          "supplier_price_comparable":"True","api_warehouse_city_verified":"True",
          "brand":"NGN","article":"361366","category":"brake_discs",
          "supplier_list_price_rub":"6046.65",
          "api_matching_delivery_lowest_rub":"4479",
          "api_irkutsk_stock_ids":"HST111","supplier_delivery_days":"0"}

    def test_price_difference_positive(self):
        row=make_proposal(self.good())
        self.assertTrue(row["drom_price_delta_rub"]<0)
        self.assertTrue(row["avito_price_delta_rub"]<0)
        self.assertEqual(row["publish_permitted"],"NO_REVIEW_ONLY")

    def test_no_price_if_city_not_verified(self):
        row=self.good()
        row["api_warehouse_city_verified"]="False"
        self.assertFalse(allowed_wholesale_row(row))
        self.assertIsNone(make_proposal(row))

    def test_no_price_if_delivery_not_matched(self):
        row=self.good()
        row["status"]="no_verified_irkutsk_matching_delivery"
        self.assertIsNone(make_proposal(row))

    def test_empty_review_writes_headers(self):
        with tempfile.TemporaryDirectory() as dir:
            d=Path(dir)
            src=d/"input.csv"
            with src.open("w",encoding="utf-8",newline="") as fp:
                writer=csv.DictWriter(fp,fieldnames=list(self.good()),delimiter=";")
                writer.writeheader()
                item=self.good()
                item["api_warehouse_city_verified"]="False"
                writer.writerow(item)
            run(src,d/"out")
            with (d/"out"/"WHOLESALE_PRICING_REVIEW_ONLY.csv").open(
              encoding="utf-8-sig",newline="") as fp:
                data=list(csv.DictReader(fp,delimiter=";"))
            self.assertEqual(data,[])

if __name__=="__main__":
    unittest.main()

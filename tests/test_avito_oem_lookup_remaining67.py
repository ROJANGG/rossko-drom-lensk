import unittest
from avito_oem_lookup_remaining67 import (
    manufacturer_url, normalized_oem, pairs_from_manufacturer_html,
)

class MakerOEMEvidenceTests(unittest.TestCase):
    def test_ngn_exact_article_and_original_vehicle_manufacturer_only(self):
        html="""<html><h1>NGN 36-1431, Brake disc heat-resistant</h1>
        <div>Compatibility</div><div>Analogs</div>
        <div>09.7011.11</div><div>BREMBO</div>
        <div>1J0 615 301 D</div><div>VAG</div>
        <div>1J0 615 301 J</div><div>VAG</div>
        <div>Model</div><div>FORD 999999</div></html>"""
        pairs,status=pairs_from_manufacturer_html(html,"NGN","361431")
        self.assertEqual(status,"maker_labeled_cross_references")
        self.assertEqual(pairs,[("VAG","1J0615301D"),("VAG","1J0615301J")])
        self.assertEqual(pairs_from_manufacturer_html(html,"NGN","361430")[1],"article_mismatch")
        self.assertEqual(manufacturer_url("NGN","361431"),"https://ngn-parts.com/36-1431.html")

    def test_marshall_oe_pairs_not_analog_brand(self):
        html="""<html><h1>Brake disc front (M2000400)</h1>
        <div>Артикул: M2000400</div><div>Аналоги: TRW DF4465</div>
        <div>В комплект входит один диск</div>
        <div>FORD 1223663</div><div>FORD 1253729</div>
        <div>Volvo 30666800</div><div>Описание</div>
        <div>Другие товары: TOYOTA 1234567</div></html>"""
        pairs,status=pairs_from_manufacturer_html(html,"Marshall","M2000400")
        self.assertEqual([code for _,code in pairs],["1223663","1253729","30666800"])
        self.assertEqual(pairs_from_manufacturer_html(html,"Marshall","M2000401")[1],"article_mismatch")
        self.assertEqual(manufacturer_url("Marshall","M2000400"),"https://cars.marshall.parts/product/m2000400/")

    def test_never_turn_aftermarket_code_into_original(self):
        self.assertEqual(normalized_oem("361431","361431"),"")
        self.assertEqual(normalized_oem("M2000400","M2000400"),"")
        self.assertEqual(normalized_oem("TRW DF4465","M2000400"),"TRWDF4465")
        # The parser only accepts the above value when paired with an original car brand.
        html="<h1>NGN 36-1239</h1><div>Analogs</div><div>DF4465</div><div>TRW</div><div>Model</div>"
        self.assertEqual(pairs_from_manufacturer_html(html,"NGN","361239")[0],[])

if __name__=="__main__":
    unittest.main()

"""No-network safeguards for new article/photo audit."""
import unittest
from avito_extra100_catalog_audit import analyze_record, classify_condition, image_risk


class Extra100CatalogAuditTests(unittest.TestCase):
    def row(self, brand="CTR", article="GD0031", image="https://imgs.rossko.ru/AB/CD/NSII123/1.jpg", product=True):
        p={"Остаток РОССКО":2, "Цена Авито":5500} if product else None
        return ("ctr|gd0031",brand,article,"NSII123",image,"", "Тормозные диски",p,"")

    def test_manufacturer_confirmed_restored_motorherz_is_blocked(self):
        self.assertEqual(classify_condition("Motorherz","J50031RB"),"RESTORED_NOT_NEW")
        self.assertNotEqual(classify_condition("Motorherz","J50031NW"),"RESTORED_NOT_NEW")
        x=self.row(brand="Motorherz", article="J50031RB")
        result=analyze_record(x,("https://rossko.ru/card/example/","exact_image_present_on_supplier_card"))
        self.assertEqual(result["publication_status"],"BLOCKED_RESTORED_NOT_NEW")

    def test_unverified_supplier_oem_and_weak_image_are_not_approved(self):
        x=analyze_record(self.row(),("https://rossko.ru/card/example/","same_nomenclature_photo_folder"))
        self.assertEqual(x["publication_status"],"NEEDS_DOCUMENTED_ORIGINAL_OEM")
        self.assertFalse(x["verified_original_OEM"])
        wrong=analyze_record(self.row(image="https://imgs.rossko.ru/XX/YY/OTHER/1.jpg"),
                           ("https://rossko.ru/card/example/","no_matching_photos_on_card"))
        self.assertEqual(wrong["publication_status"],"CHECK_PHOTO_SUPPLIER_ARTICLE_LINK")
        self.assertEqual(image_risk("Marshall","M2000583"),"TECHNICAL_DRAWING_ON_CONTACT_SHEET")

    def test_out_of_stock_is_not_ready(self):
        r=analyze_record(self.row(product=False),("https://rossko.ru/card/example/","exact_image_present_on_supplier_card"))
        self.assertEqual(r["publication_status"],"NOT_IN_FRESH_IRKUTSK_STOCK")


if __name__=="__main__":
    unittest.main()

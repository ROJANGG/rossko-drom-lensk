"""No-network guardrails for photo mirroring."""
import unittest
from xml.etree import ElementTree as ET
from PIL import Image
from avito_xml_v3_diagnostic import build_xml, TEST_SKUS
from avito_image_mirror import image_urls_for_pilot, render_jpeg


class PhotoMirrorTests(unittest.TestCase):
    def test_all_four_ids_will_be_mirrored(self):
        rows=[]
        for group,pairs in TEST_SKUS.items():
            for brand,article in pairs:
                rows.append({
                    "Группа":group,"Бренд":brand,"Артикул":article,
                    "Цена ₽":4500, "Остаток":2,
                    "Фото URL":"https://imgs.rossko.ru/AB/CD/NSII0000000000/test.jpg",
                    "Применимость РОССКО":"",
                })
        self.assertEqual(len(image_urls_for_pilot(build_xml(rows))),4)
        with self.assertRaisesRegex(ValueError,"missing IDs"):
            image_urls_for_pilot(build_xml(rows[:2]))

    def test_output_is_valid_jpeg(self):
        data=render_jpeg(Image.new("RGB",(640,480),"white"))
        self.assertTrue(data.startswith(b"\xff\xd8\xff"))
        self.assertGreater(len(data),1000)

if __name__=="__main__":
    unittest.main()

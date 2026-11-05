"""No-network guardrails for photo mirroring."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from PIL import Image
from avito_xml_v3_diagnostic import build_xml, TEST_SKUS
from avito_image_mirror import image_urls_for_pilot, render_jpeg, public_photo_url, write_mirrors_and_rewrite
from avito_feed import stable_id


class PhotoMirrorTests(unittest.TestCase):
    def test_all_fifty_ids_will_be_mirrored(self):
        rows=[]
        for group,pairs in TEST_SKUS.items():
            for brand,article in pairs:
                rows.append({
                    "Группа":group,"Бренд":brand,"Артикул":article,
                    "Цена ₽":4500, "Остаток":2,
                    "Фото URL":"https://imgs.rossko.ru/AB/CD/NSII0000000000/test.jpg",
                    "Применимость РОССКО":"",
                })
        self.assertEqual(len(image_urls_for_pilot(build_xml(rows))), 50)
        # Two locally unavailable items may disappear without inventing SKUs.
        self.assertEqual(len(image_urls_for_pilot(build_xml(rows[:-2]))), 48)
        with self.assertRaisesRegex(ValueError, "too many missing IDs"):
            image_urls_for_pilot(build_xml(rows[:39]))

    def test_exactly_gd0123_uses_alternative_cdn_without_changing_id(self):
        gd0123 = stable_id("Тормозные диски", "CTR", "GD0123")
        gd0109 = stable_id("Тормозные диски", "CTR", "GD0109")
        same_name = "irktest-abcdef012345.jpg"
        a = public_photo_url(gd0123, same_name)
        b = public_photo_url(gd0109, same_name)
        self.assertTrue(a.startswith("https://cdn.jsdelivr.net/gh/ROJANGG/rossko-drom-lensk@avito-irkutsk-feed/avito-images/"))
        self.assertTrue(b.startswith("https://raw.githubusercontent.com/ROJANGG/rossko-drom-lensk/avito-irkutsk-feed/avito-images/"))
        self.assertEqual(a.split("/")[-1], b.split("/")[-1])
        with self.assertRaisesRegex(ValueError, "Unexpected Avito image ID"):
            public_photo_url("untrusted-new-ID", same_name)

    def test_temporary_source_timeout_is_retried_without_changing_id(self):
        photo="https://imgs.rossko.ru/12/34/NSII000/1.jpg"
        source=ET.Element("Ads",{"formatVersion":"3","target":"Avito.ru"})
        ad=ET.SubElement(source,"Ad")
        ET.SubElement(ad,"Id").text="test-1"
        ET.SubElement(ET.SubElement(ad,"Images"),"Image",{"url":photo})
        content=ET.tostring(source)
        image=Image.new("RGB",(640,480),"white")
        with tempfile.TemporaryDirectory() as tmp, \
             patch("avito_image_mirror.image_urls_for_pilot",return_value={"test-1":photo}), \
             patch("avito_image_mirror.public_photo_url",return_value="https://cdn.jsdelivr.net/safe.jpg"), \
             patch("avito_image_mirror.retrieve_image",side_effect=[
                 (None,"ReadTimeout","","",""),
                 (image,"available_unverified","640","480","sampledigest")
             ]) as fetch, \
             patch("avito_image_mirror.time.sleep"):
            output, manifest=write_mirrors_and_rewrite(content,Path(tmp))
            self.assertEqual(fetch.call_count,2)
            self.assertEqual(ET.fromstring(output).findtext("./Ad/Id"),"test-1")
            self.assertEqual(len(list(Path(tmp).glob("*.jpg"))),1)
            self.assertEqual(len(manifest),1)

    def test_three_failed_image_downloads_never_commit_partial_photos(self):
        photo="https://imgs.rossko.ru/12/34/NSII000/1.jpg"
        source=ET.Element("Ads",{"formatVersion":"3"})
        ad=ET.SubElement(source,"Ad")
        ET.SubElement(ad,"Id").text="test-1"
        ET.SubElement(ET.SubElement(ad,"Images"),"Image",{"url":photo})
        with tempfile.TemporaryDirectory() as tmp, \
             patch("avito_image_mirror.image_urls_for_pilot",return_value={"test-1":photo}), \
             patch("avito_image_mirror.retrieve_image",return_value=(None,"ReadTimeout","","","")) as fetch, \
             patch("avito_image_mirror.time.sleep"):
            with self.assertRaisesRegex(ValueError,"after 3 attempts"):
                write_mirrors_and_rewrite(ET.tostring(source),Path(tmp))
            self.assertEqual(fetch.call_count,3)
            self.assertEqual(list(Path(tmp).glob("*.jpg")),[])

    def test_output_is_valid_jpeg(self):
        data=render_jpeg(Image.new("RGB",(640,480),"white"))
        self.assertTrue(data.startswith(b"\xff\xd8\xff"))
        self.assertGreater(len(data),1000)

if __name__=="__main__":
    unittest.main()

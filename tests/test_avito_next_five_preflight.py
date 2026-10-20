"""Offline protections for the next five CTR review-only listings."""
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from avito_feed import stable_id
from avito_next_five_preflight import EXTRA, EXTRA_ARTICLES, GROUP, assemble, read_evidence
from avito_xml_v3_diagnostic import TEST_SKUS, build_xml


def base_xml():
    rows = [{
        "Группа":group,"Бренд":brand,"Артикул":article,"Цена ₽":9000,
        "Остаток":1,"Фото URL":"https://imgs.rossko.ru/12/34/NSII00/1.jpg"
    } for group, group_rows in TEST_SKUS.items() for brand,article in group_rows]
    return build_xml(rows)


def data():
    photos={}
    noms={}
    rows=[]
    for n,article in enumerate(EXTRA_ARTICLES):
        k=("ctr",article.casefold())
        nom=f"NSII{n + 1:08}"
        photos["ctr|"+article.casefold()]=f"https://imgs.rossko.ru/12/34/{nom}/1.jpg"
        noms[k]=nom
        rows.append({"Группа":GROUP,"Бренд":"CTR","Артикул":article,
                     "Остаток РОССКО":2,"Цена Авито":6100+n*50})
    oems={"ctr|"+x.casefold():"12345"+str(i) for i,x in enumerate(EXTRA_ARTICLES)}
    return rows,photos,noms,oems


class NextFiveTests(unittest.TestCase):
    def test_five_new_ids_keep_all_existing_ads(self):
        original=base_xml()
        rows,photos,noms,oems=data()
        output,report=assemble(original,rows,photos,noms,oems,image_check=lambda url:True)
        ids=lambda data:{a.findtext("Id") for a in ET.fromstring(data).findall("Ad")}
        self.assertEqual(len(ids(original)),50)
        self.assertEqual(len(ids(output)),55)
        self.assertTrue(ids(original) <= ids(output))
        self.assertEqual(report["new"],5)
        self.assertEqual(report["total"],55)
        self.assertEqual(len(report["new_prices_rub"]),5)

    def test_checked_55_item_xml_passes_whitelisted_live_guards(self):
        from avito_feed_transition import analyze_transition
        from avito_image_mirror import image_urls_for_pilot
        from avito_next_five_preflight import approved_next_five_ids
        old=base_xml()
        rows,photos,noms,oems=data()
        proposed, _=assemble(old,rows,photos,noms,oems,image_check=lambda url:True)
        allowed=approved_next_five_ids()
        self.assertEqual(len(allowed),5)
        with self.assertRaisesRegex(ValueError,"Unexpected"):
            analyze_transition(old,proposed)
        transition=analyze_transition(old,proposed,approved_extra_ids=allowed)
        self.assertEqual(transition["added"],5)
        self.assertEqual(transition["current_ads"],55)
        self.assertEqual(transition["removed"],0)
        with self.assertRaisesRegex(ValueError,"unexpected|Unexpected|Refusing"):
            image_urls_for_pilot(proposed)
        self.assertEqual(len(image_urls_for_pilot(proposed,extra_ids=allowed)),55)
        self.assertEqual(analyze_transition(proposed,proposed,approved_extra_ids=allowed)["added"],0)

    def test_sixth_unapproved_id_remains_blocked(self):
        from avito_feed_transition import analyze_transition
        from avito_image_mirror import image_urls_for_pilot
        from avito_next_five_preflight import approved_next_five_ids
        old=base_xml()
        rows,photos,noms,oems=data()
        proposed,_=assemble(old,rows,photos,noms,oems)
        other=stable_id("Тормозные диски","CTR","GD9999")
        with self.assertRaisesRegex(ValueError,"Unexpected additional"):
            image_urls_for_pilot(proposed,extra_ids=approved_next_five_ids()|{other})
        with self.assertRaisesRegex(ValueError,"Unexpected additional"):
            analyze_transition(old,proposed,approved_extra_ids=approved_next_five_ids()|{other})

    def test_missing_stock_bad_photo_duplicate_id_fail_closed(self):
        xml=base_xml()
        rows,photos,noms,oems=data()
        with self.assertRaisesRegex(ValueError,"freshly verified"):
            assemble(xml,rows[:-1],photos,noms,oems)
        with self.assertRaisesRegex(ValueError,"image bytes"):
            assemble(xml,rows,photos,noms,oems,image_check=lambda url:False)
        photos["ctr|gd0031"]="https://imgs.rossko.ru/AB/CD/WRONG/1.jpg"
        with self.assertRaisesRegex(ValueError,"Photo filename"):
            assemble(xml,rows,photos,noms,oems)

    def test_evidence_source_must_match_exact_ctr_article(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"evidence.csv"
            head="brand;article;proposed_original_oem;source;verification_status\n"
            def row(a,src=None):
                return ("CTR;"+a+";12345"+a[-2:]+";"+(src or "https://ctr.co.ru/catalog/"+a)
                        +";MANUFACTURER_OEM_CATALOG_REVIEW\n")
            path.write_text(head+"".join(row(a) for a in EXTRA_ARTICLES),encoding="utf-8")
            self.assertEqual(len(read_evidence(path)),5)
            path.write_text(head+"".join(row(a,src="https://ctr.co.ru/catalog/GD9999")
                            if a==EXTRA_ARTICLES[0] else row(a) for a in EXTRA_ARTICLES),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"Wrong supplier"):
                read_evidence(path)


if __name__=="__main__":
    unittest.main()

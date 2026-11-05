import tempfile,unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from avito_bulk66_preflight import assemble,approved_bulk_ids,evidence_map,SKIP
from avito_xml_v3_diagnostic import TEST_SKUS
from avito_expand_canary import CANARY
from avito_next_five_preflight import EXTRA_ARTICLES as A
from avito_second_five_preflight import EXTRA_ARTICLES as B
from avito_third_ten_preflight import EXTRA_ARTICLES as C
from avito_fourth_eleven_preflight import EXTRA_ARTICLES as D
from avito_feed import stable_id
from avito_feed_transition import analyze_transition
from avito_image_mirror import image_urls_for_pilot,public_photo_url

def base():
    root=ET.Element("Ads",{"formatVersion":"3","target":"Avito.ru"})
    original=[(group,brand,article) for group,pairs in TEST_SKUS.items() for brand,article in pairs]
    add=[("Тормозные диски","CTR",article) for brand,article in CANARY]
    add+= [("Тормозные диски","CTR",article) for article in A+B+C+D]
    entries=original+add[:29]
    assert len(entries)==79
    for group,brand,article in entries:
        ad=ET.SubElement(root,"Ad")
        ET.SubElement(ad,"Id").text=stable_id(group,brand,article)
        ET.SubElement(ad,"Price").text="6000"
        ET.SubElement(ad,"OEM").text="123456789"
        ET.SubElement(ET.SubElement(ad,"Images"),"Image",{"url":"https://imgs.rossko.ru/12/34/NSII000/1.jpg"})
    return ET.tostring(root,encoding="utf-8")

def stock():
    product,photos,noms=[],{},{}
    for idx,(k,row) in enumerate((kv for kv in evidence_map().items() if kv[0]!=SKIP)):
        brand,article=row["brand"],row["article"]
        group="Рулевые рейки" if k[0]=="masterkit" else "Тормозные диски"
        nom=f"NSII{idx:08d}"
        product.append({"Группа":group,"Бренд":brand,"Артикул":article,
                        "Цена Авито":5000+idx*50,"Остаток РОССКО":2})
        photos["|".join(k)]=f"https://imgs.rossko.ru/12/34/{nom}/1.jpg"
        noms[k]=nom
    return product,photos,noms

class TestBulk66(unittest.TestCase):
    def test_source_allowlist_is_exact_66_and_excludes_sold_out(self):
        e=evidence_map()
        self.assertEqual(len(e),67)
        self.assertEqual(len(approved_bulk_ids()),66)
        self.assertEqual(e[SKIP]["publication_scope"],"EXCLUDE_NO_CURRENT_ROSSKO_STOCK")
        self.assertEqual(e[("masterkit","77r072")]["verified_original_oem"],"MR554233")
        self.assertEqual(e[("masterkit","77r097")]["verified_original_oem"],"480014BA0A")

    def test_preserves_old_and_adds_66_unique_ids(self):
        old=base()
        product,photos,noms=stock()
        xml,audit=assemble(old,product,photos,noms,evidence_map())
        before={a.findtext("Id") for a in ET.fromstring(old).findall("Ad")}
        newer={a.findtext("Id") for a in ET.fromstring(xml).findall("Ad")}
        self.assertEqual((len(before),len(newer)),(79,145))
        self.assertEqual(newer-before,approved_bulk_ids())
        self.assertEqual(audit["added"],66)
        approved={stable_id("Тормозные диски","CTR",a) for _,a in CANARY}
        approved|={stable_id("Тормозные диски","CTR",a) for a in A+B+C+D}
        approved|=approved_bulk_ids()
        report=analyze_transition(old,xml,approved_extra_ids=approved)
        self.assertEqual((report["added"],report["removed"]),(66,0))
        self.assertEqual(len(image_urls_for_pilot(xml,extra_ids=approved)),145)
        new_id=stable_id("Тормозные диски","NGN","361431")
        self.assertTrue(public_photo_url(new_id,"part.jpg").startswith("https://cdn.jsdelivr.net/"))

    def test_missing_stock_and_wrong_nomenclature_fail(self):
        items,photos,noms=stock()
        with self.assertRaisesRegex(ValueError,"Too many parts unavailable"):
            assemble(base(),items[:-1],photos,noms,evidence_map())
        xml,audit=assemble(base(),items[:-1],photos,noms,evidence_map(),max_missing=1)
        self.assertEqual((audit["added"],audit["total"]),(65,144))
        with self.assertRaisesRegex(ValueError,"Too many parts unavailable"):
            assemble(base(),items[:-3],photos,noms,evidence_map(),max_missing=2)
        bad=dict(photos)
        bad[next(iter(bad))]="https://imgs.rossko.ru/12/34/WRONG/1.jpg"
        with self.assertRaisesRegex(ValueError,"nomenclature"):
            assemble(base(),items,bad,noms,evidence_map())

    def test_unexpected_sixty_seventh_new_id_blocked(self):
        old=base()
        p,photos,noms=stock()
        candidate,_=assemble(old,p,photos,noms,evidence_map())
        ids=approved_bulk_ids()|{stable_id("Тормозные диски","NGN","361999")}
        with self.assertRaisesRegex(ValueError,"Unexpected additional"):
            image_urls_for_pilot(candidate,extra_ids=ids)
        with self.assertRaisesRegex(ValueError,"Unexpected additional"):
            analyze_transition(old,candidate,approved_extra_ids=ids)

if __name__=="__main__":
    unittest.main()

import copy,json,unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from avito_verified_extension_release import validate_manifest,validate_source,make_ad,append_ads,stable_id,load_source_cache
from datetime import datetime,timezone,timedelta
from avito_active_feed_refresh import seller_sku,key,EXTRA_APPROVED_STOCK_CATEGORIES,plan
from decimal import Decimal

MANIFEST=Path(__file__).resolve().parent.parent/'input/avito_verified_extension_evidence.json'
class ExtensionSafety(unittest.TestCase):
    def setUp(self):self.manifest=json.loads(MANIFEST.read_text(encoding='utf-8'))
    def test_only_original_95_and_visually_reviewed_records(self):
        records=validate_manifest(self.manifest)
        self.assertEqual(len(self.manifest['scope_skus']),95)
        for r in records:self.assertEqual(EXTRA_APPROVED_STOCK_CATEGORIES[key(r['brand'],r['article'])],r['category'])
        bad=copy.deepcopy(self.manifest);bad['items'][0]['photo_review']='DIAGRAM'
        with self.assertRaises(ValueError):validate_manifest(bad)
        bad=copy.deepcopy(self.manifest);bad['items'][0]['article']='UNREVIEWED'
        with self.assertRaises(ValueError):validate_manifest(bad)
    def test_reject_reused_photos(self):
        bad=copy.deepcopy(self.manifest);bad['items'][1]['images']=bad['items'][0]['images']
        with self.assertRaises(ValueError):validate_manifest(bad)
    def test_all_new_titles_can_be_refreshed_without_guessing(self):
        for r in self.manifest['items']:
            ad=make_ad(r,1500,{'public_url':'https://example.test/product.jpg'},'Иркутск')
            self.assertEqual(seller_sku(ad),(key(r['brand'],r['article']),r['category']))
            self.assertLessEqual(len(ad.findtext('Title')),50)
            ad.find('Brand').text='wrong brand'
            with self.assertRaises(ValueError):seller_sku(ad)
    def test_kit_price_is_explicitly_per_kit(self):
        for r in self.manifest['items']:
            if r.get('pack_quantity'):
                a=make_ad(r,1550,{'public_url':'https://example.test/product.jpg'},'Иркутск')
                self.assertIn('Комплект: 4 шт. Цена за комплект.',a.findtext('Description'))
    def test_existing_ad_ids_oem_images_and_all_fields_unchanged(self):
        original=b'<Ads formatVersion="3" target="Avito.ru">\n  <Ad><Id>existing</Id><OEM>ORIGINAL</OEM><Price>1234</Price><Images><Image url="https://example.test/old.jpg" /></Images><Custom>preserve</Custom></Ad>\n</Ads>'
        r=self.manifest['items'][0];new=make_ad(r,1500,{'public_url':'https://example.test/new.jpg'},'Иркутск')
        before=ET.fromstring(original).find('Ad');result=ET.fromstring(append_ads(original,[new]))
        self.assertEqual(ET.tostring(before),ET.tostring(result.findall('Ad')[0]))
        self.assertEqual(result.findall('Ad')[1].findtext('Id'),stable_id(r))
        with self.assertRaises(ValueError):append_ads(original,[new,new])
    def test_source_cannot_bind_different_sku_oem_or_photo(self):
        r=copy.deepcopy(next(x for x in self.manifest['items'] if x['source_kind']=='stellox'))
        r['fitment_tokens']=[]
        photo=r['images'][0]['url'];oem=r['oem'];sku=r['article']
        page=f'<h1>STELLOX {sku}</h1><div class="product-oe"><button class="product-usability__item"><span class="body-text2">{oem}</span></button></div><img src="{photo}">'
        self.assertTrue(validate_source(r,page))
        for bad in [page.replace(sku,'DIFFERENT'),page.replace(oem,oem+'999'),page.replace(photo,'https://ru.stellox.com/other.jpg')]:
            with self.assertRaises(ValueError):validate_source(r,bad)
    def test_automaker_fitment_must_use_the_same_original_part_number(self):
        r=next(x for x in self.manifest['items'] if x['article']=='000605SX')
        photo=r['images'][0]['url'];oem=r['oem']
        page=f'<h1>STELLOX 000605SX</h1><div class="product-oe"><button class="product-usability__item"><span class="body-text2">{oem}</span></button></div><img src="{photo}">'
        proof=f'<h1>Shoe Set Parking Brake - Nissan ({oem})</h1><p>TITAN. Armada.</p>'
        self.assertTrue(validate_source(r,page,{r['oe_fitment_page']:proof}))
        for invalid in [proof.replace(oem,'44060-ZE00A999'),proof.replace('Armada','OTHER'),proof.replace('Nissan','OTHER')]:
            with self.assertRaises(ValueError):validate_source(r,page,{r['oe_fitment_page']:invalid})
    def test_stellox_automaker_cache_expires_and_cannot_change_oe_source(self):
        r=next(x for x in self.manifest['items'] if x['article']=='000605SX')
        path=MANIFEST.parent.parent/r['source_cache']['path'];proof=json.loads(path.read_text())
        observed=datetime.fromisoformat(proof['verified_at_utc'])
        load_source_cache(r,now=observed+timedelta(minutes=5))
        with self.assertRaises(ValueError):load_source_cache(r,now=observed+timedelta(hours=3,seconds=1))
        bad=copy.deepcopy(r);bad['oe_fitment_page']='https://parts.nissanusa.com/parts/other'
        with self.assertRaises(ValueError):load_source_cache(bad,now=observed+timedelta(minutes=5))
    def test_stock_refresh_keeps_existing_nonstandard_xml_whitespace(self):
        original='<Ads formatVersion="3"><Ad>\n <Id>keep-me</Id><Brand>Luzar</Brand>\n    <Title>Радиатор кондиционера Luzar LRAC3034 новый</Title><Price>1500</Price><OEM>VALUE</OEM><Images>\n<Image url="https://example.test/original.jpg" /></Images></Ad>\n</Ads>'
        k=key('Luzar','LRAC3034')
        supplier={k:{'Группа':'Радиаторы кондиционера','Остаток РОССКО':1,'Срок поставки':0,'_source_list_price':Decimal('1000')}}
        retail={k:{'supplier_price':Decimal('1000'),'avito_price':1500,'days':0}}
        result,_=plan(original.encode(),supplier,retail,min_ads=1)
        self.assertEqual(ET.tostring(ET.fromstring(original).find('Ad')),ET.tostring(ET.fromstring(result).find('Ad')))
    def test_primary_source_cache_identity_hash_and_three_hour_expiry(self):
        r=next(x for x in self.manifest['items'] if x['source_kind']=='ngk')
        path=MANIFEST.parent.parent/r['source_cache']['path'];proof=json.loads(path.read_text())
        observed=datetime.fromisoformat(proof['verified_at_utc'])
        load_source_cache(r,now=observed+timedelta(minutes=5))
        for bad_time in [observed-timedelta(seconds=1),observed+timedelta(hours=3,seconds=1)]:
            with self.assertRaises(ValueError):load_source_cache(r,now=bad_time)
        bad=copy.deepcopy(r);bad['source_cache']['sha256']='0'*64
        with self.assertRaises(ValueError):load_source_cache(bad,now=observed+timedelta(minutes=5))
if __name__=='__main__':unittest.main()

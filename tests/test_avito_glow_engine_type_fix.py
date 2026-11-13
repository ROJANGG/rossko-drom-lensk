import unittest
from avito_glow_engine_type_fix import fix_xml,ENGINE_TYPE
class EngineSubtypeTests(unittest.TestCase):
    def xml(self,title='Свеча накаливания NGK CZ552 новая',group='Двигатель',extra=''):
        return ('<?xml version="1.0"?><Ads target="Avito.ru" formatVersion="3"><Ad><Id>same-id</Id><SparePartType>'+group+'</SparePartType>'+extra+'<Title>'+title+'</Title><Price>1234</Price><OEM>00123</OEM><Description><![CDATA[<p>Keep exact text</p>]]></Description><Images><Image url="https://example.com/a.jpg" /></Images></Ad></Ads>').encode()
    def test_missing_tag_added_only(self):
        raw=self.xml();new,ids=fix_xml(raw);self.assertEqual(ids,['same-id']);self.assertEqual(new.replace(('<EngineSparePartType>'+ENGINE_TYPE+'</EngineSparePartType>').encode(),b''),raw)
    def test_kit_and_single_same_taxonomy(self):
        for title in ['Свечи накала STARTVOLT GLSP508 новые','Свеча накаливания NGK CZ251 новая']:
            self.assertEqual(len(fix_xml(self.xml(title))[1]),1)
    def test_real_generator_sets_subtype_for_all_reviewed_glow_skus(self):
        import ast,json,hashlib,re
        from pathlib import Path
        from xml.etree import ElementTree as ET
        base=Path(__file__).resolve().parents[1]
        tree=ast.parse((base/'avito_verified_extension_release.py').read_text())
        selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('canon','stable_id','make_ad') or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='TYPES' for t in n.targets)]
        scope={'ET':ET,'hashlib':hashlib,'re':re}
        exec(compile(ast.Module(body=selected,type_ignores=[]),'real_generator','exec'),scope)
        manifest=json.loads((base/'input/avito_verified_extension_evidence.json').read_text())
        for record in manifest['items']:
            ad=scope['make_ad'](record,1500,{'public_url':'https://example.test/photo.jpg'},'Иркутск')
            expected=ENGINE_TYPE if record['category']=='Свечи накала' else None
            self.assertEqual(ad.findtext('EngineSparePartType'),expected)

    def test_existing_correct_is_idempotent(self):
        once,_=fix_xml(self.xml());self.assertEqual(fix_xml(once),(once,[]))
    def test_other_category_unchanged(self):
        raw=self.xml('Радиатор кондиционера новый','Система охлаждения');self.assertEqual(fix_xml(raw),(raw,[]))
    def test_unknown_engine_family_rejected(self):
        with self.assertRaises(ValueError):fix_xml(self.xml('Двигатель в сборе'))
    def test_wrong_or_duplicate_existing_tag_rejected(self):
        for extra in ['<EngineSparePartType>Двигатель в сборе</EngineSparePartType>','<EngineSparePartType>x</EngineSparePartType><EngineSparePartType>x</EngineSparePartType>']:
            with self.assertRaises(ValueError):fix_xml(self.xml(extra=extra))
if __name__=='__main__':unittest.main()

import hashlib
import unittest
from xml.etree import ElementTree as E
from avito_refresh_public_cdn import refresh, CDN, PURGE

class PublicCDNTest(unittest.TestCase):
    def xml(self, count):
        root=E.Element('Ads',formatVersion='3',target='Avito.ru')
        for i in range(count):
            E.SubElement(E.SubElement(root,'Ad'),'Id').text=str(i)
        return E.tostring(root)
    def test_330_exact_bytes_and_purge(self):
        raw=self.xml(411);calls=[]
        def get(url):
            calls.append(url)
            return b'{"status":"finished"}' if url==PURGE else raw
        result=refresh(raw,getter=get,sleeper=lambda _:None)
        self.assertEqual(result['ads'],411)
        self.assertEqual(result['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(calls,[PURGE,CDN])
    def test_old_xml_and_excessive_count_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'different XML'):
            refresh(self.xml(330),getter=lambda u:b'{"status":"finished"}' if u==PURGE else self.xml(245),sleeper=lambda _:None)
        with self.assertRaisesRegex(ValueError,'Unexpected validated'):
            refresh(self.xml(573),getter=lambda _:self.fail('No network for invalid XML'))

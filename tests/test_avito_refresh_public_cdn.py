import hashlib
import unittest
from xml.etree import ElementTree as E
from avito_refresh_public_cdn import refresh, CDN, PURGE, CDNPurgeThrottled

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
        self.assertEqual(calls,[CDN])
    def test_old_xml_and_excessive_count_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'different XML'):
            refresh(self.xml(330),getter=lambda u:b'{"status":"finished"}' if u==PURGE else self.xml(245),sleeper=lambda _:None)
        with self.assertRaisesRegex(ValueError,'Unexpected validated'):
            refresh(self.xml(837),getter=lambda _:self.fail('No network for invalid XML'))

    def test_throttled_path_is_rejected_despite_finished_global_status(self):
        raw=self.xml(564);calls=[]
        def getter(url):
            calls.append(url)
            return b'{"status":"finished","paths":{"file":{"throttled":true,"throttlingReset":2582}}}' if url==PURGE else self.xml(510)
        with self.assertRaises(CDNPurgeThrottled) as error:refresh(raw,getter=getter,sleeper=lambda _:self.fail('No waiting or repeated purge under throttle'))
        self.assertEqual(error.exception.retry_after_seconds,2582);self.assertEqual(calls,[CDN,PURGE])
    def test_accepted_non_throttled_purge_still_requires_exact_bytes(self):
        raw=self.xml(564);calls=[]
        def getter(url):
            calls.append(url)
            if url==PURGE:return b'{"status":"finished","paths":{"file":{"throttled":false}}}'
            return self.xml(510) if len(calls)==1 else raw
        self.assertTrue(refresh(raw,getter=getter,sleeper=lambda _:None)['cdn_exact_bytes_verified']);self.assertEqual(calls,[CDN,PURGE,CDN])

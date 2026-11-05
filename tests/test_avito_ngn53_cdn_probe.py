"""Offline NGN photo CDN release prechecks."""
import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from avito_ngn53_cdn_probe import EXPECTED_PREFIX, select_new_images
from avito_ngn53_preflight import approved_ngn53_ids


class TestNGN53CDN(unittest.TestCase):
    def test_requires_51_to_53_exact_local_jpegs(self):
        pic = Image.new("RGB",(500,500),"white")
        blob=io.BytesIO()
        pic.save(blob,"JPEG",quality=90)
        raw=blob.getvalue()
        self.assertGreater(len(raw),1500)
        digest=hashlib.sha256(raw).hexdigest()[:12]
        ids=sorted(approved_ngn53_ids())
        with tempfile.TemporaryDirectory() as folder:
            d=Path(folder)
            manifest={}
            for identifier in ids[:51]:
                filename=f"{identifier}-{digest}.jpg"
                (d/filename).write_bytes(raw)
                manifest[identifier]={"url":EXPECTED_PREFIX+filename}
            self.assertEqual(len(select_new_images(manifest,d)),51)
            manifest[ids[51]]={"url": "https://bad-host.example/fake.jpg"}
            with self.assertRaisesRegex(ValueError,"Expected 51-53|Untrusted CDN"):
                select_new_images(manifest,d)
            manifest.pop(ids[51])
            manifest.pop(ids[0])
            with self.assertRaisesRegex(ValueError,"Expected 51-53"):
                select_new_images(manifest,d)


if __name__=="__main__":
    unittest.main()

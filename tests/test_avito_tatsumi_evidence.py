import copy
import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from avito_tatsumi_evidence import validate_proof, load_evidence

BASE = Path(__file__).resolve().parents[1]
class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.records = [r for r in json.loads((BASE/'input/avito_verified_extension_evidence.json').read_text())['items'] if r['source_kind']=='tatsumi_rossko']
        self.record = copy.deepcopy(self.records[0])
        self.proof = json.loads((BASE/self.record['source_cache']['path']).read_text())
        self.now = datetime.fromisoformat(self.proof['verified_at_utc'])+timedelta(minutes=1)
    def test_all_nine_exact_sources(self):
        self.assertEqual(len(self.records),9)
        for record in self.records:
            load_evidence(record,BASE,self.now)
    def test_wrong_article(self):
        self.proof['supplier_photo']['article']='THQ9999'
        with self.assertRaises(ValueError): validate_proof(self.record,self.proof,self.now)
    def test_aftermarket_number_not_oes(self):
        self.record['oem']='NGK5605'
        with self.assertRaises(ValueError): validate_proof(self.record,self.proof,self.now)
    def test_different_nomenclature(self):
        self.record['photo_supplier_nomenclature']='NSII0000000000'
        with self.assertRaises(ValueError): validate_proof(self.record,self.proof,self.now)
    def test_stale(self):
        with self.assertRaises(ValueError): validate_proof(self.record,self.proof,self.now+timedelta(hours=3))
    def test_wrong_fitment(self):
        self.proof['manufacturer']['fitment'][0][1]='Other model'
        with self.assertRaises(ValueError): validate_proof(self.record,self.proof,self.now)
    def test_small_or_placeholder_image(self):
        self.proof['supplier_photo']['dimensions']=[100,100]
        with self.assertRaises(ValueError): validate_proof(self.record,self.proof,self.now)
    def test_wrong_photo_hash(self):
        self.proof['supplier_photo']['sha256']='0'*64
        with self.assertRaises(ValueError): validate_proof(self.record,self.proof,self.now)
if __name__=='__main__': unittest.main()

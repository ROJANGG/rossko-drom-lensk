import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from openpyxl import Workbook
from avito_bosch_era_evidence import validate_proof, load_evidence, verify_supplier_bindings, prepare_photo

BASE = Path(__file__).resolve().parent.parent
MANIFEST = BASE/'input/avito_verified_extension_evidence.json'


class BoschEvidenceTests(unittest.TestCase):
    def setUp(self):
        manifest = json.loads(MANIFEST.read_text())
        self.record = next(r for r in manifest['items'] if r['source_kind'] == 'bosch_era')
        self.proof = json.loads((BASE/self.record['source_cache']['path']).read_text())
        self.now = datetime.fromisoformat(self.proof['verified_at_utc']) + timedelta(minutes=5)

    def test_reviewed_primary_facts_and_actual_photo_hash(self):
        load_evidence(self.record, base=BASE, now=self.now)

    def test_stale_or_future_capture_is_rejected(self):
        observed = datetime.fromisoformat(self.proof['verified_at_utc'])
        for now in (observed-timedelta(seconds=1), observed+timedelta(hours=3, seconds=1)):
            with self.assertRaisesRegex(ValueError, 'expired'):
                validate_proof(self.record, self.proof, now)

    def test_other_article_oem_era_row_or_photo_identity_is_rejected(self):
        for field, value in [('article', '0250202142999'), ('oem', 'FAKE'),
                             ('era_reference_article', '886000'),
                             ('photo_supplier_nomenclature', 'NSIN999999')]:
            record = copy.deepcopy(self.record);record[field] = value
            with self.assertRaises(ValueError):
                validate_proof(record, self.proof, self.now)
        record = copy.deepcopy(self.record);record['images'][0]['url'] = 'https://imgs.rossko.ru/wrong/NSIN999999/2.jpg'
        with self.assertRaises(ValueError):
            validate_proof(record, self.proof, self.now)

    def test_changed_source_hash_is_rejected(self):
        record = copy.deepcopy(self.record);record['source_cache']['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            load_evidence(record, base=BASE, now=self.now)

    def test_fresh_workbook_must_bind_the_same_supplier_nomenclature(self):
        book = Workbook();book.active.append(['Бренд', 'Артикул', 'Номенклатура'])
        book.active.append(['Bosch', self.record['article'], self.record['photo_supplier_nomenclature']])
        verify_supplier_bindings(book, [self.record])
        book.active.cell(2,3).value = 'NSIN999999'
        with self.assertRaisesRegex(ValueError, 'no longer matches'):
            verify_supplier_bindings(book, [self.record])
        book.close()

    def test_missing_supplier_identity_is_rejected(self):
        book = Workbook();book.active.append(['Бренд', 'Артикул', 'Номенклатура'])
        with self.assertRaisesRegex(ValueError, 'missing'):
            verify_supplier_bindings(book, [self.record])
        book.close()

    def test_placeholder_size_cannot_be_published(self):
        _, photo = load_evidence(self.record, base=BASE, now=self.now)
        record = copy.deepcopy(self.record);record['images'][0]['height'] = 80
        with tempfile.TemporaryDirectory() as directory:
            with patch('avito_bosch_era_evidence.load_evidence', return_value=(self.proof, photo)):
                with self.assertRaisesRegex(ValueError, 'size/format'):
                    prepare_photo(record, Path(directory), 'test-id', 'https://example.test/')


if __name__ == '__main__':
    unittest.main()

import json,tempfile,unittest
from pathlib import Path
from avito_reviewed_sufix_drive_belts import load_reviewed_sufix_belts
from avito_prepared_belts_release import filter_selection
from avito_reviewed_drive_belts import load_reviewed_belts
from avito_reviewed_lynx_source06 import load_reviewed_lynx
from avito_reviewed_febest_cvj import load_reviewed_febest
B=Path(__file__).resolve().parents[1]
class ExactReleaseSelection(unittest.TestCase):
 def test_only_33_new_keys_selected_and_unknown_or_duplicate_rejected(self):
  sr=load_reviewed_sufix_belts(B/'input/avito_reviewed_sufix_drive_belts.json');fr=load_reviewed_febest(B/'input/avito_reviewed_febest_cvj.json');dr=load_reviewed_belts(B/'input/avito_reviewed_drive_belts_source09.json');lr=load_reviewed_lynx(B/'input/avito_reviewed_lynx_source06.json');rs=sr+fr+dr+lr;p=B/'input/avito_release_selection_20261123.json';self.assertEqual(len(filter_selection(rs,p)),15)
  self.assertEqual({r['article'] for r in filter_selection(rs,p)},{r['article'] for r in sr[353:]+fr[20:]+dr[2:]+lr[12:]})
  with tempfile.TemporaryDirectory() as d:
   q=Path(d)/'q.json';data=json.loads(p.read_text());data['items'][0]['article']='UNKNOWN';q.write_text(json.dumps(data))
   with self.assertRaises(ValueError):filter_selection(rs,q)
   data=json.loads(p.read_text());data['items'].append(data['items'][0]);q.write_text(json.dumps(data))
   with self.assertRaises(ValueError):filter_selection(rs,q)

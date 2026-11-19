import json,tempfile,unittest
from pathlib import Path
from avito_reviewed_sufix_drive_belts import load_reviewed_sufix_belts
from avito_prepared_belts_release import filter_selection
B=Path(__file__).resolve().parents[1]
class ExactReleaseSelection(unittest.TestCase):
 def test_only_33_new_keys_selected_and_unknown_or_duplicate_rejected(self):
  rs=load_reviewed_sufix_belts(B/'input/avito_reviewed_sufix_drive_belts.json');p=B/'input/avito_release_selection_radiators_20261119.json';self.assertEqual(len(filter_selection(rs,p)),49)
  self.assertEqual({r['article'] for r in filter_selection(rs,p)},{r['article'] for r in rs[76:]})
  with tempfile.TemporaryDirectory() as d:
   q=Path(d)/'q.json';data=json.loads(p.read_text());data['items'][0]['article']='UNKNOWN';q.write_text(json.dumps(data))
   with self.assertRaises(ValueError):filter_selection(rs,q)
   data=json.loads(p.read_text());data['items'].append(data['items'][0]);q.write_text(json.dumps(data))
   with self.assertRaises(ValueError):filter_selection(rs,q)

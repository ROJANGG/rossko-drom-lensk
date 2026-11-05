"""Offline checks of one verified supplier XLSX cached ONLY for the current CI run."""
import io,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from openpyxl import Workbook
from avito_irkutsk import load_fresh_price

def valid_workbook():
    wb=Workbook()
    ws=wb.active
    ws.append(["Бренд","Артикул","Наличие","Цена, руб."])
    for i in range(1,2501):
        ws.append(["NGN",str(360000+i),str(i%100),float(i)*1.35])
    buf=io.BytesIO()
    wb.save(buf)
    data=buf.getvalue()
    assert len(data)>10000
    return data

class TestSingleRunSupplierCache(unittest.TestCase):
    def test_one_download_then_same_workbook_within_run(self):
        data=valid_workbook()
        cfg={"rossko":{"price_source":"url","price_url":"https://supplier.example/current.xlsx"}}
        with tempfile.TemporaryDirectory() as td:
            cache=Path(td)/"price_234578.xlsx"
            response=Mock()
            response.content=data
            response.raise_for_status.return_value=None
            with patch.dict(os.environ,{"ROSSKO_RUN_PRICE_CACHE":str(cache)}), \
                 patch("avito_irkutsk.requests.get",return_value=response) as network:
                book=load_fresh_price(cfg,Path(td),2)
                self.assertEqual(book.active["A2"].value,"NGN")
                book.close()
                self.assertTrue(cache.exists())
                self.assertEqual(cache.read_bytes(),data)
                self.assertEqual(network.call_count,1)
                book=load_fresh_price(cfg,Path(td),2)
                self.assertEqual(book.active["B2"].value,"360001")
                book.close()
                self.assertEqual(network.call_count,1)

    def test_stale_cache_fails_closed_without_redownload(self):
        cfg={"rossko":{"price_source":"url","price_url":"https://supplier.example/current.xlsx"}}
        with tempfile.TemporaryDirectory() as td:
            cache=Path(td)/"price_234578.xlsx"
            cache.write_bytes(valid_workbook())
            old=time.time()-7200*2
            os.utime(cache,(old,old))
            with patch.dict(os.environ,{"ROSSKO_RUN_PRICE_CACHE":str(cache)}), \
                 patch("avito_irkutsk.requests.get") as network:
                with self.assertRaisesRegex(ValueError,"Устаревший"):
                    load_fresh_price(cfg,Path(td),2)
                network.assert_not_called()

if __name__=="__main__":
    unittest.main()

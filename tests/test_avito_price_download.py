import io
import unittest
import zipfile
from unittest.mock import Mock

import requests
from openpyxl import Workbook

from avito_irkutsk import download_price_snapshot


def valid_xlsx():
    book = Workbook()
    for i in range(1500):
        book.active.append([i, str(i * 1777)])
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def response(data):
    return Mock(content=data)


class PriceDownloadTests(unittest.TestCase):
    def test_invalid_supplier_page_then_valid_xlsx(self):
        data = valid_xlsx()
        get = Mock(side_effect=[response(b'<html>temporarily unavailable</html>'), response(data)])
        sleep = Mock()
        self.assertEqual(download_price_snapshot('https://supplier.test/file', 15, getter=get, sleeper=sleep), data)
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_persistent_invalid_file_fails_after_three_attempts(self):
        get = Mock(return_value=response(b'PK' + b'x' * 12000))
        with self.assertRaises(zipfile.BadZipFile):
            download_price_snapshot('https://supplier.test/file', 15, getter=get, sleeper=Mock())
        self.assertEqual(get.call_count, 3)

    def test_timeout_can_recover(self):
        data = valid_xlsx()
        get = Mock(side_effect=[requests.exceptions.Timeout(), response(data)])
        self.assertEqual(download_price_snapshot('https://supplier.test/file', 15, getter=get, sleeper=Mock()), data)

    def test_auth_failure_is_not_retried(self):
        denied = response(b'forbidden')
        denied.raise_for_status.side_effect = requests.exceptions.HTTPError(response=Mock(status_code=403))
        get = Mock(return_value=denied)
        with self.assertRaises(requests.exceptions.HTTPError):
            download_price_snapshot('https://supplier.test/file', 15, getter=get, sleeper=Mock())
        get.assert_called_once()

    def test_service_unavailable_can_recover(self):
        unavailable = response(b'service unavailable')
        unavailable.raise_for_status.side_effect = requests.exceptions.HTTPError(response=Mock(status_code=503))
        data = valid_xlsx()
        get = Mock(side_effect=[unavailable, response(data)])
        self.assertEqual(download_price_snapshot('https://supplier.test/file', 15, getter=get, sleeper=Mock()), data)


if __name__ == '__main__':
    unittest.main()

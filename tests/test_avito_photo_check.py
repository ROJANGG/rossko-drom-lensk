import unittest
from unittest.mock import patch
from avito_photo_check import approved_url, verified_image_with_retry


class PhotoSourceTests(unittest.TestCase):
    def test_only_supplier_domain(self):
        self.assertTrue(approved_url("https://imgs.rossko.ru/example/1.jpg"))
        self.assertFalse(approved_url("http://imgs.rossko.ru/1.jpg"))
        self.assertFalse(approved_url("https://imgs.rossko.ru.evil.test/1.jpg"))
        self.assertFalse(approved_url("https://example.com/photo.jpg"))
        self.assertFalse(approved_url("https://imgs.rossko.ru:8080/photo.jpg"))

    def test_retry_one_transient_timeout_and_preserve_decoded_image(self):
        with patch("avito_photo_check.retrieve_image",side_effect=[
             (None,"ReadTimeout","","",""),
             (object(),"available_unverified","640","480","digest")
        ]) as loader, patch("avito_photo_check.time.sleep"):
            self.assertTrue(verified_image_with_retry("https://imgs.rossko.ru/a/1.jpg"))
            self.assertEqual(loader.call_count,2)

    def test_three_failed_tries_never_approve_photo(self):
        with patch("avito_photo_check.retrieve_image",return_value=(None,"ReadTimeout","","","")) as loader, \
             patch("avito_photo_check.time.sleep"):
            self.assertFalse(verified_image_with_retry("https://imgs.rossko.ru/a/1.jpg"))
            self.assertEqual(loader.call_count,3)

    def test_blocked_photo_url_never_retried_or_approved(self):
        with patch("avito_photo_check.retrieve_image",return_value=(None,"blocked_url","","","")) as loader:
            self.assertFalse(verified_image_with_retry("https://evil.example/x.jpg"))
            self.assertEqual(loader.call_count,1)


if __name__ == "__main__":
    unittest.main()

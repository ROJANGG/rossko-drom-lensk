import unittest
from avito_photo_check import approved_url


class PhotoSourceTests(unittest.TestCase):
    def test_only_supplier_domain(self):
        self.assertTrue(approved_url("https://imgs.rossko.ru/example/1.jpg"))
        self.assertFalse(approved_url("http://imgs.rossko.ru/1.jpg"))
        self.assertFalse(approved_url("https://imgs.rossko.ru.evil.test/1.jpg"))
        self.assertFalse(approved_url("https://example.com/photo.jpg"))
        self.assertFalse(approved_url("https://imgs.rossko.ru:8080/photo.jpg"))


if __name__ == "__main__":
    unittest.main()

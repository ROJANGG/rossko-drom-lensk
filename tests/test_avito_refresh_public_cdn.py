import unittest
from unittest.mock import Mock
from avito_refresh_public_cdn import CDN, PURGE, refresh


XML = ('<Ads formatVersion="3">' + '<Ad><Id>test</Id></Ad>' * 150 + '</Ads>').encode()


class PublicCDNTests(unittest.TestCase):
    def test_refreshes_only_exact_feed_and_waits_for_identical_bytes(self):
        getter = Mock(side_effect=[b'{"status":"finished"}', XML.replace(b'test', b'older'), XML])
        result = refresh(XML, getter=getter, sleeper=Mock())
        self.assertTrue(result['cdn_exact_bytes_verified'])
        self.assertEqual([call.args[0] for call in getter.call_args_list], [PURGE, CDN, CDN])

    def test_mismatching_cdn_is_never_reported_as_success(self):
        getter = Mock(side_effect=[b'{"status":"finished"}'] + [XML + b'\n'] * 5)
        with self.assertRaisesRegex(ValueError, 'different XML bytes'):
            refresh(XML, getter=getter, sleeper=Mock())
        self.assertEqual(getter.call_count, 6)

    def test_unaccepted_refresh_request_stops_before_verification(self):
        getter = Mock(return_value=b'{"status":"error"}')
        with self.assertRaisesRegex(ValueError, 'not accepted'):
            refresh(XML, getter=getter, sleeper=Mock())
        getter.assert_called_once_with(PURGE)

    def test_invalid_xml_makes_no_network_requests(self):
        getter = Mock()
        with self.assertRaises(ValueError):
            refresh(b'<Ads formatVersion="3"/>', getter=getter)
        getter.assert_not_called()


if __name__ == '__main__':
    unittest.main()

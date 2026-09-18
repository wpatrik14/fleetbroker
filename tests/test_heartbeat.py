import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from fleetbroker import heartbeat


class TestHeartbeat(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.home = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _log_text(self) -> str:
        log_path = self.home / "log.txt"
        return log_path.read_text() if log_path.exists() else ""

    def test_no_config_is_noop(self):
        with patch("fleetbroker.heartbeat.urllib.request.urlopen") as mock_urlopen:
            result = heartbeat.push(self.home, None)
        mock_urlopen.assert_not_called()
        self.assertIsNone(result)
        self.assertEqual(self._log_text(), "")

    def test_missing_url_is_noop(self):
        with patch("fleetbroker.heartbeat.urllib.request.urlopen") as mock_urlopen:
            result = heartbeat.push(self.home, {"timeout_seconds": 5})
        mock_urlopen.assert_not_called()
        self.assertIsNone(result)

    def test_pushes_status_up_and_msg_as_query_params(self):
        with patch("fleetbroker.heartbeat.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b"OK"
            result = heartbeat.push(
                self.home, {"url": "https://kuma.example.com/api/push/abc123"}, msg="tick ok"
            )
        self.assertTrue(result)
        called_url = mock_urlopen.call_args[0][0]
        self.assertTrue(called_url.startswith("https://kuma.example.com/api/push/abc123?"))
        self.assertIn("status=up", called_url)
        self.assertIn("msg=tick+ok", called_url)

    def test_respects_existing_query_string_in_url(self):
        with patch("fleetbroker.heartbeat.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b"OK"
            heartbeat.push(self.home, {"url": "https://kuma.example.com/api/push/abc?foo=bar"})
        called_url = mock_urlopen.call_args[0][0]
        self.assertTrue(called_url.startswith("https://kuma.example.com/api/push/abc?foo=bar&"))

    def test_uses_configured_timeout(self):
        with patch("fleetbroker.heartbeat.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b"OK"
            heartbeat.push(self.home, {"url": "https://kuma.example.com/x", "timeout_seconds": 30})
        self.assertEqual(mock_urlopen.call_args.kwargs["timeout"], 30)

    def test_default_timeout_is_five_seconds(self):
        with patch("fleetbroker.heartbeat.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b"OK"
            heartbeat.push(self.home, {"url": "https://kuma.example.com/x"})
        self.assertEqual(mock_urlopen.call_args.kwargs["timeout"], 5)

    def test_swallows_network_errors_and_logs(self):
        with patch("fleetbroker.heartbeat.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("connection refused")
            result = heartbeat.push(self.home, {"url": "https://kuma.example.com/x"})
        self.assertFalse(result)
        self.assertIn("heartbeat push failed: ", self._log_text())
        self.assertIn("connection refused", self._log_text())

    def test_swallows_arbitrary_exceptions_not_just_urlerror(self):
        with patch("fleetbroker.heartbeat.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = TimeoutError("timed out")
            result = heartbeat.push(self.home, {"url": "https://kuma.example.com/x"})
        self.assertFalse(result)
        self.assertIn("heartbeat push failed: timed out", self._log_text())

    def test_message_is_truncated_to_200_chars(self):
        with patch("fleetbroker.heartbeat.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b"OK"
            heartbeat.push(self.home, {"url": "https://kuma.example.com/x"}, msg="a" * 500)
        called_url = mock_urlopen.call_args[0][0]
        # urlencode('a'*200) has no special chars, so just check the raw run length.
        msg_param = called_url.split("msg=", 1)[1]
        self.assertEqual(len(msg_param), 200)


if __name__ == "__main__":
    unittest.main()

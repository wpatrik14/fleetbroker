import unittest
from datetime import datetime, timedelta, timezone

from fleetbroker.timeutil import parse_iso_timestamp

from pre311 import pre_311_fromisoformat


class TestParseIsoTimestamp(unittest.TestCase):
    def test_utc_designators_and_offsets_are_equivalent(self):
        expected = datetime(2026, 9, 17, 11, 30, tzinfo=timezone.utc)
        for value in ("2026-09-17T11:30:00Z", "2026-09-17T11:30:00z", "2026-09-17T11:30:00+00:00",
                      "2026-09-17T13:30:00+02:00"):
            with self.subTest(value=value):
                parsed = parse_iso_timestamp(value)
                self.assertEqual(parsed, expected)
                self.assertIsNotNone(parsed.tzinfo)

    def test_offset_is_preserved(self):
        parsed = parse_iso_timestamp("2026-09-17T13:30:00+02:00")
        self.assertEqual(parsed.utcoffset(), timedelta(hours=2))

    def test_fractional_seconds(self):
        for value in ("2026-09-17T11:30:00.123456Z", "2026-09-17T11:30:00.123456+00:00"):
            with self.subTest(value=value):
                parsed = parse_iso_timestamp(value)
                self.assertEqual(parsed, datetime(2026, 9, 17, 11, 30, 0, 123456, tzinfo=timezone.utc))

    def test_naive_input_stays_naive(self):
        parsed = parse_iso_timestamp("2026-09-17T11:30:00")
        self.assertIsNone(parsed.tzinfo)
        self.assertEqual(parsed, datetime(2026, 9, 17, 11, 30))

    def test_invalid_input_still_raises(self):
        for value in ("", "not a timestamp", "Z"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_iso_timestamp(value)

    def test_z_suffix_works_when_fromisoformat_rejects_it(self):
        # Simulates Python < 3.11 on every interpreter.
        with pre_311_fromisoformat():
            parsed = parse_iso_timestamp("2026-09-17T11:30:00.500000Z")
        self.assertEqual(parsed, datetime(2026, 9, 17, 11, 30, 0, 500000, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()

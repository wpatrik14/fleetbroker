import unittest
from datetime import datetime, timedelta, timezone

from fleetbroker.probes.anthropic_usage import _parse_usage
from fleetbroker.probes import ha_quota


class TestParseUsage(unittest.TestCase):
    def test_parses_session_and_week_usage(self):
        raw = {
            "five_hour": {"utilization": 66.0, "resets_at": "2026-09-17T21:00:00+00:00"},
            "seven_day": {"utilization": 42.0, "resets_at": "2026-09-20T08:00:00+00:00"},
        }
        data = _parse_usage(raw)
        self.assertEqual(data["session_usage"], 66.0)
        self.assertEqual(data["week_usage"], 42.0)
        self.assertEqual(data["session_reset"], datetime.fromisoformat("2026-09-17T21:00:00+00:00"))
        self.assertEqual(data["week_reset"], datetime.fromisoformat("2026-09-20T08:00:00+00:00"))
        self.assertIsInstance(data["week_pace"], float)

    def test_missing_sections_do_not_raise(self):
        data = _parse_usage({})
        self.assertIsNone(data["session_usage"])
        self.assertIsNone(data["week_usage"])
        self.assertIsNone(data["session_reset"])
        self.assertIsNone(data["week_reset"])
        self.assertIsNone(data["week_pace"])

    def test_pace_formula_matches_hacs_integration_source(self):
        # A reset exactly now (0 seconds left) means 100% of the week has
        # elapsed; utilization 30% => pace should be 30 - 100 = -70.
        now = datetime.now(timezone.utc)
        raw = {
            "seven_day": {"utilization": 30.0, "resets_at": now.isoformat()},
        }
        data = _parse_usage(raw)
        self.assertAlmostEqual(data["week_pace"], -70.0, delta=0.5)

    def test_reused_policy_functions_are_identical_objects_from_ha_quota(self):
        from fleetbroker.probes import anthropic_usage
        self.assertIs(anthropic_usage.decide, ha_quota.decide)
        self.assertIs(anthropic_usage.prepare_state, ha_quota.prepare_state)
        self.assertIs(anthropic_usage.build_body, ha_quota.build_body)
        self.assertIs(anthropic_usage.default_state, ha_quota.default_state)


if __name__ == "__main__":
    unittest.main()

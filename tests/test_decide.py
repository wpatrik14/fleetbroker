import unittest
from datetime import datetime, timedelta, timezone

from fleetbroker.probes.ha_quota import decide


NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


def data(session_usage=10.0, week_usage=20.0, session_reset=None, week_reset=None, week_pace=None):
    return {
        "session_usage": session_usage,
        "week_usage": week_usage,
        "session_reset": session_reset,
        "week_reset": week_reset,
        "week_pace": week_pace,
    }


class TestDecidePrecedence(unittest.TestCase):
    def test_1_hard_weekly_ceiling_blocks_everything(self):
        d = decide(data(session_usage=0.0, week_usage=85.0), daily_used_pct_derived(0.0), NOW)
        self.assertFalse(d.notify)
        self.assertIn("stop threshold", d.reason)

    def test_1_ceiling_takes_precedence_over_urgency(self):
        # even an imminent, unused reset must not override the hard ceiling
        d = decide(
            data(session_usage=0.0, week_usage=90.0,
                 session_reset=NOW + timedelta(minutes=5)),
            daily_used_pct_derived(0.0), NOW,
        )
        self.assertFalse(d.notify)
        self.assertIn("stop threshold", d.reason)

    def test_2_pace_projection_pullback(self):
        # week_usage 60, pace +10%/day, reset 3 days away -> projects to 90% (>=85)
        d = decide(
            data(week_usage=60.0, week_reset=NOW + timedelta(days=3), week_pace=10.0),
            daily_used_pct_derived(0.0), NOW,
        )
        self.assertFalse(d.notify)
        self.assertIn("pulling back", d.reason)

    def test_2_pullback_does_not_fire_when_reset_is_imminent(self):
        # same pace/usage, but reset inside WEEK_URGENT_MINUTES (120) -> urgency
        # logic should get a chance instead of the pullback
        d = decide(
            data(week_usage=60.0, week_reset=NOW + timedelta(minutes=60), week_pace=10.0),
            daily_used_pct_derived(0.0), NOW,
        )
        self.assertTrue(d.notify)
        self.assertIn("use it before it resets", d.reason)

    def test_3_daily_cap_blocks(self):
        d = decide(data(session_usage=10.0, week_usage=20.0), daily_used_pct_derived(14.0), NOW)
        self.assertFalse(d.notify)
        self.assertIn("daily cap reached", d.reason)

    def test_3_daily_cap_precedes_urgency(self):
        d = decide(
            data(session_usage=10.0, week_usage=20.0, session_reset=NOW + timedelta(minutes=10)),
            daily_used_pct_derived(14.0), NOW,
        )
        self.assertFalse(d.notify)
        self.assertIn("daily cap reached", d.reason)

    def test_4_session_urgency_fires(self):
        d = decide(
            data(session_usage=50.0, session_reset=NOW + timedelta(minutes=20)),
            daily_used_pct_derived(0.0), NOW,
        )
        self.assertTrue(d.notify)
        self.assertIn("session reset in 20min", d.reason)
        self.assertEqual(d.window_minutes, 15)  # round(20) - 5

    def test_4_week_urgency_fires_when_no_session_urgency(self):
        d = decide(
            data(week_usage=50.0, week_reset=NOW + timedelta(minutes=90)),
            daily_used_pct_derived(0.0), NOW,
        )
        self.assertTrue(d.notify)
        self.assertIn("week reset in 90min", d.reason)

    def test_4_soonest_reset_wins_when_both_urgent(self):
        d = decide(
            data(session_usage=50.0, week_usage=50.0,
                 session_reset=NOW + timedelta(minutes=30),
                 week_reset=NOW + timedelta(minutes=10)),
            daily_used_pct_derived(0.0), NOW,
        )
        self.assertTrue(d.notify)
        self.assertIn("week reset in 10min", d.reason)

    def test_4_urgency_window_floors_at_5(self):
        d = decide(
            data(session_usage=0.0, session_reset=NOW + timedelta(minutes=2)),
            daily_used_pct_derived(0.0), NOW,
        )
        self.assertEqual(d.window_minutes, 5)

    def test_4_negative_minutes_quirk_preserved(self):
        # a stale HA sensor can report a reset time already in the past;
        # this must still fire urgency with a floored 5-minute window -
        # observed live, do not "fix" without deliberately choosing to.
        d = decide(
            data(session_usage=0.0, session_reset=NOW - timedelta(seconds=30)),
            daily_used_pct_derived(0.0), NOW,
        )
        self.assertTrue(d.notify)
        self.assertEqual(d.window_minutes, 5)
        self.assertIn("-0min", d.reason)

    def test_5_default_risk_threshold(self):
        d = decide(data(session_usage=70.0), daily_used_pct_derived(0.0), NOW)
        self.assertFalse(d.notify)
        self.assertIn("70% risk threshold", d.reason)

    def test_5_lenient_threshold_when_pace_ahead(self):
        d = decide(data(session_usage=75.0, week_pace=-25.0), daily_used_pct_derived(0.0), NOW)
        self.assertTrue(d.notify)  # 75 < 80 lenient threshold

    def test_5_strict_threshold_when_pace_behind(self):
        d = decide(data(session_usage=60.0, week_pace=15.0), daily_used_pct_derived(0.0), NOW)
        self.assertFalse(d.notify)  # 60 >= 55 strict threshold
        self.assertIn("55% risk threshold", d.reason)

    def test_6_default_green_light(self):
        d = decide(data(session_usage=10.0, week_usage=20.0), daily_used_pct_derived(0.0), NOW)
        self.assertTrue(d.notify)
        self.assertEqual(d.window_minutes, 45)
        self.assertIn("room available", d.reason)

    def test_unknown_reset_sensors_treated_as_far_away(self):
        # session_reset=None / week_reset=None must not raise, must not spuriously
        # trigger urgency (matches "unknown at rollover" sensor behavior)
        d = decide(data(session_usage=10.0, week_usage=20.0, session_reset=None, week_reset=None),
                    daily_used_pct_derived(0.0), NOW)
        self.assertTrue(d.notify)
        self.assertIn("room available", d.reason)


def daily_used_pct_derived(value: float) -> float:
    return value


if __name__ == "__main__":
    unittest.main()

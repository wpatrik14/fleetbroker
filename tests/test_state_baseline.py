import unittest
from datetime import datetime, timezone

from fleetbroker.probes.quota_policy import prepare_state


class TestDailyCapBaseline(unittest.TestCase):
    def test_first_run_ever_sets_baseline_to_current_usage(self):
        state = {"day_start_date": None, "day_start_week_usage": 0.0}
        now = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)
        daily_used = prepare_state(state, {"week_usage": 31.0}, now)
        self.assertEqual(state["day_start_date"], "2026-09-17")
        self.assertEqual(state["day_start_week_usage"], 31.0)
        self.assertEqual(daily_used, 0.0)

    def test_same_day_accumulates_against_existing_baseline(self):
        state = {"day_start_date": "2026-09-17", "day_start_week_usage": 31.0}
        now = datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc)
        daily_used = prepare_state(state, {"week_usage": 37.0}, now)
        self.assertEqual(state["day_start_week_usage"], 31.0)  # untouched
        self.assertEqual(daily_used, 6.0)

    def test_plain_calendar_rollover_carries_cumulative_total_forward(self):
        state = {"day_start_date": "2026-09-16", "day_start_week_usage": 20.0}
        now = datetime(2026, 9, 17, 0, 5, tzinfo=timezone.utc)
        daily_used = prepare_state(state, {"week_usage": 45.0}, now)  # no reset, just a new day
        self.assertEqual(state["day_start_date"], "2026-09-17")
        self.assertEqual(state["day_start_week_usage"], 45.0)  # carried forward, not zeroed
        self.assertEqual(daily_used, 0.0)

    def test_weekly_reset_snaps_baseline_to_zero_not_observed_reading(self):
        # week_usage dropping below the stored baseline signals a real weekly
        # reset. Even if usage already happened before we noticed (e.g. cron
        # was down across the reset moment), the baseline must snap to exactly
        # 0.0, not to whatever week_usage we happen to observe first - this is
        # the exact bug found and fixed in production on 2026-09-06.
        state = {"day_start_date": "2026-09-06", "day_start_week_usage": 85.0}
        now = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
        daily_used = prepare_state(state, {"week_usage": 5.0}, now)  # reset already happened, 5% used since
        self.assertEqual(state["day_start_week_usage"], 0.0)  # NOT 5.0
        self.assertEqual(daily_used, 5.0)  # the 5% counts fully against today's cap

    def test_weekly_reset_wins_over_calendar_rollover_when_both_true(self):
        # a reset landing exactly at a day boundary must still zero-snap,
        # not just carry-forward as a plain rollover would.
        state = {"day_start_date": "2026-09-06", "day_start_week_usage": 85.0}
        now = datetime(2026, 9, 7, 0, 1, tzinfo=timezone.utc)
        daily_used = prepare_state(state, {"week_usage": 2.0}, now)
        self.assertEqual(state["day_start_date"], "2026-09-07")
        self.assertEqual(state["day_start_week_usage"], 0.0)
        self.assertEqual(daily_used, 2.0)


if __name__ == "__main__":
    unittest.main()

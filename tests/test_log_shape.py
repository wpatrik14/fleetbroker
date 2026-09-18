"""Golden-case regression test for the default green-light branch: a fixed
decide() input/output pair, pinned so a future change to the reason-string
shape can't drift silently. Precedence-chain coverage for every other branch
lives in test_decide.py; this file exists only to lock the exact wording of
the log line an operator would actually see.
"""

import unittest
from datetime import datetime, timezone

from fleetbroker.probes.ha_quota import decide


class TestGoldenReplay(unittest.TestCase):
    def test_default_green_light_reason_shape(self):
        now = datetime.fromisoformat("2026-01-01T13:00:00+00:00")
        data = {
            "session_usage": 25.0,
            "week_usage": 35.0,
            "session_reset": None,
            "week_reset": None,
            "week_pace": -25.1,
        }
        d = decide(data, 4.0, now)
        self.assertTrue(d.notify)
        self.assertEqual(d.window_minutes, 45)
        self.assertEqual(
            d.reason,
            "room available: session 25.0%, week 35.0% (pace=-25.1), no urgent reset",
        )


if __name__ == "__main__":
    unittest.main()

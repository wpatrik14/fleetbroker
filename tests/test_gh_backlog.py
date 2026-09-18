import unittest
from datetime import datetime, timedelta, timezone

from fleetbroker.probes.gh_backlog import prepare_state, decide, build_body

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


def issue(number, state="OPEN", labels=(), closed_at=None, title=None, url=None):
    return {
        "number": number,
        "title": title or f"issue {number}",
        "url": url or f"https://github.com/x/y/issues/{number}",
        "state": state,
        "labels": [{"name": n} for n in labels],
        "closedAt": closed_at,
    }


def gathered(issues, my_site="home", known_sites=("home", "site-b"), window_days=7):
    return {
        "repo": "x/y",
        "my_site": my_site,
        "known_sites": list(known_sites),
        "window_days": window_days,
        "issues": issues,
    }


class TestCandidateFiltering(unittest.TestCase):
    def test_excludes_closed_issues(self):
        derived = prepare_state({}, gathered([issue(1, state="CLOSED", labels=["site:shared"])]), NOW)
        self.assertEqual(derived["candidates"], [])

    def test_excludes_already_claimed(self):
        derived = prepare_state(
            {}, gathered([issue(1, labels=["site:shared", "claimed-by:home"])]), NOW
        )
        self.assertEqual(derived["candidates"], [])

    def test_excludes_reserved_for_other_site(self):
        derived = prepare_state({}, gathered([issue(1, labels=["site:site-b"])]), NOW)
        self.assertEqual(derived["candidates"], [])

    def test_includes_reserved_for_my_site(self):
        derived = prepare_state({}, gathered([issue(1, labels=["site:home"])]), NOW)
        self.assertEqual(len(derived["candidates"]), 1)

    def test_includes_shared_and_unlabeled_site(self):
        derived = prepare_state(
            {}, gathered([issue(1, labels=["site:shared"]), issue(2, labels=[])]), NOW
        )
        self.assertEqual({c["number"] for c in derived["candidates"]}, {1, 2})

    def test_sorts_by_priority_then_number(self):
        derived = prepare_state(
            {},
            gathered([
                issue(3, labels=["site:shared", "priority:P3"]),
                issue(1, labels=["site:shared", "priority:P2"]),
                issue(2, labels=["site:shared", "priority:P1"]),
            ]),
            NOW,
        )
        self.assertEqual([c["number"] for c in derived["candidates"]], [2, 1, 3])

    def test_missing_priority_sorts_last(self):
        derived = prepare_state(
            {},
            gathered([
                issue(1, labels=["site:shared"]),
                issue(2, labels=["site:shared", "priority:P3"]),
            ]),
            NOW,
        )
        self.assertEqual([c["number"] for c in derived["candidates"]], [2, 1])


class TestFairnessCounts(unittest.TestCase):
    def test_open_claimed_issue_counts(self):
        derived = prepare_state(
            {}, gathered([issue(1, labels=["claimed-by:site-b"])]), NOW
        )
        self.assertEqual(derived["site_counts"]["site-b"], 1)

    def test_closed_claim_within_window_counts(self):
        closed_at = (NOW - timedelta(days=2)).isoformat().replace("+00:00", "Z")
        derived = prepare_state(
            {},
            gathered([issue(1, state="CLOSED", labels=["claimed-by:home"], closed_at=closed_at)]),
            NOW,
        )
        self.assertEqual(derived["site_counts"]["home"], 1)

    def test_closed_claim_outside_window_does_not_count(self):
        closed_at = (NOW - timedelta(days=30)).isoformat().replace("+00:00", "Z")
        derived = prepare_state(
            {},
            gathered([issue(1, state="CLOSED", labels=["claimed-by:home"], closed_at=closed_at)]),
            NOW,
        )
        self.assertEqual(derived["site_counts"]["home"], 0)

    def test_unknown_claimant_ignored(self):
        derived = prepare_state({}, gathered([issue(1, labels=["claimed-by:someone-else"])]), NOW)
        self.assertEqual(derived["site_counts"], {"home": 0, "site-b": 0})


class TestDecide(unittest.TestCase):
    def test_no_candidates_no_notify(self):
        derived = prepare_state({}, gathered([]), NOW)
        d = decide({}, derived, NOW)
        self.assertFalse(d.notify)
        self.assertIn("no eligible", d.reason)

    def test_notifies_when_fair(self):
        data = gathered([issue(1, labels=["site:shared", "claimed-by:site-b"]),
                          issue(2, labels=["site:shared"])])
        derived = prepare_state({}, data, NOW)
        d = decide(data, derived, NOW)
        self.assertTrue(d.notify)
        self.assertIn("#2", d.reason)

    def test_holds_back_when_ahead_of_peer(self):
        data = gathered([
            issue(1, labels=["claimed-by:home"]),
            issue(2, labels=["claimed-by:home"]),
            issue(3, labels=["site:shared"]),
        ])
        derived = prepare_state({}, data, NOW)
        d = decide(data, derived, NOW)
        self.assertFalse(d.notify)
        self.assertIn("fair-share hold-back", d.reason)

    def test_notifies_when_behind_peer(self):
        data = gathered([
            issue(1, labels=["claimed-by:site-b"]),
            issue(2, labels=["claimed-by:site-b"]),
            issue(3, labels=["site:shared"]),
        ])
        derived = prepare_state({}, data, NOW)
        d = decide(data, derived, NOW)
        self.assertTrue(d.notify)

    def test_single_site_no_fairness_check(self):
        data = gathered(
            [issue(1, labels=["claimed-by:home"]), issue(2, labels=["site:shared"])],
            known_sites=("home",),
        )
        derived = prepare_state({}, data, NOW)
        d = decide(data, derived, NOW)
        self.assertTrue(d.notify)


class TestBuildBody(unittest.TestCase):
    def test_includes_claim_instructions(self):
        data = gathered([issue(5, labels=["site:shared", "priority:P1", "size:M"], title="Fix thing")])
        derived = prepare_state({}, data, NOW)
        d = decide(data, derived, NOW)
        body = build_body(data, derived, d)
        self.assertIn("#5", body)
        self.assertIn("Fix thing", body)
        self.assertIn("claimed-by:home", body)
        self.assertIn("--add-assignee @me", body)


if __name__ == "__main__":
    unittest.main()

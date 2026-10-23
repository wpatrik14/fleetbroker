import json
import subprocess
import unittest
from datetime import datetime, timezone
from unittest import mock

from fleetbroker.probes import gh_repo_watch as probe

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
OLD = "2026-09-17T10:00:00+00:00"
NEW = "2026-09-17T11:30:00Z"


def item(number, updated=NEW, state="OPEN", title=None):
    return {
        "number": number,
        "title": title or f"item {number}",
        "state": state,
        "updatedAt": updated,
        "url": f"https://github.com/x/y/issues/{number}",
    }


def fake_run(table, failing=()):
    """Build a subprocess.run stand-in. `table` maps (repo, 'issue'|'pr') to a
    list of items; repos in `failing` exit non-zero."""

    def run(argv, **kwargs):
        kind = argv[1]
        repo = argv[argv.index("-R") + 1]
        if repo in failing:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="HTTP 502")
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(table.get((repo, kind), [])), stderr="")

    return run


def run_gather(config, table, failing=()):
    with mock.patch.object(probe.subprocess, "run", side_effect=fake_run(table, failing)) as m:
        return probe.gather(config), m


class TestLegacySingleRepo(unittest.TestCase):
    def test_gather_shape_and_cli_args(self):
        data, run = run_gather({"repo": "a/one"}, {("a/one", "issue"): [item(1)], ("a/one", "pr"): [item(2)]})
        self.assertFalse(data["multi"])
        self.assertEqual([i["number"] for i in data["issues"]], [1])
        self.assertEqual([p["number"] for p in data["prs"]], [2])
        argv = run.call_args_list[0].args[0]
        self.assertEqual(argv[:2], ["gh", "issue"])
        self.assertEqual(run.call_args_list[0].kwargs["timeout"], 30)

    def test_body_format_is_unchanged(self):
        data, _ = run_gather(
            {"repo": "a/one"},
            {("a/one", "issue"): [item(1, title="Bug")], ("a/one", "pr"): [item(2, state="MERGED", title="Fix")]},
        )
        state = {"last_notify_epoch": 0, "last_check": OLD}
        derived = probe.prepare_state(state, data, NOW)
        decision = probe.decide(data, derived, NOW)
        self.assertTrue(decision.notify)
        self.assertEqual(decision.reason, "2 new/updated issue(s)/PR(s) since last check")
        self.assertEqual(
            probe.build_body(data, derived, decision),
            "[Repo-watch] New/updated items:\n"
            "- Issue #1 [OPEN]: Bug - https://github.com/x/y/issues/1\n"
            "- PR #2 [MERGED]: Fix - https://github.com/x/y/issues/2",
        )

    def test_state_only_touches_last_check(self):
        data, _ = run_gather({"repo": "a/one"}, {})
        state = {"last_notify_epoch": 0, "last_check": OLD}
        probe.prepare_state(state, data, NOW)
        self.assertEqual(state, {"last_notify_epoch": 0, "last_check": NOW.isoformat()})

    def test_old_items_are_filtered_by_watermark(self):
        data, _ = run_gather({"repo": "a/one"}, {("a/one", "issue"): [item(1, updated="2026-09-17T09:00:00Z")]})
        derived = probe.prepare_state({"last_check": OLD}, data, NOW)
        self.assertEqual(derived, {"issues": [], "prs": []})
        self.assertFalse(probe.decide(data, derived, NOW).notify)

    def test_failure_raises_like_before(self):
        with self.assertRaises(RuntimeError):
            run_gather({"repo": "a/one"}, {}, failing=("a/one",))

    def test_repo_is_not_format_validated(self):
        repos, multi = probe.resolve_repos({"repo": "github.example.com/a/one"})
        self.assertEqual((repos, multi), (["github.example.com/a/one"], False))


class TestMultiRepo(unittest.TestCase):
    TABLE = {
        ("a/one", "issue"): [item(1, title="A issue")],
        ("a/one", "pr"): [item(5, title="A pr", state="MERGED")],
        ("b/two", "issue"): [item(1, title="B issue", state="CLOSED")],
    }

    def test_merge_and_repo_prefix(self):
        data, run = run_gather({"repos": ["a/one", "b/two"]}, self.TABLE)
        self.assertEqual(run.call_count, 4)
        state = {"last_notify_epoch": 0, "last_check": OLD}
        derived = probe.prepare_state(state, data, NOW)
        decision = probe.decide(data, derived, NOW)
        self.assertTrue(decision.notify)
        self.assertEqual(
            probe.build_body(data, derived, decision),
            "[Repo-watch] New/updated items:\n"
            "- [a/one] Issue #1 [OPEN]: A issue - https://github.com/x/y/issues/1\n"
            "- [b/two] Issue #1 [CLOSED]: B issue - https://github.com/x/y/issues/1\n"
            "- [a/one] PR #5 [MERGED]: A pr - https://github.com/x/y/issues/5",
        )

    def test_single_element_list_still_prefixes(self):
        data, _ = run_gather({"repos": ["a/one"]}, self.TABLE)
        derived = probe.prepare_state({"last_check": OLD}, data, NOW)
        self.assertIn("- [a/one] Issue #1", probe.build_body(data, derived, probe.decide(data, derived, NOW)))

    def test_watermarks_advance_per_repo_and_last_check_is_min(self):
        data, _ = run_gather({"repos": ["a/one", "b/two"]}, self.TABLE)
        state = {"last_notify_epoch": 0, "last_check": OLD}
        probe.prepare_state(state, data, NOW)
        self.assertEqual(state["repo_checks"], {"a/one": NOW.isoformat(), "b/two": NOW.isoformat()})
        self.assertEqual(state["last_check"], NOW.isoformat())

    def test_per_repo_watermark_filters_independently(self):
        data, _ = run_gather({"repos": ["a/one", "b/two"]}, self.TABLE)
        state = {"last_check": OLD, "repo_checks": {"a/one": "2026-09-17T11:45:00+00:00"}}
        derived = probe.prepare_state(state, data, NOW)
        # a/one's items (11:30) are older than its watermark; b/two falls back to last_check
        self.assertEqual([(i["repo"], i["number"]) for i in derived["issues"]], [("b/two", 1)])
        self.assertEqual(derived["prs"], [])


class TestValidation(unittest.TestCase):
    def assert_invalid(self, config, fragment):
        with self.assertRaises(ValueError) as ctx:
            probe.resolve_repos(config)
        self.assertIn(fragment, str(ctx.exception))

    def test_neither(self):
        self.assert_invalid({}, "required")

    def test_both(self):
        self.assert_invalid({"repo": "a/one", "repos": ["b/two"]}, "not both")

    def test_empty_list(self):
        self.assert_invalid({"repos": []}, "non-empty list")

    def test_repos_must_be_a_list(self):
        self.assert_invalid({"repos": "a/one"}, "non-empty list")

    def test_empty_repo_string(self):
        self.assert_invalid({"repo": "  "}, "non-empty string")

    def test_malformed_names(self):
        for bad in ("one", "a/b/c", "/two", "a/", "a b/c", "", 5, None):
            with self.subTest(bad=bad):
                self.assert_invalid({"repos": ["a/one", bad]}, "invalid repository name")

    def test_duplicates_including_case(self):
        self.assert_invalid({"repos": ["a/one", "b/two", "a/one"]}, "duplicate")
        self.assert_invalid({"repos": ["a/one", "A/One"]}, "duplicate")

    def test_gather_validates_before_any_subprocess_call(self):
        with mock.patch.object(probe.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                probe.gather({"repos": []})
        run.assert_not_called()


class TestPartialFailure(unittest.TestCase):
    TABLE = {("a/one", "issue"): [item(1, title="A issue")]}

    def gather_partial(self):
        data, _ = run_gather({"repos": ["a/one", "b/two"]}, self.TABLE, failing=("b/two",))
        return data

    def test_other_repos_still_reported_and_failure_in_body(self):
        data = self.gather_partial()
        self.assertEqual(data["repos"], ["a/one"])
        self.assertIn("b/two", data["errors"])
        state = {"last_notify_epoch": 0, "last_check": OLD}
        derived = probe.prepare_state(state, data, NOW)
        decision = probe.decide(data, derived, NOW)
        self.assertTrue(decision.notify)
        self.assertIn("1 repo(s) failed", decision.reason)
        body = probe.build_body(data, derived, decision)
        self.assertIn("- [a/one] Issue #1 [OPEN]: A issue", body)
        self.assertIn("- [b/two] could not be fetched (will retry next run): ", body)
        self.assertIn("HTTP 502", body)

    def test_failed_repo_watermark_does_not_advance(self):
        data = self.gather_partial()
        state = {"last_notify_epoch": 0, "last_check": OLD}
        probe.prepare_state(state, data, NOW)
        self.assertEqual(state["repo_checks"], {"a/one": NOW.isoformat(), "b/two": OLD})
        self.assertEqual(state["last_check"], OLD)

    def test_failed_repo_events_reported_after_recovery(self):
        state = {"last_notify_epoch": 0, "last_check": OLD}
        probe.prepare_state(state, self.gather_partial(), NOW)
        later = datetime(2026, 9, 17, 12, 5, tzinfo=timezone.utc)
        table = {("a/one", "issue"): [item(1)], ("b/two", "issue"): [item(9, updated="2026-09-17T11:00:00Z")]}
        data, _ = run_gather({"repos": ["a/one", "b/two"]}, table)
        derived = probe.prepare_state(state, data, later)
        self.assertEqual([(i["repo"], i["number"]) for i in derived["issues"]], [("b/two", 9)])
        self.assertEqual(state["last_check"], later.isoformat())

    def test_failure_alone_does_not_notify(self):
        data, _ = run_gather({"repos": ["a/one", "b/two"]}, {}, failing=("b/two",))
        derived = probe.prepare_state({"last_check": OLD}, data, NOW)
        decision = probe.decide(data, derived, NOW)
        self.assertFalse(decision.notify)
        self.assertIn("failed to fetch", decision.reason)

    def test_all_failing_raises_and_leaves_state_to_runner(self):
        with self.assertRaises(RuntimeError) as ctx:
            run_gather({"repos": ["a/one", "b/two"]}, {}, failing=("a/one", "b/two"))
        self.assertIn("a/one", str(ctx.exception))
        self.assertIn("b/two", str(ctx.exception))

    def test_timeout_counts_as_failure_for_that_repo_only(self):
        def run(argv, **kwargs):
            if "b/two" in argv:
                raise subprocess.TimeoutExpired(argv, 30)
            return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")

        with mock.patch.object(probe.subprocess, "run", side_effect=run):
            data = probe.gather({"repos": ["a/one", "b/two"]})
        self.assertEqual(data["repos"], ["a/one"])
        self.assertIn("b/two", data["errors"])


class TestStateMigration(unittest.TestCase):
    def test_legacy_state_json_loads_into_multi_mode(self):
        legacy = json.loads(json.dumps({"last_notify_epoch": 123.0, "last_check": OLD}))
        data, _ = run_gather({"repos": ["a/one", "b/two"]}, {("b/two", "pr"): [item(3)]})
        derived = probe.prepare_state(legacy, data, NOW)
        self.assertEqual([(p["repo"], p["number"]) for p in derived["prs"]], [("b/two", 3)])
        self.assertEqual(legacy["last_notify_epoch"], 123.0)
        self.assertEqual(set(legacy["repo_checks"]), {"a/one", "b/two"})

    def test_multi_state_loads_back_into_legacy_mode(self):
        state = {"last_check": OLD, "repo_checks": {"a/one": NOW.isoformat()}}
        data, _ = run_gather({"repo": "a/one"}, {("a/one", "issue"): [item(1)]})
        derived = probe.prepare_state(state, data, NOW)
        self.assertEqual(len(derived["issues"]), 1)  # legacy mode ignores repo_checks
        self.assertEqual(state["last_check"], NOW.isoformat())

    def test_repo_removed_from_config_is_pruned(self):
        state = {"last_check": OLD, "repo_checks": {"a/one": OLD, "gone/repo": OLD}}
        data, _ = run_gather({"repos": ["a/one", "b/two"]}, {})
        probe.prepare_state(state, data, NOW)
        self.assertEqual(set(state["repo_checks"]), {"a/one", "b/two"})

    def test_newly_added_repo_inherits_oldest_watermark_not_epoch_2000(self):
        state = {"last_check": NOW.isoformat(), "repo_checks": {"a/one": NOW.isoformat()}}
        data, _ = run_gather({"repos": ["a/one", "b/two"]}, {}, failing=("b/two",))
        probe.prepare_state(state, data, NOW)
        self.assertEqual(state["repo_checks"]["b/two"], NOW.isoformat())


class _Py310Datetime(datetime):
    """datetime whose fromisoformat rejects a trailing 'Z', like Python < 3.11."""

    @classmethod
    def fromisoformat(cls, value):
        if value.endswith(("Z", "z")):
            raise ValueError(f"Invalid isoformat string: {value!r}")
        return super().fromisoformat(value)


class TestTimestampParsing(unittest.TestCase):
    def test_parse_ts_accepts_z_offset_and_lowercase_z(self):
        expected = datetime(2026, 9, 17, 11, 30, tzinfo=timezone.utc)
        for value in ("2026-09-17T11:30:00Z", "2026-09-17T11:30:00z", "2026-09-17T11:30:00+00:00",
                      "2026-09-17T13:30:00+02:00"):
            with self.subTest(value=value):
                parsed = probe._parse_ts(value)
                self.assertEqual(parsed, expected)
                self.assertIsNotNone(parsed.tzinfo)

    def test_gh_output_with_z_suffix_works_under_pre_311_parsing(self):
        with mock.patch.object(probe, "datetime", _Py310Datetime):
            data, _ = run_gather({"repo": "a/one"}, {("a/one", "issue"): [item(1, updated="2026-09-17T11:30:00Z")]})
            derived = probe.prepare_state({"last_check": OLD}, data, NOW)
        self.assertEqual([i["number"] for i in derived["issues"]], [1])

    def test_z_suffixed_state_values_work_under_pre_311_parsing(self):
        state = {
            "last_check": "2026-09-17T10:00:00Z",
            "repo_checks": {"a/one": "2026-09-17T11:45:00Z", "b/two": "2026-09-17T10:00:00Z"},
        }
        table = {
            ("a/one", "issue"): [item(1, updated="2026-09-17T11:30:00Z")],  # older than a/one's watermark
            ("b/two", "issue"): [item(2, updated="2026-09-17T11:30:00Z")],  # newer than b/two's watermark
        }
        with mock.patch.object(probe, "datetime", _Py310Datetime):
            data, _ = run_gather({"repos": ["a/one", "b/two"]}, table)
            derived = probe.prepare_state(state, data, NOW)
        self.assertEqual([(i["repo"], i["number"]) for i in derived["issues"]], [("b/two", 2)])
        self.assertEqual(state["last_check"], NOW.isoformat())


if __name__ == "__main__":
    unittest.main()

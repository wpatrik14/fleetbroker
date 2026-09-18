import unittest

from fleetbroker import compat


class TestParseVersion(unittest.TestCase):
    def test_parses_standard_cli_output(self):
        self.assertEqual(compat.parse_version("2.1.267 (Claude Code)"), (2, 1, 267))

    def test_parses_bare_version_string(self):
        self.assertEqual(compat.parse_version("2.1.0"), (2, 1, 0))

    def test_returns_none_on_unparseable_input(self):
        self.assertIsNone(compat.parse_version("not a version"))
        self.assertIsNone(compat.parse_version(""))


class TestCheckVersion(unittest.TestCase):
    def test_within_verified_range_is_ok(self):
        status, detail = compat.check_version("2.1.267 (Claude Code)")
        self.assertEqual(status, "OK")
        self.assertIn("2.1.267", detail)

    def test_at_exact_minimum_is_ok(self):
        status, _ = compat.check_version("2.1.0")
        self.assertEqual(status, "OK")

    def test_below_minimum_is_warn_not_fail(self):
        status, detail = compat.check_version("2.0.9")
        self.assertEqual(status, "WARN")
        self.assertIn("older", detail)

    def test_at_next_major_is_warn_not_fail(self):
        status, detail = compat.check_version("3.0.0")
        self.assertEqual(status, "WARN")
        self.assertIn("newer", detail)

    def test_unparseable_string_is_warn_not_crash(self):
        status, detail = compat.check_version("garbage output")
        self.assertEqual(status, "WARN")
        self.assertIn("could not parse", detail)


if __name__ == "__main__":
    unittest.main()

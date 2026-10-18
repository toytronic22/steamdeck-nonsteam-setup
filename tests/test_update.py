import json
import os
import tempfile
import unittest
from unittest import mock

import update


class Parse(unittest.TestCase):
    def test_versions(self):
        self.assertEqual(update.parse("1.0.0\n"), (1, 0, 0))
        self.assertEqual(update.parse("v2.10"), (2, 10))
        self.assertGreater(update.parse("1.10.0"), update.parse("1.9.9"))

    def test_garbage(self):
        for text in (None, "", "404: Not Found", "<html>", "1.0.0-beta", "1..0"):
            self.assertIsNone(update.parse(text), text)


class ReportLine(unittest.TestCase):
    def test_newer(self):
        line = update.report_line("1.0.0", "1.2.0\n")
        self.assertIn("вышла 1.2.0", line)
        self.assertIn(update.INSTALL_CMD, line)

    def test_same_or_older(self):
        self.assertEqual(update.report_line("1.2.0", "1.2.0"), "Версия 1.2.0 · новее нет.")
        self.assertEqual(update.report_line("1.2.0", "1.1.9"), "Версия 1.2.0 · новее нет.")

    def test_check_failed(self):
        with mock.patch.object(update, "latest", return_value=None):
            self.assertIn("проверить обновление не удалось", update.report_line("1.0.0"))

    def test_no_version_file(self):
        with mock.patch.object(update, "HERE", tempfile.gettempdir() + "/no-such-dir"):
            self.assertIn("Версия неизвестна", update.report_line())

    def test_command_points_to_repo(self):
        self.assertEqual(update.INSTALL_CMD,
                         "curl -fsSL https://raw.githubusercontent.com/toytronic22/steamdeck-nonsteam-setup/main/get.sh"
                         " | bash")


class Latest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = os.path.join(self.tmp.name, "data", "update-check.json")
        for p in (mock.patch.object(update, "CACHE", self.cache),
                  mock.patch.object(update, "DATA", os.path.dirname(self.cache))):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fetches_and_caches(self):
        self.assertEqual(update.latest(now=100, fetch=lambda: "1.1.0\n"), "1.1.0")
        with open(self.cache) as f:
            self.assertEqual(json.load(f), {"at": 100, "latest": "1.1.0"})

    def test_fresh_cache_skips_network(self):
        update.latest(now=100, fetch=lambda: "1.1.0")
        boom = mock.Mock(side_effect=AssertionError("network"))
        self.assertEqual(update.latest(now=100 + update.EVERY - 1, fetch=boom), "1.1.0")
        boom.assert_not_called()

    def test_stale_cache_refetches(self):
        update.latest(now=100, fetch=lambda: "1.1.0")
        self.assertEqual(update.latest(now=100 + update.EVERY, fetch=lambda: "1.2.0"), "1.2.0")

    def test_failure_is_not_cached(self):
        def fail():
            raise OSError("offline")
        self.assertIsNone(update.latest(now=100, fetch=fail))
        self.assertIsNone(update.latest(now=100, fetch=lambda: "404: Not Found"))
        self.assertFalse(os.path.exists(self.cache))
        self.assertEqual(update.latest(now=101, fetch=lambda: "1.0.1"), "1.0.1")

    def test_broken_cache_is_ignored(self):
        os.makedirs(os.path.dirname(self.cache))
        with open(self.cache, "w") as f:
            f.write("{oops")
        self.assertEqual(update.latest(now=100, fetch=lambda: "1.0.1"), "1.0.1")


class VersionFile(unittest.TestCase):
    def test_repo_version_parses(self):
        self.assertIsNotNone(update.parse(update.current()))


if __name__ == "__main__":
    unittest.main()

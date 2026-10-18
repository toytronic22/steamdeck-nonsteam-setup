import os
import tempfile
import unittest
from unittest import mock

import main


class NothingNew(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.report = os.path.join(self.tmp.name, "last-report.txt")
        for p in (mock.patch.object(main, "REPORT", self.report),
                  mock.patch.object(main, "library_now", return_value="")):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_says_nothing_new(self):
        self.assertEqual(main.nothing_new(), "Новых игр нет — всё уже оформлено.")

    def test_no_command_line_hints(self):
        with open(self.report, "w") as f:
            f.write("Оформлено игр: 1 из 1.")
        text = main.nothing_new()
        self.assertNotIn("--", text)
        self.assertNotIn("ключ", text)

    def test_libraries_and_last_report_follow(self):
        with open(self.report, "w") as f:
            f.write("Оформлено игр: 1 из 1.\n")
        with mock.patch.object(main, "library_now", return_value="Библиотеки сейчас:\n\n✓ Игра: всё на месте"):
            text = main.nothing_new()
        head, libs, last = text.split("\n\n", 2)
        self.assertEqual(head, "Новых игр нет — всё уже оформлено.")
        self.assertEqual(libs, "Библиотеки сейчас:")
        self.assertIn("✓ Игра: всё на месте", last)
        self.assertRegex(last, r"Последний отчёт, \d\d\.\d\d \d\d:\d\d:\n\nОформлено игр: 1 из 1\.$")


class LibraryNow(unittest.TestCase):
    def libraries(self, done):
        shortcuts = [{"appid": int(k), "name": v.pop("name"), "exe": "/g/game.exe"} for k, v in done.items()]
        with mock.patch.object(main, "find_user_dir", return_value="1"), \
                mock.patch.object(main, "read_shortcuts", return_value=shortcuts), \
                mock.patch.object(main, "load_state", return_value={"done": done}), \
                mock.patch.object(main.redist, "plan", return_value={"todo": [], "stuck": [], "absent": [],
                                                                     "had": ["vc2022"]}):
            return main.library_now()

    def test_unknown_original_needs_are_shown(self):
        text = self.libraries({"1": {"name": "Ведьмак", "redist": {"depots": None, "local": []}},
                               "2": {"name": "Террария", "redist": {"depots": [], "local": []}}})
        self.assertIn("? Ведьмак: не узнал у Steam, что нужно оригиналу, — спрошу при следующем запуске", text)
        self.assertIn("✓ Террария: есть Visual C++ 2015–2022", text)

    def test_game_without_original_is_not_listed(self):
        text = self.libraries({"1": {"name": "Своя игра"}, "2": {"name": "Террария", "redist": {"depots": []}}})
        self.assertNotIn("Своя игра", text)


if __name__ == "__main__":
    unittest.main()

import hashlib
import os
import re
import unittest

import main

GROUP_NAME_HASHES = {"e582be5f3b8f2f67", "3491f77c94f2a59e", "d2f12d879e340cc4", "d2e124a92a721f29",
                     "794fe492ed5159d5", "c98fdbce5145934d", "786806b784a56b57", "233bc15924d82979"}


def candidates(name, exe):
    return main.name_candidates({"name": name, "exe": exe})


class NameCandidates(unittest.TestCase):
    def test_group_after_by_is_cut_right_after_full_name(self):
        self.assertEqual(candidates("Far Cry Primal by SomeGroup", "/home/deck/Downloads/Far Cry Primal by SomeGroup/bin/FCPrimal.exe")[:2],
                         ["Far Cry Primal by SomeGroup", "Far Cry Primal"])

    def test_by_inside_title_keeps_full_title_first(self):
        self.assertEqual(candidates("Dead by Daylight", "/home/deck/Games/Dead by Daylight/DeadByDaylight.exe")[0],
                         "Dead by Daylight")

    def test_last_by_is_cut(self):
        self.assertIn("Dead by Daylight", candidates("Dead by Daylight by Someone", "/home/deck/Games/x/DBD.exe"))

    def test_unspaced_tail_after_dash(self):
        self.assertEqual(candidates("Grounded2.exe", "/home/deck/Games/Grounded.2-SomeGroup/Grounded2.exe"),
                         ["Grounded 2-SomeGroup", "Grounded 2"])

    def test_spaced_dash_tail(self):
        self.assertIn("The Witcher 3 Wild Hunt",
                      candidates("Witcher3.exe", "/home/deck/Games/The Witcher 3 Wild Hunt - Some Repack/bin/x64/witcher3.exe"))

    def test_brackets_versions_and_junk_words_removed(self):
        self.assertEqual(candidates("x.exe", "/home/deck/Games/Stardew Valley v1.6.15 [GOG]/x.exe")[0], "Stardew Valley")

    def test_generic_dirs_skipped_and_root_dirs_stop_the_walk(self):
        found = candidates("ShippingPC-BmGame.exe",
                           "/run/media/mmcblk0p1/Games/Batman Arkham Asylum GOTY/Binaries/ShippingPC-BmGame.exe")
        self.assertEqual(found[0], "Batman Arkham Asylum")
        self.assertNotIn("mmcblk0p1", " ".join(found))
        self.assertNotIn("Binaries", found)

    def test_cyrillic_group(self):
        self.assertIn("Ведьмак 3", candidates("Игра", "/home/deck/Games/Ведьмак 3 by Кто-то/witcher3.exe"))

    def test_exe_and_bat_names_are_not_titles(self):
        self.assertTrue(main.is_exe_name("RunLauncher.bat", "/g/RunLauncher.bat"))
        self.assertTrue(main.is_exe_name("Game.exe", "/g/Other.exe"))
        self.assertFalse(main.is_exe_name("Hollow Knight", "/g/hollow_knight.exe"))

    def test_no_group_names_left_in_repo(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for name in files:
                if not name.endswith((".py", ".sh", ".md", ".html")):
                    continue
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    words = set(re.findall(r"[^\W\d_]+", f.read().lower()))
                hit = {hashlib.sha256(w.encode()).hexdigest()[:16] for w in words} & GROUP_NAME_HASHES
                self.assertFalse(hit, name)


if __name__ == "__main__":
    unittest.main()

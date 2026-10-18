import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import add_to_steam
from steamcdp import SteamUnavailable


class FakeCdp:
    calls = []
    fail = False

    def __init__(self, *args, **kwargs):
        if FakeCdp.fail:
            raise SteamUnavailable("closed")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def call(self, js, *args):
        FakeCdp.calls.append((js, args))
        return 99 if "AddShortcut" in js else None


class Button(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = os.path.join(self.tmp.name, "config")
        self.grid = os.path.join(self.config, "grid")
        os.makedirs(self.grid)
        self.pending = os.path.join(self.tmp.name, "button-pending")
        FakeCdp.calls, FakeCdp.fail = [], False
        for p in (mock.patch.object(add_to_steam, "Cdp", FakeCdp),
                  mock.patch.object(add_to_steam, "BUTTON_PENDING", self.pending),
                  mock.patch.object(add_to_steam, "DATA", self.tmp.name),
                  mock.patch.object(add_to_steam, "config_dir", lambda: self.config),
                  mock.patch.object(add_to_steam.time, "sleep", lambda _: None)):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def run_quiet(self, fn):
        out = io.StringIO()
        with redirect_stdout(out):
            code = fn()
        return code, out.getvalue()

    def js(self):
        return [js for js, _ in FakeCdp.calls]

    def test_no_profile_leaves_pending(self):
        with mock.patch.object(add_to_steam, "config_dir", lambda: None):
            code, out = self.run_quiet(add_to_steam.add)
        self.assertEqual(code, 1)
        self.assertTrue(os.path.exists(self.pending))
        self.assertIn("появится сама", out)

    def test_no_port_leaves_pending(self):
        FakeCdp.fail = True
        code, out = self.run_quiet(add_to_steam.add)
        self.assertEqual(code, 1)
        self.assertTrue(os.path.exists(self.pending))
        self.assertIn("порт отладки закрыт", out)

    def test_adds_and_clears_pending(self):
        open(self.pending, "w").close()
        with mock.patch.object(add_to_steam, "find_shortcut", return_value=None), \
                mock.patch.object(add_to_steam, "dress", return_value=[]):
            code, out = self.run_quiet(add_to_steam.add)
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(self.pending))
        self.assertTrue(any("AddShortcut" in js for js in self.js()))
        self.assertIn("Добавил в Steam ярлык", out)

    def test_existing_button_is_not_added_twice(self):
        sc = {"appid": 7, "exe": add_to_steam.RUN, "icon": "x"}
        with mock.patch.object(add_to_steam, "find_shortcut", return_value=sc), \
                mock.patch.object(add_to_steam, "dress", return_value=[]):
            code, out = self.run_quiet(add_to_steam.add)
        self.assertEqual(code, 0)
        self.assertFalse(any("AddShortcut" in js for js in self.js()))

    def test_remove_deletes_button_and_its_art_only(self):
        sc = {"appid": 7, "exe": add_to_steam.RUN}
        mine = ["7.jpg", "7p.png", "7_hero.jpg", "7_logo.png", "7.json"]
        other = ["77p.jpg", "70_hero.jpg", "7_other.txt"]
        for name in mine + other:
            open(os.path.join(self.grid, name), "w").close()
        open(self.pending, "w").close()
        with mock.patch.object(add_to_steam, "find_shortcut", side_effect=[sc, sc, None]):
            code, out = self.run_quiet(add_to_steam.remove)
        self.assertEqual(code, 0, out)
        self.assertEqual(FakeCdp.calls[0][1], (7,))
        self.assertIn("RemoveShortcut", FakeCdp.calls[0][0])
        self.assertEqual(sorted(os.listdir(self.grid)), sorted(other))
        self.assertFalse(os.path.exists(self.pending))

    def test_remove_keeps_art_when_steam_did_not_remove(self):
        sc = {"appid": 7, "exe": add_to_steam.RUN}
        open(os.path.join(self.grid, "7p.png"), "w").close()
        with mock.patch.object(add_to_steam, "find_shortcut", return_value=sc):
            code, out = self.run_quiet(add_to_steam.remove)
        self.assertEqual(code, 1)
        self.assertIn("проверь библиотеку", out)
        self.assertEqual(os.listdir(self.grid), ["7p.png"])

    def test_remove_without_port(self):
        FakeCdp.fail = True
        sc = {"appid": 7, "exe": add_to_steam.RUN}
        with mock.patch.object(add_to_steam, "find_shortcut", return_value=sc):
            code, out = self.run_quiet(add_to_steam.remove)
        self.assertEqual(code, 1)
        self.assertIn("удали ярлык", out)

    def test_remove_when_nothing_installed(self):
        with mock.patch.object(add_to_steam, "find_shortcut", return_value=None):
            code, out = self.run_quiet(add_to_steam.remove)
        self.assertEqual(code, 0)
        self.assertEqual(FakeCdp.calls, [])


if __name__ == "__main__":
    unittest.main()

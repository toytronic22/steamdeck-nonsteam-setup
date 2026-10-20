import os
import tempfile
import unittest
from unittest import mock

import main
import steamemu
from tests.test_runner_launch import FakeCdp

SMART = b"[Launcher]\r\nTarget=castnchill.exe\r\nStartIn=Cast n Chill\r\nSteamClientPath64=steamclient64.dll\r\n"
COLD = (b"# modified version of ColdClientLoader\n[SteamClient]\nExe=game.exe\nAppId=3483740\n"
        b"SteamClientDll=steamclient\\steamclient.dll\nSteamClient64Dll=steamclient\\steamclient64.dll\n"
        b"\n[Injection]\nForceInjectSteamClient=0\n")


def put(data, *parts):
    path = os.path.join(*parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def read(path):
    with open(path, "rb") as f:
        return f.read()


class Fix(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = os.path.join(self.tmp.name, "Cast n Chill v1.3.0a")
        self.exe = put(b"MZ", self.game, "SmartSteamLoader_x64.exe")

    def tearDown(self):
        self.tmp.cleanup()

    def test_smart_loader_gets_renamed_copy(self):
        ini = put(SMART, self.game, "steamclient64.ini")
        put(b"gbe emulator", self.game, "steamclient64.dll")
        done = steamemu.fix(self.exe)
        self.assertEqual([(c["was"], c["now"]) for c in done], [("steamclient64.dll", "gbe_client64.dll")])
        self.assertEqual(read(os.path.join(self.game, "gbe_client64.dll")), b"gbe emulator")
        self.assertEqual(read(os.path.join(self.game, "steamclient64.dll")), b"gbe emulator")
        self.assertEqual(read(ini), SMART.replace(b"=steamclient64.dll", b"=gbe_client64.dll"))
        self.assertEqual(read(ini + ".orig"), SMART)

    def test_second_run_changes_nothing(self):
        ini = put(SMART, self.game, "steamclient64.ini")
        put(b"gbe emulator", self.game, "steamclient64.dll")
        steamemu.fix(self.exe)
        before = {n: read(os.path.join(self.game, n)) for n in os.listdir(self.game)}
        self.assertEqual(steamemu.fix(self.exe), [])
        self.assertEqual({n: read(os.path.join(self.game, n)) for n in os.listdir(self.game)}, before)
        self.assertEqual(read(ini + ".orig"), SMART)

    def test_cold_client_loader_both_dlls_keep_their_folder(self):
        ini = put(COLD, self.game, "ColdClientLoader.ini")
        put(b"32", self.game, "steamclient", "steamclient.dll")
        put(b"64", self.game, "steamclient", "steamclient64.dll")
        done = steamemu.fix(self.exe)
        self.assertEqual(sorted(c["now"] for c in done), ["steamclient\\gbe_client.dll", "steamclient\\gbe_client64.dll"])
        self.assertEqual(read(os.path.join(self.game, "steamclient", "gbe_client.dll")), b"32")
        self.assertEqual(read(os.path.join(self.game, "steamclient", "gbe_client64.dll")), b"64")
        want = COLD.replace(b"\\steamclient.dll", b"\\gbe_client.dll").replace(b"\\steamclient64.dll", b"\\gbe_client64.dll")
        self.assertEqual(read(ini), want)

    def test_names_on_disk_in_any_case(self):
        ini = put(SMART.replace(b"steamclient64.dll", b"SteamClient64.DLL"), self.game, "SteamClient64.INI")
        put(b"gbe", self.game, "STEAMCLIENT64.dll")
        done = steamemu.fix(self.exe)
        self.assertEqual([c["now"] for c in done], ["gbe_client64.dll"])
        self.assertEqual(read(os.path.join(self.game, "gbe_client64.dll")), b"gbe")
        self.assertIn(b"SteamClientPath64=gbe_client64.dll\r\n", read(ini))

    def test_utf8_bom_at_start(self):
        ini = put(b"\xef\xbb\xbf" + SMART, self.game, "steamclient64.ini")
        put(b"gbe", self.game, "steamclient64.dll")
        self.assertEqual([c["now"] for c in steamemu.fix(self.exe)], ["gbe_client64.dll"])
        self.assertTrue(read(ini).startswith(b"\xef\xbb\xbf[Launcher]\r\n"))

    def test_quoted_value_keeps_quotes(self):
        ini = put(SMART.replace(b"=steamclient64.dll", b'="steamclient64.dll"'), self.game, "steamclient64.ini")
        put(b"gbe", self.game, "steamclient64.dll")
        steamemu.fix(self.exe)
        self.assertIn(b'SteamClientPath64="gbe_client64.dll"\r\n', read(ini))

    def test_no_dll_next_to_ini_nothing_changes(self):
        ini = put(SMART, self.game, "steamclient64.ini")
        self.assertEqual(steamemu.fix(self.exe), [])
        self.assertEqual(read(ini), SMART)
        self.assertFalse(os.path.exists(ini + ".orig"))

    def test_key_outside_its_section_is_ignored(self):
        ini = put(b"[Other]\nSteamClientPath64=steamclient64.dll\n", self.game, "steamclient64.ini")
        put(b"gbe", self.game, "steamclient64.dll")
        self.assertEqual(steamemu.fix(self.exe), [])
        self.assertFalse(os.path.exists(os.path.join(self.game, "gbe_client64.dll")))
        self.assertFalse(os.path.exists(ini + ".orig"))

    def test_other_dll_name_and_absolute_paths_are_left_alone(self):
        for value in (b"C:\\Emu\\steamclient.dll", b"\\steamclient.dll"):
            text = b"[SteamClient]\nSteamClientDll=" + value + b"\nSteamClient64Dll=my_emu64.dll\n"
            put(text, self.game, "ColdClientLoader.ini")
            put(b"gbe", self.game, "my_emu64.dll")
            put(b"gbe", self.game, "steamclient.dll")
            self.assertEqual(steamemu.fix(self.exe), [], value)

    def test_existing_orig_is_not_overwritten(self):
        ini = put(SMART, self.game, "steamclient64.ini")
        put(b"first original", self.game, "steamclient64.ini.orig")
        put(b"gbe", self.game, "steamclient64.dll")
        steamemu.fix(self.exe)
        self.assertEqual(read(ini + ".orig"), b"first original")

    def test_ini_in_other_folder_is_not_touched(self):
        game_exe = put(b"MZ", self.game, "Cast n Chill", "castnchill.exe")
        ini = put(SMART, self.game, "steamclient64.ini")
        put(b"gbe", self.game, "steamclient64.dll")
        self.assertEqual(steamemu.fix(game_exe), [])
        self.assertEqual(read(ini), SMART)

    def test_plan_changes_nothing(self):
        ini = put(SMART, self.game, "steamclient64.ini")
        put(b"gbe", self.game, "steamclient64.dll")
        self.assertEqual([c["now"] for c in steamemu.plan(self.exe)], ["gbe_client64.dll"])
        self.assertEqual(read(ini), SMART)
        self.assertEqual(sorted(os.listdir(self.game)), ["SmartSteamLoader_x64.exe", "steamclient64.dll",
                                                         "steamclient64.ini"])

    def test_describe(self):
        put(SMART, self.game, "steamclient64.ini")
        put(b"gbe", self.game, "steamclient64.dll")
        items = steamemu.plan(self.exe)
        self.assertTrue(steamemu.describe(items).startswith(
            "эмулятор Steam: в steamclient64.ini steamclient64.dll → gbe_client64.dll"))
        self.assertTrue(steamemu.describe(items, dry_run=True).startswith(
            "эмулятор Steam: заменю в steamclient64.ini steamclient64.dll → gbe_client64.dll"))


class RunnerEmulator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = os.path.join(self.tmp.name, "Game")
        self.exe = put(b"MZ", self.game, "steamclient_loader_x64.exe")
        self.ini = put(SMART, self.game, "steamclient64.ini")
        put(b"gbe", self.game, "steamclient64.dll")

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, dry_run):
        return main.Runner(FakeCdp(), "1", progress=None, dry_run=dry_run)

    def test_fixes_once_and_reports(self):
        runner = self.runner(dry_run=False)
        lines = runner.apply_emulator({"appid": 7, "exe": self.exe})
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("   эмулятор Steam: в steamclient64.ini"), lines[0])
        self.assertIn(b"=gbe_client64.dll", read(self.ini))
        self.assertEqual(runner.apply_emulator({"appid": 7, "exe": self.exe}), [])

    def test_dry_run_changes_nothing(self):
        lines = self.runner(dry_run=True).apply_emulator({"appid": 7, "exe": self.exe})
        self.assertIn("заменю", lines[0])
        self.assertEqual(read(self.ini), SMART)
        self.assertFalse(os.path.exists(os.path.join(self.game, "gbe_client64.dll")))

    def test_shortcut_setup_includes_the_step(self):
        sc = {"appid": 7, "name": "Cast n Chill", "exe": self.exe, "start_dir": self.game}
        with mock.patch.object(main.steamweb, "match_game", return_value={"appid": 3483740, "name": "Cast n Chill"}), \
                mock.patch.object(main.steamweb, "store_item", return_value={"name": "Cast n Chill"}), \
                mock.patch.object(main.steamweb, "controller_support", return_value="full"), \
                mock.patch.object(main.steamweb, "app_info", return_value=None):
            orig, lines = self.runner(dry_run=True).process(sc)
        self.assertEqual(orig, 3483740)
        self.assertTrue(any(line.startswith("   эмулятор Steam: заменю") for line in lines), lines)

    def test_game_not_found_in_store_still_gets_the_fix(self):
        sc = {"appid": 7, "name": "Repack", "exe": self.exe, "start_dir": self.game}
        with mock.patch.object(main.steamweb, "match_game", return_value=None):
            orig, lines = self.runner(dry_run=False).process(sc)
        self.assertIsNone(orig)
        self.assertTrue(lines[-1].startswith("   эмулятор Steam: в steamclient64.ini"), lines)
        self.assertIn(b"=gbe_client64.dll", read(self.ini))

    def test_regular_game_gets_no_line(self):
        exe = put(b"MZ", self.tmp.name, "Plain", "Game.exe")
        self.assertEqual(self.runner(dry_run=False).apply_emulator({"appid": 7, "exe": exe}), [])

    def test_disk_error_is_reported_not_raised(self):
        runner = self.runner(dry_run=False)
        with mock.patch.object(main.steamemu.shutil, "copy2", side_effect=PermissionError("read-only")):
            lines = runner.apply_emulator({"appid": 7, "exe": self.exe})
        self.assertTrue(lines[0].startswith("   эмулятор Steam: не смог"), lines[0])
        self.assertEqual(read(self.ini), SMART)


if __name__ == "__main__":
    unittest.main()

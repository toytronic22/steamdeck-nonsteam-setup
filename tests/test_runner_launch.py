import os
import tempfile
import unittest
from unittest import mock

import main
from tests.test_launch import ASYLUM, CITY, touch


class FakeCdp:
    def __init__(self):
        self.calls = []

    def call(self, js, *args):
        self.calls.append((js, args))
        return None


class RunnerLaunch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = os.path.join(self.tmp.name, "City")

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, dry_run):
        cdp = FakeCdp()
        runner = main.Runner(cdp, "1", progress=None, dry_run=dry_run)
        cdp.calls.clear()
        return runner, cdp

    def test_moves_shortcut_with_quoted_paths(self):
        bat = touch(self.game, "RunLauncher.bat")
        exe = touch(self.game, "Binaries", "Win32", "BatmanAC.exe")
        runner, cdp = self.runner(dry_run=False)
        sc = {"appid": 7, "exe": bat, "start_dir": self.game}
        with mock.patch.object(main.steamweb, "app_info", return_value=CITY), \
                mock.patch.object(runner, "shortcut_exe", return_value=exe):
            lines = runner.apply_launch(sc, 200260)
        self.assertEqual([args for _, args in cdp.calls],
                         [(7, f'"{exe}"'), (7, f'"{os.path.dirname(exe)}"')])
        self.assertIn("SetShortcutExe", cdp.calls[0][0])
        self.assertIn("SetShortcutStartDir", cdp.calls[1][0])
        self.assertEqual(sc["exe"], exe)
        self.assertIn("перевёл на игру", lines[0])
        self.assertNotIn("не записал", lines[0])

    def test_dry_run_changes_nothing(self):
        bat = touch(self.game, "RunLauncher.bat")
        touch(self.game, "Binaries", "Win32", "BatmanAC.exe")
        runner, cdp = self.runner(dry_run=True)
        sc = {"appid": 7, "exe": bat, "start_dir": self.game}
        with mock.patch.object(main.steamweb, "app_info", return_value=CITY):
            lines = runner.apply_launch(sc, 200260)
        self.assertEqual(cdp.calls, [])
        self.assertEqual(sc["exe"], bat)
        self.assertIn("переведу на игру", lines[0])

    def test_reports_when_steam_did_not_save(self):
        bat = touch(self.game, "RunLauncher.bat")
        touch(self.game, "Binaries", "Win32", "BatmanAC.exe")
        runner, _ = self.runner(dry_run=False)
        sc = {"appid": 7, "exe": bat, "start_dir": self.game}
        with mock.patch.object(main.steamweb, "app_info", return_value=CITY), \
                mock.patch.object(runner, "shortcut_exe", return_value=bat), mock.patch.object(main.time, "sleep"):
            lines = runner.apply_launch(sc, 200260)
        self.assertIn("Steam пока не записал", lines[0])

    def test_launcher_gets_hint_and_no_change(self):
        launcher = touch(self.game, "Binaries", "BmLauncher.exe")
        touch(self.game, "Binaries", "ShippingPC-BmGame.exe")
        runner, cdp = self.runner(dry_run=False)
        sc = {"appid": 7, "exe": launcher, "start_dir": os.path.dirname(launcher)}
        with mock.patch.object(main.steamweb, "app_info", return_value=ASYLUM):
            lines = runner.apply_launch(sc, 35140)
        self.assertEqual(cdp.calls, [])
        self.assertEqual(lines, ["   запуск: ярлык ведёт на лаунчер «BmLauncher.exe». Если кнопок не видно — "
                                 "направь ярлык на exe игры: ShippingPC-BmGame.exe."])

    def test_no_steam_data_no_line_for_regular_game(self):
        exe = touch(self.game, "Game.exe")
        runner, cdp = self.runner(dry_run=False)
        with mock.patch.object(main.steamweb, "app_info", side_effect=OSError("offline")):
            self.assertEqual(runner.apply_launch({"appid": 7, "exe": exe, "start_dir": self.game}, 1), [])
        self.assertEqual(cdp.calls, [])


if __name__ == "__main__":
    unittest.main()

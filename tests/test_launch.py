import os
import tempfile
import unittest

import launch

CITY = {"config": {"launch": {
    "0": {"executable": "Binaries\\Win32\\BatmanAC.exe", "config": {"oslist": "windows"}},
    "1": {"executable": "RunLauncher.bat", "description": "Configure PC Options", "config": {"oslist": "windows"}},
    "2": {"executable": "Batman Arkham City GOTY.app", "description": "Mac Binary", "config": {"oslist": "macos"}}}}}
ASYLUM = {"config": {"launch": {
    "0": {"executable": "Binaries\\BmLauncher.exe", "workingdir": "Binaries", "config": {"oslist": "windows"}},
    "1": {"executable": "Batman Arkham Asylum GOTY.app", "description": "Launch", "config": {"oslist": "macos"}}}}}
CIV = {"config": {"launch": {
    "0": {"executable": "Launcher.exe", "type": "default", "config": {"betakey": "legacy", "oslist": "windows"}},
    "5": {"executable": "CivilizationV.exe", "type": "option1", "config": {"oslist": "windows"}},
    "6": {"executable": "CivilizationV_DX11.exe", "type": "option2", "config": {"oslist": "windows"}}}}}
WORKDIR = {"config": {"launch": {
    "0": {"executable": "bin/Game.exe", "workingdir": "bin", "config": {"oslist": "windows"}},
    "1": {"executable": "Settings.exe", "description": "Graphics settings", "config": {"oslist": "windows"}}}}}
SAFE_MODE = {"config": {"launch": {
    "0": {"executable": "Game.exe", "config": {"oslist": "windows"}},
    "1": {"executable": "GameDX11.exe", "description": "Play in DirectX 11", "config": {"oslist": "windows"}}}}}


def touch(*parts):
    path = os.path.join(*parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()
    return path


class Retarget(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_settings_shortcut_moves_to_main_exe(self):
        game = os.path.join(self.root, "Batman City")
        bat = touch(game, "RunLauncher.bat")
        exe = touch(game, "Binaries", "Win32", "BatmanAC.exe")
        move = launch.retarget(bat, CITY)
        self.assertEqual(move["exe"], exe)
        self.assertEqual(move["start_dir"], os.path.dirname(exe))
        self.assertEqual(move["rel"], os.path.join("Binaries", "Win32", "BatmanAC.exe"))
        self.assertEqual(move["was"], "Configure PC Options")

    def test_case_of_folders_on_disk_does_not_matter(self):
        game = os.path.join(self.root, "City")
        bat = touch(game, "runlauncher.BAT")
        exe = touch(game, "BINARIES", "win32", "batmanac.exe")
        self.assertEqual(launch.retarget(bat, CITY)["exe"], exe)

    def test_no_move_when_main_exe_missing(self):
        bat = touch(self.root, "City", "RunLauncher.bat")
        self.assertIsNone(launch.retarget(bat, CITY))

    def test_no_move_when_main_is_a_launcher(self):
        game = os.path.join(self.root, "Asylum")
        touch(game, "Binaries", "BmLauncher.exe")
        game_exe = touch(game, "Binaries", "ShippingPC-BmGame.exe")
        self.assertIsNone(launch.retarget(game_exe, ASYLUM))

    def test_no_move_when_already_on_main(self):
        exe = touch(self.root, "City", "Binaries", "Win32", "BatmanAC.exe")
        self.assertIsNone(launch.retarget(exe, CITY))

    def test_only_options_and_beta_entries_mean_no_main(self):
        exe = touch(self.root, "Civ", "CivilizationV_DX11.exe")
        touch(self.root, "Civ", "CivilizationV.exe")
        self.assertIsNone(launch.retarget(exe, CIV))

    def test_working_dir_from_steam_data(self):
        game = os.path.join(self.root, "G")
        settings = touch(game, "Settings.exe")
        touch(game, "bin", "Game.exe")
        self.assertEqual(launch.retarget(settings, WORKDIR)["start_dir"], os.path.join(game, "bin"))

    def test_unknown_shortcut_target_is_left_alone(self):
        exe = touch(self.root, "City", "Something.exe")
        touch(self.root, "City", "Binaries", "Win32", "BatmanAC.exe")
        self.assertIsNone(launch.retarget(exe, CITY))

    def test_other_play_variant_is_left_alone(self):
        dx11 = touch(self.root, "G", "GameDX11.exe")
        touch(self.root, "G", "Game.exe")
        self.assertIsNone(launch.retarget(dx11, SAFE_MODE))

    def test_mac_and_linux_entries_ignored(self):
        self.assertEqual([e["exe"] for e in launch.entries(CITY)], ["Binaries/Win32/BatmanAC.exe", "RunLauncher.bat"])


class LauncherHint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = os.path.join(self.tmp.name, "Asylum")

    def tearDown(self):
        self.tmp.cleanup()

    def test_hint_lists_game_exe_not_launchers(self):
        launcher = touch(self.game, "Binaries", "BmLauncher.exe")
        hint = launch.launcher_hint(launcher, ASYLUM, ["ShippingPC-BmGame.exe", "BmLauncher.exe"])
        self.assertIn("«BmLauncher.exe»", hint)
        self.assertTrue(hint.endswith(": ShippingPC-BmGame.exe."), hint)

    def test_main_exe_from_steam_comes_first(self):
        bat = touch(self.game, "RunLauncher.bat")
        touch(self.game, "Binaries", "Win32", "BatmanAC.exe")
        hint = launch.launcher_hint(bat, CITY, ["Binaries/Win32/Other.exe"])
        self.assertIn(": " + os.path.join("Binaries", "Win32", "BatmanAC.exe") + ", Binaries/Win32/Other.exe.", hint)

    def test_no_hint_for_regular_exe(self):
        exe = touch(self.game, "Game.exe")
        self.assertIsNone(launch.launcher_hint(exe, None, []))

    def test_hint_without_candidates_and_without_steam_data(self):
        launcher = touch(self.game, "Launcher.exe")
        self.assertTrue(launch.launcher_hint(launcher, None, []).endswith("направь ярлык на exe игры."))


if __name__ == "__main__":
    unittest.main()

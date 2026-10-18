import itertools
import subprocess
import tempfile
import unittest
from unittest import mock

import redist


class Proc:
    def __init__(self, waits, code=0):
        self.pid = 4242
        self.waits = waits
        self.code = code

    def wait(self, timeout=None):
        if timeout is not None and self.waits > 0:
            self.waits -= 1
            raise subprocess.TimeoutExpired("proton", timeout)
        return self.code


class RunInstaller(unittest.TestCase):
    def setUp(self):
        self.log = mock.Mock()
        self.kill = mock.patch.object(redist.os, "killpg").start()
        mock.patch.object(redist.time, "time", side_effect=itertools.count()).start()
        self.addCleanup(mock.patch.stopall)

    def run_with(self, proc, alive=lambda: True):
        with mock.patch.object(redist.subprocess, "Popen", return_value=proc):
            return redist.run_installer("/proton", "x86.exe", ["/q"], {}, self.log, alive)

    def test_finished_installer_returns_its_code(self):
        self.assertEqual(self.run_with(Proc(waits=3, code=0)), 0)
        self.kill.assert_not_called()

    def test_closed_screen_stops_installer_at_once(self):
        self.assertEqual(self.run_with(Proc(waits=1000), alive=lambda: False), redist.SCREEN_LOST)
        self.kill.assert_called_once_with(4242, redist.signal.SIGKILL)

    def test_hung_installer_is_stopped_after_three_minutes(self):
        self.assertEqual(redist.TIMEOUT, 180)
        self.assertEqual(self.run_with(Proc(waits=1000)), "таймаут")
        self.kill.assert_called_once()

    def test_installer_inside_timeout_is_not_stopped(self):
        self.assertEqual(self.run_with(Proc(waits=redist.TIMEOUT - 5, code=0)), 0)
        self.kill.assert_not_called()


class ScreenEnv(unittest.TestCase):
    def steam(self, env, owner):
        return mock.patch.object(redist, "steam_screen", return_value=(env, owner))

    def test_screen_of_steam_is_used_and_watched(self):
        with self.steam({"DISPLAY": ":0"}, 100), mock.patch.dict(redist.os.environ, clear=True):
            self.assertEqual(redist.screen_env(), ({"DISPLAY": ":0"}, 100))

    def test_no_steam_no_screen(self):
        with self.steam(None, None), mock.patch.dict(redist.os.environ, clear=True):
            self.assertEqual(redist.screen_env(), (None, None))

    def test_own_screen_is_watched_through_its_steam(self):
        with self.steam({"DISPLAY": ":0"}, 100), mock.patch.dict(redist.os.environ, {"DISPLAY": ":0"}):
            self.assertEqual(redist.screen_env(), ({}, 100))

    def test_own_screen_of_other_steam_is_not_watched(self):
        with self.steam({"DISPLAY": ":1"}, 100), mock.patch.dict(redist.os.environ, {"DISPLAY": ":0"}):
            self.assertEqual(redist.screen_env(), ({}, None))

    def test_unknown_owner_is_always_alive(self):
        self.assertTrue(redist.steam_alive(None))


class WaitScreen(unittest.TestCase):
    def setUp(self):
        mock.patch.object(redist.time, "time", side_effect=itertools.count()).start()
        self.sleep = mock.patch.object(redist.time, "sleep").start()
        self.addCleanup(mock.patch.stopall)

    def test_new_steam_is_given_time_to_start(self):
        with mock.patch.object(redist, "steam_screen", side_effect=[(None, None), ({"DISPLAY": ":0"}, 200)]), \
                mock.patch.object(redist, "is_steam", return_value=True):
            self.assertEqual(redist.wait_screen(), ({"DISPLAY": ":0"}, 200))
        self.assertEqual(self.sleep.call_args_list[-1], mock.call(redist.SCREEN_SETTLE))

    def test_steam_that_closed_while_settling_is_skipped(self):
        screens = [({"DISPLAY": ":0"}, 100), ({"DISPLAY": ":0"}, 200)]
        with mock.patch.object(redist, "steam_screen", side_effect=screens), \
                mock.patch.object(redist, "is_steam", side_effect=[False, True]):
            self.assertEqual(redist.wait_screen(), ({"DISPLAY": ":0"}, 200))

    def test_gives_up_without_steam(self):
        with mock.patch.object(redist, "steam_screen", return_value=(None, None)):
            self.assertEqual(redist.wait_screen(), (None, None))


class EnsureScreenChange(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.done = False
        self.envs = []
        for name, value in (("COMPAT", self.tmp.name), ("LOGS", self.tmp.name)):
            mock.patch.object(redist, name, value).start()
        for name, value in (("busy", False), ("proton_dir", "/proton"), ("backup_prefix", None),
                            ("installer", (["x86.exe", "x64.exe"], None)), ("steam_launched", False),
                            ("stop_wine", True), ("read_registry", {})):
            mock.patch.object(redist, name, return_value=value).start()
        mock.patch.object(redist, "plan", return_value={"had": [], "absent": [], "todo": ["vc2022"],
                                                        "stuck": []}).start()
        mock.patch.object(redist, "installed", side_effect=lambda *a: self.done).start()
        mock.patch.object(redist, "screen_env", return_value=({"DISPLAY": ":0", "XAUTHORITY": "/old"}, 100)).start()
        self.kill = mock.patch.object(redist, "kill_wine", return_value=True).start()
        self.addCleanup(mock.patch.stopall)

    def installers(self, *codes):
        codes = iter(codes)

        def run(proton, exe, args, env, log, alive):
            self.envs.append((exe, env["DISPLAY"], env.get("XAUTHORITY")))
            code = next(codes)
            self.done = code == 0 and exe == "x64.exe"
            return code
        return mock.patch.object(redist, "run_installer", side_effect=run)

    def ensure(self):
        return redist.ensure(1, "proton", ["228989"], {"vc2022": 1}, 3, say=lambda t: None)

    def test_reinstalls_on_new_screen(self):
        with self.installers(redist.SCREEN_LOST, 0, 0), \
                mock.patch.object(redist, "wait_screen", return_value=({"DISPLAY": ":1"}, 200)):
            result = self.ensure()
        self.assertEqual(self.envs, [("x86.exe", ":0", "/old"), ("x86.exe", ":1", None), ("x64.exe", ":1", None)])
        self.kill.assert_called_once()
        self.assertEqual((result["done"], result["failed"], result["skipped"]), (["vc2022"], [], None))

    def test_no_new_screen_is_not_a_failure(self):
        with self.installers(redist.SCREEN_LOST), mock.patch.object(redist, "wait_screen", return_value=(None, None)):
            result = self.ensure()
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["tries"], {"vc2022": 1})
        self.assertEqual(result["skipped"], "экран Steam закрылся во время установки — поставлю при следующем запуске")

    def test_game_started_while_screen_changed_is_not_killed(self):
        self.kill.return_value = False
        with self.installers(redist.SCREEN_LOST), mock.patch.object(redist, "wait_screen") as wait:
            result = self.ensure()
        wait.assert_not_called()
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["skipped"], "игру запустили во время установки — проверю, когда закроется")

    def test_endless_screen_changes_give_up(self):
        lost = [redist.SCREEN_LOST] * (redist.SCREEN_CHANGES + 1)
        with self.installers(*lost), mock.patch.object(redist, "wait_screen", return_value=({"DISPLAY": ":1"}, 200)):
            result = self.ensure()
        self.assertEqual(len(self.envs), redist.SCREEN_CHANGES + 1)
        self.assertEqual(result["failed"], [])
        self.assertTrue(result["skipped"].startswith("экран Steam закрылся"))

    def test_ordinary_failure_still_counts(self):
        with self.installers(1, 1), mock.patch.object(redist, "wait_screen") as wait:
            result = self.ensure()
        wait.assert_not_called()
        self.assertEqual((result["failed"], result["tries"]), (["vc2022"], {"vc2022": 2}))


if __name__ == "__main__":
    unittest.main()

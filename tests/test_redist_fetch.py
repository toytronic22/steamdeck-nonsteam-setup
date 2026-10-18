import itertools
import os
import tempfile
import unittest
from unittest import mock

import main
import redist
from steamcdp import JsError, SteamUnavailable

VC2010 = ["vcredist/2010", "vcredist_x86.exe", "vcredist_x64.exe"]
OPENAL = ["OpenAL/2.0.7.0", "oalinst.exe"]


class FakeSteam:
    def __init__(self, root):
        self.root = root
        self.log = os.path.join(root, "console_log.txt")
        self.commands = []
        self.answers = []
        with open(self.log, "w") as f:
            f.write("[2026-10-03 15:00:00] old line\n")

    def write(self, *lines):
        with open(self.log, "a") as f:
            for line in lines:
                f.write(f"[2026-10-03 15:00:01] {line}\n")

    def put(self, depot, folder, *files):
        path = os.path.join(self.root, "content", "app_228980", f"depot_{depot}", "_CommonRedist", folder)
        os.makedirs(path, exist_ok=True)
        for name in files:
            open(os.path.join(path, name), "w").close()

    def complete(self, depot, folder, *files):
        self.put(depot, folder, *files)
        self.write(f"Downloading depot {depot} (2 files, 1 MB) ... ",
                   f'Depot download complete : "/x/ubuntu12_32\\steamapps\\content\\app_228980\\depot_{depot}" (manifest 1) ')

    def __call__(self, command):
        self.commands.append(command)
        if self.answers:
            self.answers.pop(0)()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.steam = FakeSteam(self.tmp.name)
        self.naps = itertools.count()
        for p in (mock.patch.object(redist, "CONSOLE_LOG", self.steam.log),
                  mock.patch.object(redist, "SHARED", os.path.join(self.tmp.name, "none")),
                  mock.patch.object(redist, "DEPOT_DOWNLOADS", [os.path.join(self.tmp.name, "content", "app_228980")]),
                  mock.patch.object(redist, "COMPAT", os.path.join(self.tmp.name, "compatdata")),
                  mock.patch.dict(redist.PACKAGES["physx"], variants=[(os.path.join(self.tmp.name, "PhysX"), None)]),
                  mock.patch.object(redist.time, "sleep", side_effect=self.nap),
                  mock.patch.object(redist.time, "time", side_effect=itertools.count())):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def nap(self, seconds):
        if next(self.naps) > 100000:
            raise AssertionError("ожидание не кончается")


class Fetch(Base):
    def test_downloads_and_finds_installer(self):
        self.steam.answers = [lambda: self.steam.complete("228983", *VC2010)]
        got, errors = redist.fetch(["vc2010"], self.steam, say=lambda t: None)
        self.assertEqual((got, errors), (["vc2010"], {}))
        self.assertEqual(self.steam.commands, ["download_depot 228980 228983"])
        self.assertIsNotNone(redist.installer("vc2010"))

    def test_failure_line_gives_reason(self):
        self.steam.answers = [lambda: self.steam.write("Depot download failed : No connection")]
        got, errors = redist.fetch(["vc2010"], self.steam, say=lambda t: None)
        self.assertEqual((got, errors), ([], {"vc2010": "No connection"}))

    def test_timeout_when_steam_is_silent(self):
        with mock.patch.object(redist.time, "time", side_effect=[0, 0, 400]):
            got, errors = redist.fetch(["vc2010"], self.steam, say=lambda t: None, timeout=300)
        self.assertEqual((got, errors), ([], {"vc2010": "Steam не скачал за 5 мин"}))

    def test_waits_until_line_appears(self):
        polls = iter([lambda: None, lambda: None, lambda: self.steam.complete("228983", *VC2010)])
        with mock.patch.object(redist.time, "sleep", side_effect=lambda s: next(polls)()):
            got, errors = redist.fetch(["vc2010"], self.steam, say=lambda t: None)
        self.assertEqual((got, errors), (["vc2010"], {}))

    def test_old_failure_does_not_count(self):
        self.steam.write("Depot download failed : old failure")
        self.steam.answers = [lambda: self.steam.complete("228983", *VC2010)]
        got, errors = redist.fetch(["vc2010"], self.steam, say=lambda t: None)
        self.assertEqual((got, errors), (["vc2010"], {}))

    def test_old_complete_does_not_count(self):
        self.steam.write('Depot download complete : "/x/app_228980\\depot_228983" (manifest 1) ')
        self.steam.answers = [lambda: self.steam.write("Depot download failed : No connection")]
        got, errors = redist.fetch(["vc2010"], self.steam, say=lambda t: None)
        self.assertEqual((got, errors), ([], {"vc2010": "No connection"}))

    def test_other_depot_does_not_end_wait(self):
        self.steam.answers = [lambda: self.steam.complete("228981", "vcredist/2005", "vcredist_x86.exe")]
        polls = iter([lambda: self.steam.complete("228983", *VC2010)])
        with mock.patch.object(redist.time, "sleep", side_effect=lambda s: next(polls)()):
            got, errors = redist.fetch(["vc2010"], self.steam, say=lambda t: None)
        self.assertEqual((got, errors), (["vc2010"], {}))

    def test_rotated_log_is_read_from_start(self):
        def rotate():
            with open(self.steam.log, "w"):
                pass
            self.steam.complete("228983", *VC2010)
        self.steam.write("x" * 5000)
        self.steam.answers = [rotate]
        got, errors = redist.fetch(["vc2010"], self.steam, say=lambda t: None)
        self.assertEqual((got, errors), (["vc2010"], {}))

    def test_complete_without_installer_is_an_error(self):
        self.steam.answers = [lambda: self.steam.write(
            'Depot download complete : "/x/app_228980\\depot_228983" (manifest 1) ')]
        got, errors = redist.fetch(["vc2010"], self.steam, say=lambda t: None)
        self.assertEqual((got, errors), ([], {"vc2010": "скачал, но установщика в пакете нет"}))

    def test_stale_steam_state_does_not_fake_download(self):
        content = os.path.join(self.tmp.name, "content", "app_228980")
        os.makedirs(os.path.join(content, "depot_228983"))
        patch = os.path.join(content, "state_228980_228983.patch")
        open(patch, "w").close()

        def steam():
            if os.path.exists(patch):
                self.steam.write('Depot download complete : "/x/app_228980\\depot_228983" (manifest 1) ')
            else:
                self.steam.complete("228983", *VC2010)

        self.steam.answers = [steam]
        got, errors = redist.fetch(["vc2010"], self.steam, say=lambda t: None)
        self.assertEqual((got, errors), (["vc2010"], {}))

    def test_one_package_at_a_time(self):
        def first():
            self.assertEqual(len(self.steam.commands), 1)
            self.steam.write("Depot download failed : Missing configuration")

        self.steam.answers = [first, lambda: self.steam.complete("229020", *OPENAL)]
        got, errors = redist.fetch(["vc2010", "openal"], self.steam, say=lambda t: None)
        self.assertEqual(self.steam.commands, ["download_depot 228980 228983", "download_depot 228980 229020"])
        self.assertEqual((got, errors), (["openal"], {"vc2010": "Missing configuration"}))

    def test_present_and_unfetchable_are_skipped(self):
        self.steam.put("228983", *VC2010)
        got, errors = redist.fetch(["vc2010", "physx"], self.steam, say=lambda t: None)
        self.assertEqual((got, errors, self.steam.commands), ([], {}, []))

    def test_says_what_it_downloads(self):
        said = []
        self.steam.answers = [lambda: self.steam.complete("228983", *VC2010)]
        redist.fetch(["vc2010"], self.steam, say=said.append)
        self.assertEqual(said, ["скачиваю Visual C++ 2010 через Steam…"])


class Ensure(Base):
    def setUp(self):
        super().setUp()
        for p in (mock.patch.object(redist, "ALWAYS", []), mock.patch.object(redist, "busy", return_value=False)):
            p.start()
            self.addCleanup(p.stop)
        self.calls = []

    def download(self, got, errors=None):
        def run(keys):
            self.calls.append(keys)
            for key in got:
                self.steam.put("228983", *VC2010)
            return got, errors or {}
        return run

    def test_fetched_package_goes_to_install(self):
        result = redist.ensure(1, None, ["228983"], download=self.download(["vc2010"]))
        self.assertEqual(self.calls, [["vc2010"]])
        self.assertEqual(result["fetched"], ["vc2010"])
        self.assertEqual((result["absent"], result["todo"]), ([], ["vc2010"]))
        self.assertEqual(result["skipped"], "у игры не выбран Proton")

    def test_success_clears_fetch_tries(self):
        result = redist.ensure(1, None, ["228983"], {"fetch:vc2010": 2}, 3, download=self.download(["vc2010"]))
        self.assertNotIn("fetch:vc2010", result["tries"])

    def test_failure_counts_try(self):
        result = redist.ensure(1, None, ["228983"], {"fetch:vc2010": 1}, 3,
                               download=self.download([], {"vc2010": "No connection"}))
        self.assertEqual(result["tries"]["fetch:vc2010"], 2)
        self.assertEqual(result["absent"], ["vc2010"])
        self.assertEqual(result["fetch_errors"], {"vc2010": "No connection"})

    def test_auto_stops_after_max_tries(self):
        redist.ensure(1, None, ["228983"], {"fetch:vc2010": 3}, 3, download=self.download([]), retry_fetch=False)
        self.assertEqual(self.calls, [])

    def test_button_retries_after_max_tries(self):
        redist.ensure(1, None, ["228983"], {"fetch:vc2010": 3}, 3, download=self.download([]), retry_fetch=True)
        self.assertEqual(self.calls, [["vc2010"]])

    def test_physx_is_not_downloaded(self):
        result = redist.ensure(1, None, ["229033"], download=self.download([]))
        self.assertEqual(self.calls, [])
        self.assertEqual(result["absent"], ["physx"])

    def test_nothing_absent_nothing_downloaded(self):
        self.steam.put("228983", *VC2010)
        redist.ensure(1, None, ["228983"], download=self.download([]))
        self.assertEqual(self.calls, [])

    def test_without_download_only_plans(self):
        result = redist.ensure(1, None, ["228983"])
        self.assertEqual((result["absent"], result["fetched"], result["fetch_errors"]), (["vc2010"], [], {}))


class RedistPass(Base):
    def setUp(self):
        super().setUp()
        for p in (mock.patch.object(redist, "ALWAYS", []), mock.patch.object(redist, "busy", return_value=False),
                  mock.patch.object(main, "save_state"), mock.patch.object(main, "compat_tool_in_config",
                                                                           return_value=None),
                  mock.patch.object(main, "print", create=True)):
            p.start()
            self.addCleanup(p.stop)
        self.calls = []
        self.shortcuts = [{"appid": 5, "name": "Far Cry Primal", "exe": "/g/fc.exe"}]

    def state(self, tries=None):
        return {"done": {"5": {"orig": 371660, "redist": {
            "depots": ["228983"], "local": [], "checks": redist.LOCAL_CHECKS, "exe": "/g/fc.exe",
            "tries": dict(tries or {})}}}}

    def run_pass(self, state, auto, ok=True, progress=None):
        def download(keys):
            self.calls.append(keys)
            if ok:
                self.steam.put("228983", *VC2010)
                return keys, {}
            return [], {k: "No connection" for k in keys}
        args = mock.Mock(appid=None, auto=auto)
        return main.redist_pass(state, self.shortcuts, set(), args, progress or mock.Mock(), download)

    def test_button_downloads_for_done_game(self):
        blocks = self.run_pass(self.state(), auto=False)
        self.assertEqual(self.calls, [["vc2010"]])
        self.assertEqual(len(blocks), 1)
        self.assertTrue(blocks[0].startswith("✓ Far Cry Primal\n   библиотеки: скачал через Steam Visual C++ 2010"),
                        blocks[0])

    def test_failure_is_reported_and_counted(self):
        state = self.state()
        blocks = self.run_pass(state, auto=False, ok=False)
        self.assertEqual(blocks, ["✗ Far Cry Primal\n   библиотеки: Visual C++ 2010 не скачал через Steam: No connection"])
        self.assertEqual(state["done"]["5"]["redist"]["tries"], {"fetch:vc2010": 1})
        main.save_state.assert_called()

    def test_auto_gives_up_after_max_tries(self):
        progress = mock.Mock()
        blocks = self.run_pass(self.state({"fetch:vc2010": main.AUTO_TRIES}), auto=True, progress=progress)
        self.assertEqual((self.calls, blocks), ([], []))
        progress.say.assert_not_called()

    def test_auto_gives_up_even_when_other_package_waits(self):
        self.steam.put("228981", "vcredist/2005", "vcredist_x86.exe", "vcredist_x64.exe")
        state = self.state({"fetch:vc2010": main.AUTO_TRIES})
        state["done"]["5"]["redist"]["depots"] = ["228983", "228981"]
        self.run_pass(state, auto=True)
        self.assertEqual(self.calls, [])

    def test_auto_tries_before_max(self):
        self.run_pass(self.state({"fetch:vc2010": main.AUTO_TRIES - 1}), auto=True)
        self.assertEqual(self.calls, [["vc2010"]])

    def test_button_tries_after_max(self):
        self.run_pass(self.state({"fetch:vc2010": main.AUTO_TRIES}), auto=False)
        self.assertEqual(self.calls, [["vc2010"]])


class Texts(unittest.TestCase):
    def result(self, **kw):
        base = {"had": [], "absent": [], "todo": [], "stuck": [], "done": [], "failed": [], "skipped": None,
                "log": None, "fetched": [], "fetch_errors": {}}
        base.update(kw)
        return base

    def test_fetched_and_installed(self):
        text = redist.describe(self.result(fetched=["vc2010"], done=["vc2010"]))
        self.assertEqual(text, "скачал через Steam Visual C++ 2010; поставил Visual C++ 2010")

    def test_fetch_error_named_once(self):
        text = redist.describe(self.result(absent=["vc2010"], fetch_errors={"vc2010": "No connection"}))
        self.assertEqual(text, "Visual C++ 2010 не скачал через Steam: No connection")

    def test_absent_without_try_promises_fetch(self):
        text = redist.describe(self.result(absent=["vc2010"]))
        self.assertEqual(text, "нет на деке: Visual C++ 2010; скачаю через Steam при следующем запуске")

    def test_no_console_commands_anywhere(self):
        for keys in (["vc2010"], ["vc2022", "directx", "openal"], ["physx", "vc2005"]):
            for text in (redist.describe(self.result(absent=keys)), redist.status(self.result(absent=keys))):
                self.assertNotIn("download_depot", text)
                self.assertNotIn("консол", text)


class MainFetcher(unittest.TestCase):
    def setUp(self):
        self.progress = mock.Mock()
        p = mock.patch.object(main, "print", create=True)
        p.start()
        self.addCleanup(p.stop)

    def test_failure_is_remembered_for_the_run(self):
        fetcher = main.Fetcher(self.progress)
        with mock.patch.object(main, "Cdp", mock.MagicMock()), \
                mock.patch.object(redist, "fetch", return_value=([], {"vc2010": "No connection"})) as fetch:
            first = fetcher(["vc2010"])
            second = fetcher(["vc2010"])
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(first, ([], {"vc2010": "No connection"}))
        self.assertEqual(second, first)

    def test_new_package_is_still_tried(self):
        fetcher = main.Fetcher(self.progress)
        fetcher.errors = {"vc2010": "No connection"}
        with mock.patch.object(main, "Cdp", mock.MagicMock()), \
                mock.patch.object(redist, "fetch", return_value=(["openal"], {})) as fetch:
            got, errors = fetcher(["vc2010", "openal"])
        self.assertEqual(fetch.call_args[0][0], ["openal"])
        self.assertEqual((got, errors), (["openal"], {"vc2010": "No connection"}))

    def test_steam_unavailable(self):
        with mock.patch.object(main, "Cdp", side_effect=SteamUnavailable("closed")):
            got, errors = main.Fetcher(self.progress)(["vc2010", "openal"])
        self.assertEqual((got, errors), ([], {"vc2010": "нет связи со Steam", "openal": "нет связи со Steam"}))

    def test_js_error(self):
        cdp = mock.MagicMock()
        cdp.__enter__.return_value.call.side_effect = JsError("no Console")
        with mock.patch.object(main, "Cdp", return_value=cdp), \
                mock.patch.object(redist, "installer", return_value=None):
            got, errors = main.Fetcher(self.progress)(["vc2010"])
        self.assertEqual(got, [])
        self.assertTrue(errors["vc2010"].startswith("Steam вернул ошибку: "), errors)

    def test_command_goes_to_steam_console(self):
        cdp = mock.MagicMock()
        steam = cdp.__enter__.return_value

        def fake_fetch(keys, command, say):
            command("download_depot 228980 228983")
            return [], {}

        with mock.patch.object(main, "Cdp", return_value=cdp), mock.patch.object(redist, "fetch", fake_fetch):
            main.Fetcher(self.progress)(["vc2010"])
        steam.call.assert_called_once_with("cmd => SteamClient.Console.ExecCommand(cmd)",
                                           "download_depot 228980 228983")


if __name__ == "__main__":
    unittest.main()

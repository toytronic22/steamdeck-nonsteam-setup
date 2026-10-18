import os
import tempfile
import unittest
from unittest import mock

import main
import redist
import steamweb
import vdf
from steamcdp import JsError, SteamUnavailable

ANSWER = '''[2026-10-03 16:39:43] AppID : 1144200, change number : 1/1, last change : Sat Oct  3 16:34:50 2026
[2026-10-03 16:39:43] "1144200"
{
\t"config"
\t{
\t\t"launch"
\t\t{
\t\t\t"5"
\t\t\t{
\t\t\t\t"executable"\t\t"Binaries\\\\Game.exe"
\t\t\t\t"config"
\t\t\t\t{
\t\t\t\t\t"BetaKey"\t\t"legacy"
\t\t\t\t}
\t\t\t}
\t\t}
\t}
\t"depots"
\t{
\t\t"228990"
\t\t{
\t\t\t"depotfromapp"\t\t"228980"
\t\t}
\t\t"1144201"
\t\t{
\t\t\t"maxsize"\t\t"1"
\t\t}
\t}
}
'''
WEB = {"data": {"1144200": {"depots": {"229007": {"depotfromapp": "228980"}}}}}


class ParseText(unittest.TestCase):
    def test_nested_block_with_escapes(self):
        self.assertEqual(vdf.parse_text_block('"1"\n{\n\t"a"\t\t"x\\\\y \\"q\\""\n\t"b"\n\t{\n\t\t"c"\t\t""\n\t}\n}\n"tail"'),
                         {"a": 'x\\y "q"', "b": {"c": ""}})

    def test_unfinished_block_is_not_an_answer(self):
        self.assertIsNone(vdf.parse_text_block('"1"\n{\n\t"a"\t\t"x"\n'))

    def test_empty_block(self):
        self.assertEqual(vdf.parse_text_block('"1"\n{\n}\n'), {})


class SteamConsole(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, "console_log.txt")
        with open(self.log, "w") as f:
            f.write("[2026-10-03 16:00:00] old line\n" * 50)
        patch = mock.patch.object(redist, "CONSOLE_LOG", self.log)
        patch.start()
        self.addCleanup(patch.stop)
        self.commands = []

    def tearDown(self):
        self.tmp.cleanup()

    def console(self, text, mode="a"):
        def run(command):
            self.commands.append(command)
            with open(self.log, mode) as f:
                f.write(text)
        return run

    def test_reads_answer_from_console(self):
        info = steamweb.steam_app_info(1144200, self.console(ANSWER))
        self.assertEqual(self.commands, ["app_info_print 1144200"])
        self.assertEqual(info["config"]["launch"]["5"]["executable"], "Binaries\\Game.exe")
        self.assertEqual(info["depots"]["228990"], {"depotfromapp": "228980"})

    def test_log_restarted_in_the_middle_of_answer(self):
        rest = ANSWER.split("\n", 1)[1]
        info = steamweb.steam_app_info(1144200, self.console(rest, mode="w"))
        self.assertIn("228990", info["depots"])

    def test_silent_steam_gives_up(self):
        self.assertIsNone(steamweb.steam_app_info(1144200, self.console(""), timeout=0.3, poll=0.05))

    def test_answer_about_other_game_is_ignored(self):
        other = ANSWER.replace('"1144200"', '"292030"')
        self.assertIsNone(steamweb.steam_app_info(1144200, self.console(other), timeout=0.3, poll=0.05))


class Sources(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.dict(steamweb._app_info, clear=True),
                  mock.patch.object(steamweb, "get_json", return_value=WEB)):
            self.web = p.start()
            self.addCleanup(p.stop)

    def depots(self, steam):
        with mock.patch.object(steamweb, "steam_app_info", **steam):
            return steamweb.shared_depots(1144200, console=lambda c: None)

    def test_steam_answer_is_enough(self):
        parsed = vdf.parse_text_block(ANSWER.split("\n", 1)[1])
        self.assertEqual(self.depots({"return_value": parsed}), ["228990"])
        self.web.assert_not_called()

    def test_keys_ignore_case(self):
        with mock.patch.object(steamweb, "steam_app_info", return_value=vdf.parse_text_block(ANSWER.split("\n", 1)[1])):
            info = steamweb.app_info(1144200, console=lambda c: None)
        self.assertEqual(info["config"]["launch"]["5"]["config"], {"betakey": "legacy"})

    def test_web_when_steam_knows_nothing(self):
        self.assertEqual(self.depots({"return_value": {}}), ["229007"])

    def test_web_when_steam_fails(self):
        self.assertEqual(self.depots({"side_effect": JsError("boom")}), ["229007"])

    def test_web_only_without_console(self):
        with mock.patch.object(steamweb, "steam_app_info") as steam:
            self.assertEqual(steamweb.shared_depots(1144200), ["229007"])
        steam.assert_not_called()

    def test_redist_pass_asks_web_when_steam_is_closed(self):
        with mock.patch.object(main, "Cdp", side_effect=SteamUnavailable("closed")):
            self.assertEqual(main.original_depots(1144200), ["229007"])


if __name__ == "__main__":
    unittest.main()

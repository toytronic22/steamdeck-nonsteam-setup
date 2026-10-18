import os
import tempfile
import unittest
from unittest import mock

import main

LOGIN = """"users"
{
	"76561198000000001"
	{
		"AccountName"		"other"
		"MostRecent"		"0"
	}
	"%s"
	{
		"AccountName"		"me"
		"MostRecent"		"1"
	}
}
"""


class FindUserDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.steam = self.tmp.name
        patch = mock.patch.object(main, "STEAM", self.steam)
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def user(self, uid, shortcuts_mtime=None):
        config = os.path.join(self.steam, "userdata", uid, "config")
        os.makedirs(config, exist_ok=True)
        if shortcuts_mtime is not None:
            path = os.path.join(config, "shortcuts.vdf")
            open(path, "wb").close()
            os.utime(path, (shortcuts_mtime, shortcuts_mtime))

    def login(self, steamid):
        os.makedirs(os.path.join(self.steam, "config"), exist_ok=True)
        with open(os.path.join(self.steam, "config", "loginusers.vdf"), "w") as f:
            f.write(LOGIN % steamid)

    def test_most_recent_login_wins(self):
        self.user("123456789")
        self.user("111", shortcuts_mtime=2_000_000_000)
        self.login(str(76561197960265728 + 123456789))
        self.assertEqual(main.recent_login(), "123456789")
        self.assertEqual(main.find_user_dir(), "123456789")

    def test_without_login_file_freshest_shortcuts(self):
        self.user("111", shortcuts_mtime=1_000_000_000)
        self.user("222", shortcuts_mtime=1_500_000_000)
        self.user("333")
        self.assertEqual(main.find_user_dir(), "222")

    def test_recent_login_without_userdata_falls_back(self):
        self.user("111", shortcuts_mtime=1_000_000_000)
        self.login(str(76561197960265728 + 999))
        self.assertEqual(main.find_user_dir(), "111")

    def test_skips_zero_and_names(self):
        self.user("0", shortcuts_mtime=2_000_000_000)
        self.user("anonymous", shortcuts_mtime=2_000_000_000)
        self.assertIsNone(main.find_user_dir())
        self.user("5")
        self.assertEqual(main.find_user_dir(), "5")

    def test_no_steam(self):
        self.assertEqual(main.steam_users(), [])
        self.assertIsNone(main.recent_login())
        self.assertIsNone(main.find_user_dir())

    def test_missing_shortcuts_file(self):
        self.assertEqual(main.read_shortcuts(os.path.join(self.steam, "nope", "shortcuts.vdf")), [])


if __name__ == "__main__":
    unittest.main()

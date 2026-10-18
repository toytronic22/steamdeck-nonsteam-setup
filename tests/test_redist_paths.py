import os
import tempfile
import unittest
from unittest import mock

import redist


class DepotPaths(unittest.TestCase):
    def test_steam_download_folder_is_searched_first(self):
        steam = os.path.join(os.path.expanduser("~"), ".local/share/Steam")
        self.assertEqual(redist.DEPOT_DOWNLOADS[0], os.path.join(steam, "ubuntu12_32/steamapps/content/app_228980"))


class DepotDownloads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.steam = self.tmp.name
        for p in (mock.patch.object(redist, "SHARED", os.path.join(self.steam, "steamapps", "common", "none")),
                  mock.patch.object(redist, "DEPOT_DOWNLOADS", [
                      os.path.join(self.steam, "ubuntu12_32", "steamapps", "content", "app_228980"),
                      os.path.join(self.steam, "steamapps", "content", "app_228980")])):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, *parts):
        path = os.path.join(self.steam, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").close()
        return path

    def test_vc2005_found_in_ubuntu12_32_download(self):
        folder = ("ubuntu12_32", "steamapps", "content", "app_228980", "depot_228981", "_CommonRedist", "vcredist", "2005")
        x86 = self.put(*folder, "vcredist_x86.exe")
        x64 = self.put(*folder, "vcredist_x64.exe")
        found = redist.installer("vc2005")
        self.assertIsNotNone(found)
        self.assertEqual(found[0], [x86, x64])

    def test_old_location_still_works(self):
        folder = ("steamapps", "content", "app_228980", "depot_228981", "_CommonRedist", "vcredist", "2005")
        self.put(*folder, "vcredist_x86.exe")
        self.put(*folder, "vcredist_x64.exe")
        self.assertIsNotNone(redist.installer("vc2005"))

    def test_nothing_downloaded(self):
        self.assertIsNone(redist.installer("vc2005"))


if __name__ == "__main__":
    unittest.main()

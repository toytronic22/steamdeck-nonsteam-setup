import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import redist
from steamcdp import Cdp, SteamUnavailable
from tests.test_install import free_port


def serve(body):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class Connect(unittest.TestCase):
    def check(self, body):
        server = serve(body)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with mock.patch.dict(os.environ, {"NONSTEAM_CDP_PORT": str(server.server_port)}):
            with self.assertRaises(SteamUnavailable):
                Cdp(timeout=2)

    def test_closed_port(self):
        with mock.patch.dict(os.environ, {"NONSTEAM_CDP_PORT": str(free_port())}):
            with self.assertRaises(SteamUnavailable):
                Cdp(timeout=2)

    def test_not_json(self):
        self.check(b"<html>hello</html>")

    def test_not_a_list(self):
        self.check(b'{"title": "SharedJSContext"}')

    def test_no_steam_context(self):
        self.check(b'[{"title": "Steam Big Picture Mode"}]')


class Hint(unittest.TestCase):
    def test_physx_hint_points_to_nvidia_and_folder(self):
        hint = redist.fetch_hint(["physx"])
        self.assertIn("NVIDIA", hint)
        self.assertIn("PhysX_9.23.1019_SystemSoftware.exe", hint)
        self.assertIn("~/.local/share/nonsteam-setup/redist/PhysX", hint)
        self.assertNotIn("download_depot", hint)

    def test_nothing_to_fetch(self):
        self.assertEqual(redist.fetch_hint([]), "")

    def test_depot_and_physx_together(self):
        hint = redist.fetch_hint(["vc2022", "physx"])
        self.assertTrue(hint.startswith("скачаю через Steam при следующем запуске; PhysX: "), hint)
        self.assertNotIn("download_depot", hint)


if __name__ == "__main__":
    unittest.main()

import io
import json
import os
import pty
import select
import shutil
import socket
import subprocess
import tarfile
import tempfile
import threading
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIPPED = ["install.sh", "uninstall.sh", "get.sh", "run.sh", "VERSION", "assets"]

FAKE_SYSTEMCTL = """#!/bin/bash
echo "$*" >> "$HOME/systemctl.log"
[ "$2" = show-environment ] && [ -n "${FAKE_NO_SYSTEMD:-}" ] && exit 1
exit 0
"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class OpenPort:
    def __init__(self):
        self.srv = socket.create_server(("127.0.0.1", 0))
        self.srv.settimeout(0.2)
        self.port = self.srv.getsockname()[1]
        self.done = False
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        while not self.done:
            try:
                conn, _ = self.srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(5)
                head = b""
                while b"\r\n\r\n" not in head:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    head += chunk
                if head.startswith(b"GET /json "):
                    body = json.dumps([{"title": "SharedJSContext",
                                        "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.port}/devtools/page/1"}]).encode()
                    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n"
                                 b"Connection: close\r\n\r\n" % len(body) + body)
                elif b"websocket" in head.lower():
                    conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")

    def close(self):
        self.done = True
        self.thread.join(5)
        self.srv.close()


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.bin = os.path.join(self.tmp.name, "bin")
        self.steam = os.path.join(self.home, ".local/share/Steam")
        self.data = os.path.join(self.home, ".local/share/nonsteam-setup")
        self.app = os.path.join(self.data, "app")
        self.units = os.path.join(self.home, ".config/systemd/user")
        self.flag = os.path.join(self.steam, ".cef-enable-remote-debugging")
        self.ours = os.path.join(self.data, "port-flag-created")
        self.desktop = os.path.join(self.home, ".local/share/applications/nonsteam-setup.desktop")
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "systemctl"), "w") as f:
            f.write(FAKE_SYSTEMCTL)
        os.chmod(os.path.join(self.bin, "systemctl"), 0o755)
        os.makedirs(os.path.join(self.home, "Desktop"))
        self.user("123456789")

    def tearDown(self):
        self.tmp.cleanup()

    def user(self, uid):
        os.makedirs(os.path.join(self.steam, "userdata", uid, "config"), exist_ok=True)

    def env(self, **extra):
        env = {"HOME": self.home, "PATH": self.bin + os.pathsep + os.environ["PATH"],
               "NONSTEAM_CDP_PORT": str(free_port()), "NONSTEAM_LANG": "ru", "TMPDIR": self.tmp.name}
        env.update(extra)
        return {k: v for k, v in env.items() if v is not None}

    def run_sh(self, args, cwd=REPO, stdin=None, **extra):
        done = subprocess.run(["bash"] + args, cwd=cwd, env=self.env(**extra), input=stdin,
                              capture_output=True, text=True, timeout=60, start_new_session=True)
        return done.returncode, done.stdout + done.stderr

    def install(self, *args, **extra):
        return self.run_sh([os.path.join(REPO, "install.sh")] + list(args), **extra)

    def uninstall(self, *args, **extra):
        return self.run_sh([os.path.join(self.app, "uninstall.sh")] + list(args), **extra)

    def in_tty(self, command, answers, **extra):
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(REPO)
            os.execvpe("bash", ["bash", "-c", command], self.env(**extra))
        out, sent, deadline = b"", 0, time.time() + 60
        while time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if ready:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
            while sent < len(answers) and out.count(b"[y/N]") + out.count(b"[Y/n]") > sent:
                os.write(fd, answers[sent].encode() + b"\n")
                sent += 1
        os.close(fd)
        _, status = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(status), out.decode("utf-8", "replace")

    def systemctl_log(self):
        path = os.path.join(self.home, "systemctl.log")
        return read_text(path) if os.path.exists(path) else ""


class Install(Sandbox):
    def test_fresh_install_without_port(self):
        self.user("0")
        self.user("abc")
        self.user("12345")
        code, out = self.install("--no-port")
        self.assertEqual(code, 0, out)
        for name in ("main.py", "layouts.py", "add_to_steam.py", "update.py", "uninstall.sh", "run.sh", "VERSION",
                     "assets/icon.png", "assets/poster.jpg"):
            self.assertTrue(os.path.exists(os.path.join(self.app, name)), name)
        self.assertFalse(os.path.exists(os.path.join(self.app, "tests")))
        self.assertFalse(os.path.exists(os.path.join(self.app, "get.sh")))
        self.assertTrue(os.access(os.path.join(self.app, "run.sh"), os.X_OK))
        self.assertTrue(os.access(os.path.join(self.app, "uninstall.sh"), os.X_OK))
        path_unit = read_text(os.path.join(self.units, "nonsteam-setup.path"))
        watched = [line for line in path_unit.splitlines() if line.startswith("PathChanged=")]
        self.assertEqual(sorted(watched), sorted(
            f"PathChanged={self.steam}/userdata/{u}/config/shortcuts.vdf" for u in ("12345", "123456789")))
        for unit in ("nonsteam-setup.service", "nonsteam-layouts.service"):
            self.assertIn(self.app, read_text(os.path.join(self.units, unit)), unit)
        log = self.systemctl_log()
        for call in ("--user daemon-reload", "--user enable --now nonsteam-setup.timer",
                     "--user restart nonsteam-layouts.service", "--user restart nonsteam-setup.path"):
            self.assertIn(call, log)
        self.assertIn(f"Exec={self.app}/run.sh", read_text(self.desktop))
        self.assertTrue(os.path.exists(os.path.join(self.home, "Desktop/nonsteam-setup.desktop")))
        self.assertFalse(os.path.exists(self.flag))
        self.assertIn("любая программа на этом устройстве", out)
        self.assertIn("«Удалённая отладка CEF»", out)
        self.assertIn("Порт не включён", out)
        self.assertIn("Нет связи со Steam", out)
        self.assertTrue(os.path.exists(os.path.join(self.data, "button-pending")))
        self.assertIn("установлена версия " + read_text(os.path.join(REPO, "VERSION")).strip(), out)
        self.assertIn(f"bash {self.app}/uninstall.sh", out)

    def test_no_terminal_means_no(self):
        code, out = self.install()
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(self.flag))
        self.assertIn("Порт не включён", out)
        self.assertNotIn("[y/N]", out)
        self.assertNotIn("/dev/tty", out)

    def test_enable_port_flag(self):
        code, out = self.install("--enable-port")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.exists(self.flag))
        self.assertTrue(os.path.exists(self.ours))
        self.assertIn("Порт включён", out)
        code, out = self.install()
        self.assertEqual(code, 0, out)
        self.assertIn("откроется после перезапуска Steam", out)
        self.assertNotIn("любая программа", out)

    def test_question_yes_in_terminal(self):
        code, out = self.in_tty(f"bash {REPO}/install.sh", ["y"])
        self.assertEqual(code, 0, out)
        self.assertIn("Включить порт сейчас? [y/N]", out)
        self.assertTrue(os.path.exists(self.flag))
        self.assertTrue(os.path.exists(self.ours))

    def test_question_default_is_no(self):
        code, out = self.in_tty(f"bash {REPO}/install.sh", [""])
        self.assertEqual(code, 0, out)
        self.assertIn("[y/N]", out)
        self.assertFalse(os.path.exists(self.flag))
        self.assertFalse(os.path.exists(self.ours))

    def open_port(self):
        port = OpenPort()
        self.addCleanup(port.close)
        return str(port.port)

    def test_open_port_with_flag(self):
        open(self.flag, "w").close()
        code, out = self.install(NONSTEAM_CDP_PORT=self.open_port())
        self.assertEqual(code, 0, out)
        self.assertIn("Связь со Steam есть.", out)
        self.assertNotIn("[y/N]", out)
        self.assertFalse(os.path.exists(self.ours))

    def test_open_port_without_flag_asks(self):
        port = self.open_port()
        code, out = self.in_tty(f"bash {REPO}/install.sh", ["y"], NONSTEAM_CDP_PORT=port)
        self.assertEqual(code, 0, out)
        self.assertNotIn("Связь со Steam есть", out)
        self.assertIn("сейчас открыт, но не включён насовсем", out)
        self.assertIn("Включить порт сейчас? [y/N]", out)
        self.assertIn("Порт включён насовсем.", out)
        self.assertNotIn("Перезапусти Steam", out)
        self.assertTrue(os.path.exists(self.flag))
        self.assertTrue(os.path.exists(self.ours))
        code, out = self.install(NONSTEAM_CDP_PORT=port)
        self.assertEqual(code, 0, out)
        self.assertIn("Связь со Steam есть.", out)

    def test_open_port_without_flag_declined(self):
        code, out = self.install("--no-port", NONSTEAM_CDP_PORT=self.open_port())
        self.assertEqual(code, 0, out)
        self.assertIn("сейчас открыт, но не включён насовсем", out)
        self.assertIn("Порт не включён", out)
        self.assertFalse(os.path.exists(self.flag))
        self.assertFalse(os.path.exists(self.ours))

    def test_closed_port_without_flag_says_nothing_about_open(self):
        code, out = self.install("--no-port")
        self.assertEqual(code, 0, out)
        self.assertNotIn("сейчас открыт", out)
        self.assertNotIn("Связь со Steam есть", out)

    def test_existing_flag_is_not_ours(self):
        open(self.flag, "w").close()
        code, out = self.install()
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(self.ours))
        self.assertIn("откроется после перезапуска Steam", out)

    def test_reinstall_is_update(self):
        code, out = self.install("--no-port")
        self.assertEqual(code, 0, out)
        open(os.path.join(self.app, "stale.py"), "w").close()
        for name in ("state.json", "layouts-off.json", "layouts-fuse.json"):
            with open(os.path.join(self.data, name), "w") as f:
                f.write("{}")
        code, out = self.install("--no-port")
        self.assertEqual(code, 0, out)
        self.assertIn("обновлено до версии", out)
        self.assertFalse(os.path.exists(os.path.join(self.app, "stale.py")))
        self.assertFalse(os.path.exists(self.app + ".old"))
        self.assertFalse(os.path.exists(self.app + ".new"))
        self.assertTrue(os.path.exists(os.path.join(self.data, "state.json")))
        self.assertFalse(os.path.exists(os.path.join(self.data, "layouts-off.json")))
        self.assertFalse(os.path.exists(os.path.join(self.data, "layouts-fuse.json")))

    def test_no_accounts_drops_path_unit(self):
        code, out = self.install("--no-port")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.exists(os.path.join(self.units, "nonsteam-setup.path")))
        shutil.rmtree(os.path.join(self.steam, "userdata"))
        code, out = self.install("--no-port")
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(os.path.join(self.units, "nonsteam-setup.path")))
        self.assertIn("ни в один аккаунт", out)
        self.assertIn("Не нашёл профиль Steam", out)

    def test_english(self):
        code, out = self.install("--no-port", NONSTEAM_LANG="en", LANG="ru_RU.UTF-8")
        self.assertEqual(code, 0, out)
        self.assertIn("any program on this device", out)
        self.assertIn("“CEF Remote Debugging”", out)
        self.assertIn("Done: version", out)
        self.assertNotIn("Готово", out)

    def test_language_from_locale_and_steam(self):
        code, out = self.install("--no-port", NONSTEAM_LANG=None, LANG="ru_RU.UTF-8", LC_ALL=None)
        self.assertIn("Готово", out)
        code, out = self.install("--no-port", NONSTEAM_LANG=None, LANG="en_US.UTF-8", LC_ALL=None)
        self.assertIn("Done:", out)
        os.makedirs(os.path.join(self.home, ".steam"))
        with open(os.path.join(self.home, ".steam/registry.vdf"), "w") as f:
            f.write('"Registry"\n{\n\t"HKCU"\n\t{\n\t\t"Software"\n\t\t{\n\t\t\t"Valve"\n\t\t\t{\n\t\t\t\t"Steam"\n'
                    '\t\t\t\t{\n\t\t\t\t\t"language"\t\t"russian"\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n')
        code, out = self.install("--no-port", NONSTEAM_LANG=None, LANG="en_US.UTF-8", LC_ALL=None)
        self.assertIn("Готово", out)

    def test_refuses_without_steam(self):
        shutil.rmtree(self.steam)
        code, out = self.install("--no-port")
        self.assertEqual(code, 1)
        self.assertIn("не нашёл Steam", out)
        self.assertFalse(os.path.exists(self.app))

    def test_refuses_without_systemd(self):
        code, out = self.install("--no-port", FAKE_NO_SYSTEMD="1")
        self.assertEqual(code, 1)
        self.assertIn("systemctl --user", out)
        self.assertFalse(os.path.exists(self.app))

    def test_unknown_option(self):
        code, out = self.install("--yes")
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.app))


class Uninstall(Sandbox):
    def test_removes_everything_but_data(self):
        code, out = self.install("--enable-port")
        self.assertEqual(code, 0, out)
        with open(os.path.join(self.data, "state.json"), "w") as f:
            f.write("{}")
        code, out = self.uninstall()
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(self.app))
        for unit in ("nonsteam-setup.path", "nonsteam-setup.timer", "nonsteam-layouts.service",
                     "nonsteam-setup.service"):
            self.assertFalse(os.path.exists(os.path.join(self.units, unit)), unit)
            self.assertIn(f"--user disable --now {unit}", self.systemctl_log())
        self.assertFalse(os.path.exists(self.desktop))
        self.assertFalse(os.path.exists(os.path.join(self.home, "Desktop/nonsteam-setup.desktop")))
        self.assertFalse(os.path.exists(self.flag))
        self.assertFalse(os.path.exists(self.ours))
        self.assertTrue(os.path.exists(os.path.join(self.data, "state.json")))
        self.assertIn("Данные оставил", out)
        self.assertIn("Ярлыка «Оформить новые игры» в Steam нет.", out)
        self.assertIn("Готово: программа удалена", out)

    def test_purge(self):
        self.install("--no-port")
        code, out = self.uninstall("--purge")
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(self.data))

    def test_keeps_foreign_flag_and_desktop(self):
        open(self.flag, "w").close()
        self.install()
        foreign = os.path.join(self.home, "Desktop/nonsteam-setup.desktop")
        with open(foreign, "w") as f:
            f.write("[Desktop Entry]\nExec=/something/else\n")
        code, out = self.uninstall("--keep-data")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.exists(self.flag))
        self.assertTrue(os.path.exists(foreign))
        self.assertFalse(os.path.exists(self.desktop))

    def test_questions_in_terminal(self):
        self.install("--enable-port")
        code, out = self.in_tty(f"bash {self.app}/uninstall.sh", ["n", "y"])
        self.assertEqual(code, 0, out)
        self.assertIn("Выключить его? [Y/n]", out)
        self.assertTrue(os.path.exists(self.flag))
        self.assertFalse(os.path.exists(self.data))

    def test_install_again_after_uninstall(self):
        self.install("--no-port")
        self.uninstall("--purge")
        code, out = self.install("--no-port")
        self.assertEqual(code, 0, out)
        self.assertIn("установлена версия", out)
        self.assertTrue(os.path.exists(os.path.join(self.app, "main.py")))


class GetSh(Sandbox):
    def archive(self):
        path = os.path.join(self.tmp.name, "repo.tar.gz")
        with tarfile.open(path, "w:gz") as tar:
            for name in os.listdir(REPO):
                if name.endswith(".py") or name in SHIPPED:
                    tar.add(os.path.join(REPO, name), f"steamdeck-nonsteam-setup-main/{name}",
                            filter=lambda t: None if "__pycache__" in t.name else t)
        return "file://" + path

    def leftovers(self):
        return [n for n in os.listdir(self.tmp.name) if n not in ("home", "bin", "repo.tar.gz")]

    def test_pipe_to_bash_with_args(self):
        script = read_text(os.path.join(REPO, "get.sh"))
        code, out = self.run_sh(["-s", "--", "--enable-port"], cwd=self.tmp.name, stdin=script,
                                NONSTEAM_URL=self.archive())
        self.assertEqual(code, 0, out)
        self.assertIn("установлена версия", out)
        self.assertTrue(os.path.exists(self.flag))
        self.assertTrue(os.path.exists(os.path.join(self.app, "main.py")))
        self.assertEqual(self.leftovers(), [])

    def test_pipe_to_bash_asks_in_terminal(self):
        url = self.archive()
        code, out = self.in_tty(f"cat {REPO}/get.sh | bash", ["y"], NONSTEAM_URL=url)
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.exists(self.flag))

    def test_bad_url_fails_and_cleans(self):
        code, out = self.run_sh([os.path.join(REPO, "get.sh")], cwd=self.tmp.name,
                                NONSTEAM_URL="file://" + os.path.join(self.tmp.name, "missing.tar.gz"))
        self.assertNotEqual(code, 0)
        self.assertFalse(os.path.exists(self.app))
        self.assertEqual(self.leftovers(), [])


if __name__ == "__main__":
    unittest.main()

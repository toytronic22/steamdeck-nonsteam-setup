import json
import os
import re
import time
import urllib.request

REPO = "toytronic22/steamdeck-nonsteam-setup"
LATEST_URL = f"https://raw.githubusercontent.com/{REPO}/main/VERSION"
INSTALL_CMD = f"curl -fsSL https://raw.githubusercontent.com/{REPO}/main/get.sh | bash"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.expanduser("~"), ".local/share/nonsteam-setup")
CACHE = os.path.join(DATA, "update-check.json")
EVERY = 6 * 3600


def parse(text):
    found = re.fullmatch(r"\s*v?(\d+(?:\.\d+)*)\s*", text or "")
    return tuple(int(x) for x in found.group(1).split(".")) if found else None


def current():
    try:
        with open(os.path.join(HERE, "VERSION")) as f:
            return f.read().strip()
    except OSError:
        return None


def latest(now=None, fetch=None):
    now = time.time() if now is None else now
    try:
        with open(CACHE) as f:
            cached = json.load(f)
        if now - cached["at"] < EVERY and parse(cached["latest"]):
            return cached["latest"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        text = (fetch or _fetch)()
    except Exception:
        return None
    if not parse(text):
        return None
    os.makedirs(DATA, exist_ok=True)
    with open(CACHE, "w") as f:
        json.dump({"at": now, "latest": text.strip()}, f)
    return text.strip()


def _fetch():
    req = urllib.request.Request(LATEST_URL, headers={"User-Agent": "nonsteam-setup"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read(64).decode("ascii", "replace")


def report_line(mine=None, newest=None):
    mine = current() if mine is None else mine
    if not parse(mine):
        return "Версия неизвестна: файла VERSION нет — переустанови командой из README."
    newest = latest() if newest is None else newest
    if not parse(newest):
        return f"Версия {mine} · проверить обновление не удалось."
    if parse(newest) > parse(mine):
        return f"Версия {mine} · вышла {newest.strip()} — обнови командой:\n{INSTALL_CMD}"
    return f"Версия {mine} · новее нет."

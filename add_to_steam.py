import argparse
import base64
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main
from layouts import BUTTON_PENDING, DATA
from steamcdp import Cdp, SteamUnavailable

ART_FILES = {"poster": "poster.jpg", "hero": "hero.jpg", "logo": "logo.png", "wide": "wide.jpg"}
LOGO_POSITION = {"nVersion": 1, "logoPosition": {"pinnedPosition": "BottomLeft", "nWidthPct": 42, "nHeightPct": 65}}
APP_DIR = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.join(APP_DIR, "run.sh")


def find_shortcut(shortcuts_path, exe):
    return next((sc for sc in main.read_shortcuts(shortcuts_path) if sc["exe"] == exe), None)


def dress(cdp, grid, appid, assets, has_icon):
    have = main.existing_art(grid, appid)
    added = []
    for kind, name in ART_FILES.items():
        path = os.path.join(assets, name)
        if kind in have or not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        cdp.call("(a, b, e, t) => SteamClient.Apps.SetCustomArtworkForApp(a, b, e, t)",
                 appid, data, os.path.splitext(name)[1][1:], main.ART_TYPES[kind])
        added.append(kind)
    if "logo" in added and not os.path.exists(os.path.join(grid, f"{appid}.json")):
        cdp.call("(a, j) => SteamClient.Apps.SetCustomLogoPositionForApp(a, j)", appid, json.dumps(LOGO_POSITION))
    icon = os.path.join(assets, "icon.png")
    if not has_icon and os.path.exists(icon):
        cdp.call("(a, p) => SteamClient.Apps.SetShortcutIcon(a, p)", appid, icon)
    return added


def mark_pending(on):
    if on:
        os.makedirs(DATA, exist_ok=True)
        open(BUTTON_PENDING, "w").close()
    elif os.path.exists(BUTTON_PENDING):
        os.remove(BUTTON_PENDING)


def config_dir():
    user = main.find_user_dir()
    return os.path.join(main.STEAM, "userdata", user, "config") if user else None


def add():
    config = config_dir()
    if not config:
        print("Не нашёл профиль Steam: войди в Steam — кнопка появится сама.")
        mark_pending(True)
        return 1
    grid = os.path.join(config, "grid")
    sc = find_shortcut(os.path.join(config, "shortcuts.vdf"), RUN)
    try:
        with Cdp() as cdp:
            if sc:
                appid = sc["appid"]
                print(f"Ярлык «{main.TITLE}» в Steam уже есть.")
            else:
                appid = cdp.call("(n, e, d) => SteamClient.Apps.AddShortcut(n, e, d, '')", main.TITLE, RUN, APP_DIR)
                if not appid:
                    print("Steam не создал ярлык.")
                    return 1
                cdp.call("(a, n) => SteamClient.Apps.SetShortcutName(a, n)", appid, main.TITLE)
                cdp.call("(a) => SteamClient.Apps.SpecifyCompatTool(a, '')", appid)
                print(f"Добавил в Steam ярлык «{main.TITLE}».")
            added = dress(cdp, grid, appid, os.path.join(APP_DIR, "assets"), bool(sc and sc["icon"]))
    except SteamUnavailable:
        print(f"Нет связи со Steam: порт отладки закрыт. Кнопка «{main.TITLE}» появится сама, когда он откроется.")
        mark_pending(True)
        return 1
    mark_pending(False)
    time.sleep(1)
    lost = [main.ART_NAMES[k] for k in added if k not in main.existing_art(grid, appid)]
    if lost:
        print("Steam не записал картинки: " + ", ".join(lost))
    elif added:
        print("Картинки кнопки: " + ", ".join(main.ART_NAMES[k] for k in added))
    return 0


def remove():
    mark_pending(False)
    config = config_dir()
    sc = find_shortcut(os.path.join(config, "shortcuts.vdf"), RUN) if config else None
    if not sc:
        print(f"Ярлыка «{main.TITLE}» в Steam нет.")
        return 0
    try:
        with Cdp() as cdp:
            cdp.call("(a) => SteamClient.Apps.RemoveShortcut(a)", sc["appid"])
    except SteamUnavailable:
        print(f"Нет связи со Steam: удали ярлык «{main.TITLE}» из библиотеки сам.")
        return 1
    for _ in range(10):
        if not find_shortcut(os.path.join(config, "shortcuts.vdf"), RUN):
            break
        time.sleep(0.5)
    else:
        print(f"Steam пока не убрал ярлык «{main.TITLE}» — проверь библиотеку.")
        return 1
    for path in glob.glob(os.path.join(config, "grid", f"{sc['appid']}*")):
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem in (f"{sc['appid']}", f"{sc['appid']}p", f"{sc['appid']}_hero", f"{sc['appid']}_logo"):
            os.remove(path)
    print(f"Убрал из Steam ярлык «{main.TITLE}».")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--remove", action="store_true")
    sys.exit(remove() if parser.parse_args().remove else add())

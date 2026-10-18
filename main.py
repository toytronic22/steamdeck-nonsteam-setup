import argparse
import base64
import contextlib
import fcntl
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import launch
import layouts
import protondb
import redist
import steamweb
import update
import vdf
from layouts import DATA, STATE, STORE_JS, load_state
from steamcdp import Cdp, JsError, SteamUnavailable

TITLE = "Оформить новые игры"
HOME = os.path.expanduser("~")
STEAM = os.path.join(HOME, ".local/share/Steam")
REPORT = os.path.join(DATA, "last-report.txt")
MANUAL_REPORT = os.path.join(DATA, "manual-report.txt")
LOCK = os.path.join(DATA, "run.lock")
AUTO_TRIES = 3

DECK_CONTROLLER_TYPE = 4
TEMPLATE_GAMEPAD = ("template://controller_neptune_gamepad_joystick.vdf", "Геймпад")
TEMPLATE_GAMEPAD_MOUSE = ("template://controller_neptune_gamepad+mouse.vdf", "Геймпад с высокоточными осями")

ART_TYPES = {"poster": 0, "hero": 1, "logo": 2, "wide": 3}
ART_NAMES = {"poster": "постер", "hero": "фон", "logo": "логотип", "wide": "широкая"}

JUNK_WORDS = (r"repack|portable|gog|multi\d*|rus|eng|goty|deluxe edition|complete edition|"
              r"game of the year edition|definitive edition|early access|update \d+|hotfix")
TAILS = (r"^(.*\S)[\s_.\-]+by[\s_.\-]+\S.*$", r"^(.*\S)\s+[-–—]\s+\S.*$", r"^(.*[^\W_])[_\-]+[^\W\d_][^\W_]*$")
GENERIC_DIRS = {"bin", "bin64", "binaries", "win64", "win32", "x64", "x86", "game", "games", "data", "app",
                "release", "shipping", "retail", "engine", "common", "files", "pc"}
NOT_PROGRAM = {".dll", ".lnk", ".url", ".ini", ".cfg", ".txt", ".dat", ".pak", ".ico", ".png", ".jpg", ".log",
               ".xml", ".json", ".sys", ".ocx"}
NOT_GAME_EXE = r"unins|setup|redist|physx|directx|crash|shadercompile|prereq|dxsetup|dotnet|vcredist|launcherhelper|report"
ROOT_DIRS = {"downloads", "games", "deck", "home", "steamlibrary", "media", "run", "mnt", "drive_c",
             "program files", "program files (x86)", "desktop", "загрузки", "игры"}

DECK_CONTROLLER_JS = """
(type) => {
  const c = (window.__nonsteamStore.m_controllerList || []).find(c => c.eControllerType == type);
  return c ? {index: c.nControllerIndex, serial: c.strSerialNumber || ""} : null;
}
"""

CONSOLE_JS = "cmd => SteamClient.Console.ExecCommand(cmd)"
COMPAT_TOOLS_JS = r"""
async (appid) => {
  if (SteamClient.Apps.GetAvailableCompatTools) return await SteamClient.Apps.GetAvailableCompatTools(appid);
  if (!window.__nonsteamCompat) {
    let req;
    window.webpackChunksteamui.push([[Math.random()], {}, r => { req = r }]);
    const name = '"CompatManager.GetCompatTools#1"';
    const id = req && Object.keys(req.m).find(k => String(req.m[k]).includes(name));
    const src = id ? String(req.m[id]) : "";
    const head = src.match(/^\(?(\w+),(\w+),(\w+)\)?=>\{"use strict";\3\.d\(\2,\{/);
    const ns = src.slice(src.indexOf(name)).match(/\}\)\((\w+)\|\|\(\1=\{\}\)\)/);
    if (!head || !ns) throw new Error("в Steam не нашёлся список Proton (CompatManager.GetCompatTools)");
    const factory = new Function("return " + src.slice(0, head[0].length) + "__nonsteamCompat:()=>" + ns[1] + ","
                                 + src.slice(head[0].length))();
    const exports = {};
    factory({exports}, exports, req);
    window.__nonsteamCompat = exports.__nonsteamCompat;
  }
  const answer = await window.__nonsteamCompat.GetCompatTools({appid});
  if (!answer.BSuccess()) throw new Error("Steam не отдал список Proton, код " + answer.GetEResult());
  return (answer.Body().toObject().tools || []).map(t => ({strToolName: t.name, strDisplayName: t.display_name}));
}
"""
QUERY_LAYOUTS_JS = """
async (appid, index, type, game) => {
  const s = window.__nonsteamStore;
  const loc = t => {
    if (!t || t[0] !== "#") return t;
    try { return (LocalizationManager.LocalizeString(t) || t).replace("%1$s", game) } catch (e) { return t }
  };
  s.QueryConfigsForApp(appid, index);
  for (let i = 0; i < 80; i++) {
    await new Promise(r => setTimeout(r, 250));
    if (i > 4 && !s.BConfigurationQueryInFlight) break;
  }
  const pick = x => ({title: loc(x.Title), url: x.URL, playtime: Number(x.playtime || 0),
                      official: !!x.bOfficial, recommended: !!x.bRecommended});
  return {official: (s.GetOfficialConfigsForApp(appid, type) || []).map(pick),
          workshop: (s.GetWorkshopConfigsForApp(appid, type) || []).map(pick)};
}
"""


def log_step(progress, text):
    print(text, flush=True)
    progress.say(text)


class Progress:
    def __init__(self, enabled):
        self.proc = None
        if enabled and shutil.which("zenity") and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            try:
                self.proc = subprocess.Popen(
                    ["zenity", "--progress", "--pulsate", "--no-cancel", "--auto-close",
                     f"--title={TITLE}", "--width=520", "--text=Начинаю…"],
                    stdin=subprocess.PIPE, text=True, env=dict(os.environ, LC_ALL="C.UTF-8"))
            except OSError:
                self.proc = None

    def say(self, text):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write("# " + text.replace("\n", " ") + "\n")
                self.proc.stdin.flush()
            except OSError:
                pass

    def close(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write("100\n")
                self.proc.stdin.close()
            except OSError:
                pass
            self.proc.wait(timeout=5)


class Fetcher:
    def __init__(self, progress):
        self.progress = progress
        self.errors = {}

    def __call__(self, keys):
        got = []
        todo = [k for k in keys if k not in self.errors]
        if todo:
            say = lambda t: log_step(self.progress, "   " + t)
            try:
                with Cdp() as cdp:
                    got, errors = redist.fetch(todo, lambda c: cdp.call(CONSOLE_JS, c), say=say)
            except SteamUnavailable:
                got, errors = [], {k: "нет связи со Steam" for k in todo}
            except JsError as e:
                got, errors = [], {k: f"Steam вернул ошибку: {e}" for k in todo}
            self.errors.update(errors)
        return got, {k: self.errors[k] for k in keys if k in self.errors}


def show_report(text, gui, save=REPORT, extra=""):
    if save:
        os.makedirs(DATA, exist_ok=True)
        with open(save, "w") as f:
            f.write(text + "\n")
    shown = f"{text}\n\n{extra}" if extra else text
    print("\n" + shown)
    if gui and shutil.which("zenity") and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        subprocess.run(["zenity", "--text-info", f"--title={TITLE}", "--width=1000", "--height=700"],
                       input=shown, text=True, check=False, env=dict(os.environ, LC_ALL="C.UTF-8"))


def library_now():
    try:
        user = find_user_dir()
        if not user:
            return ""
        done = load_state().get("done") or {}
        lines = []
        for sc in read_shortcuts(os.path.join(STEAM, "userdata", user, "config", "shortcuts.vdf")):
            info = (done.get(str(sc["appid"])) or {}).get("redist") or {}
            if not info:
                continue
            if info.get("depots") is None:
                lines.append(f"? {sc['name']}: не узнал у Steam, что нужно оригиналу, — спрошу при следующем запуске")
                continue
            result = redist.plan(sc["appid"], info["depots"] + (info.get("local") or []), info.get("tries"), AUTO_TRIES)
            mark = "!" if result["todo"] or result["stuck"] or result["absent"] else "✓"
            lines.append(f"{mark} {sc['name']}: {redist.status(result)}")
    except Exception as e:
        return f"Библиотеки сейчас: не смог проверить ({type(e).__name__}: {e})."
    return "Библиотеки сейчас:\n\n" + "\n".join(lines) if lines else ""


def nothing_new():
    text = "Новых игр нет — всё уже оформлено."
    now = library_now()
    if now:
        text = f"{text}\n\n{now}"
    try:
        with open(REPORT) as f:
            last = f.read().strip()
        when = time.strftime("%d.%m %H:%M", time.localtime(os.path.getmtime(REPORT)))
    except OSError:
        return text
    return f"{text}\n\nПоследний отчёт, {when}:\n\n{last}"


@contextlib.contextmanager
def run_lock(progress):
    os.makedirs(DATA, exist_ok=True)
    with open(LOCK, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log_step(progress, "Жду, пока закончится автоматическое оформление…")
            fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def gave_up(entry, sc):
    return (bool(entry) and entry.get("name") == sc["name"] and entry.get("exe", sc["exe"]) == sc["exe"]
            and entry.get("tries", 0) >= AUTO_TRIES)


def steam_users():
    try:
        names = os.listdir(os.path.join(STEAM, "userdata"))
    except OSError:
        return []
    return sorted(u for u in names if u.isdigit() and u != "0" and os.path.isdir(os.path.join(STEAM, "userdata", u)))


def recent_login():
    try:
        with open(os.path.join(STEAM, "config", "loginusers.vdf"), encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    for steamid, body in re.findall(r'"(\d{17})"\s*\{([^{}]*)\}', text):
        if re.search(r'"mostrecent"\s*"1"', body, re.I):
            return str(int(steamid) & 0xFFFFFFFF)
    return None


def find_user_dir():
    users = steam_users()
    recent = recent_login()
    if recent in users:
        return recent

    def freshness(user):
        config = os.path.join(STEAM, "userdata", user, "config")
        for path in (os.path.join(config, "shortcuts.vdf"), config):
            if os.path.exists(path):
                return (path.endswith(".vdf"), os.path.getmtime(path))
        return (False, 0.0)
    return max(users, key=freshness) if users else None


def read_shortcuts(path):
    return vdf.read_shortcuts(path) if os.path.exists(path) else []


def save_state(state):
    os.makedirs(DATA, exist_ok=True)
    with open(STATE + ".tmp", "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(STATE + ".tmp", STATE)


def backup(paths):
    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    target = os.path.join(DATA, "backups", stamp)
    os.makedirs(target, exist_ok=True)
    for p in paths:
        if os.path.exists(p):
            shutil.copy2(p, target)
    backups = sorted(glob.glob(os.path.join(DATA, "backups", "*")))
    for old in backups[:-10]:
        shutil.rmtree(old, ignore_errors=True)
    return target


def is_exe_name(name, exe):
    stem = os.path.splitext(os.path.basename(exe))[0]
    low = name.strip().lower()
    return low.endswith(launch.RUNNABLE) or low == stem.lower() or os.path.splitext(low)[1] in NOT_PROGRAM


def clean_name(name):
    name = re.sub(r"\.(exe|bat|cmd)$", "", name, flags=re.I)
    name = re.sub(r"[\[(].*?[\])]", " ", name)
    name = re.sub(r"\bv?\d+(\.\d+){1,}[\w\-]*", " ", name, flags=re.I)
    name = re.sub(r"\b(v|ver|version|build)\s*\d[\w.\-]*", " ", name, flags=re.I)
    name = re.sub(r"[_.]+", " ", name)
    name = re.sub(rf"\b({JUNK_WORDS})\b", " ", name, flags=re.I)
    name = re.sub(r"[\s\-–—]+$", "", name)
    return " ".join(name.split()).strip(" -–—")


def split_camel(stem):
    stem = re.sub(r"[_\-.]+", " ", stem)
    stem = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", stem)
    stem = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", stem)
    return " ".join(stem.split())


def name_variants(text):
    out = [text]
    for tail in TAILS:
        cut = re.sub(tail, r"\1", text, flags=re.I)
        if cut != text:
            out.append(cut)
    return [clean_name(v) for v in out]


def name_candidates(shortcut):
    name, exe = shortcut["name"], shortcut["exe"]
    sources = [name] if name and not is_exe_name(name, exe) else []
    for part in reversed(os.path.dirname(exe).split(os.sep)):
        if not part or part.lower() in ROOT_DIRS:
            break
        if part.lower() not in GENERIC_DIRS:
            sources.append(part)
    out = [v for source in sources for v in name_variants(source)]
    stem = os.path.splitext(os.path.basename(exe))[0]
    out.append(clean_name(split_camel(stem)))
    seen, result = set(), []
    for c in out:
        key = steamweb.normalize(c)
        if len(key) >= 2 and key not in seen:
            seen.add(key)
            result.append(c)
    return result


def exes_near(path, limit=4):
    root = os.path.dirname(path)
    found = []
    for folder, dirs, files in os.walk(root):
        if folder[len(root):].count(os.sep) >= 3:
            dirs[:] = []
        for f in sorted(files):
            rel = os.path.relpath(os.path.join(folder, f), root)
            if f.lower().endswith(".exe") and not re.search(NOT_GAME_EXE, rel, re.I):
                found.append(rel)
    return sorted(found, key=lambda x: (x.count(os.sep), x.lower()))[:limit]


def wrong_target(sc):
    ext = os.path.splitext(sc["exe"])[1].lower()
    if ext not in NOT_PROGRAM:
        return None
    lines = [f"✗ {sc['name']}: ярлык ведёт на файл {ext}, а не на программу — Steam его не запустит."]
    near = exes_near(sc["exe"])
    if near:
        lines.append("   Программы в этой папке: " + ", ".join(near) + ".")
    lines.append("   Удали ярлык и добавь в Steam exe игры — после этого оформлю сам.")
    return lines


def squash(text):
    return re.sub(r"[^0-9a-zа-яё]+", "", text.lower())


def has_layout(config_files, name):
    want = squash(name)
    return any(squash(k) == want for path in config_files for k in vdf.text_vdf_top_keys(path))


def existing_art(grid_dir, appid):
    found = set()
    for path in glob.glob(os.path.join(grid_dir, f"{appid}*")):
        base = os.path.basename(path)
        stem, ext = os.path.splitext(base)
        if ext.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        if stem == f"{appid}p":
            found.add("poster")
        elif stem == f"{appid}_hero":
            found.add("hero")
        elif stem == f"{appid}_logo":
            found.add("logo")
        elif stem == str(appid):
            found.add("wide")
    return found


def compat_tool_in_config(appid):
    try:
        with open(os.path.join(STEAM, "config", "config.vdf"), encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        return None
    start = text.find('"CompatToolMapping"')
    if start < 0:
        return None
    m = re.search(rf'"{appid}"\s*\{{\s*"name"\s*"([^"]*)"', text[start:])
    return m.group(1) if m else None


def choose_layout(layouts, support):
    official = layouts.get("official") or []
    if official:
        best = next((c for c in official if c["recommended"]), official[0])
        return best["url"], best["title"], "официальная от разработчика"
    if support == "full":
        return TEMPLATE_GAMEPAD[0], TEMPLATE_GAMEPAD[1], "игра полностью поддерживает геймпад"
    workshop = sorted(layouts.get("workshop") or [], key=lambda c: -c["playtime"])
    if workshop:
        return workshop[0]["url"], workshop[0]["title"], "самая популярная у сообщества"
    if support == "partial":
        return TEMPLATE_GAMEPAD[0], TEMPLATE_GAMEPAD[1], "частичная поддержка геймпада, своих раскладок нет"
    return TEMPLATE_GAMEPAD_MOUSE[0], TEMPLATE_GAMEPAD_MOUSE[1], "геймпад не поддерживается, своих раскладок нет"


def clean_store_name(name):
    return " ".join(re.sub(r"[™®©]", "", name).split())


class Runner:
    def __init__(self, cdp, user, progress, dry_run, fetcher=None, auto=False):
        self.cdp = cdp
        self.console = lambda c: cdp.call(CONSOLE_JS, c)
        self.fetcher = fetcher
        self.auto = auto
        self.user = user
        self.progress = progress
        self.dry_run = dry_run
        self.grid = os.path.join(STEAM, "userdata", user, "config", "grid")
        self.pdb = None
        self.not_found = set()
        self.tool = None
        self.redist = {}
        controller = cdp.call(DECK_CONTROLLER_JS, DECK_CONTROLLER_TYPE)
        self.ctrl_index = controller["index"] if controller else 15
        cfg_dir = os.path.join(STEAM, "steamapps", "common", "Steam Controller Configs", user, "config")
        self.config_files = [os.path.join(cfg_dir, "configset_controller_neptune.vdf")]
        if controller and controller["serial"]:
            self.config_files.append(os.path.join(cfg_dir, f"configset_{controller['serial']}.vdf"))

    def protondb(self):
        if self.pdb is None:
            self.pdb = protondb.load_index(DATA, log=lambda t: log_step(self.progress, t))["apps"]
        return self.pdb

    def process(self, sc):
        lines = []
        appid = sc["appid"]
        tried = name_candidates(sc)
        match = None
        for cand in tried:
            try:
                match = steamweb.match_game(cand)
            except Exception as e:
                return None, [f"✗ {sc['name']}: магазин Steam не ответил ({e})"]
            if match:
                break
        if not match:
            self.not_found.add(appid)
            names = ", ".join(f"«{c}»" for c in tried) or "—"
            return None, [f"✗ {sc['name']}: не нашёл игру в магазине Steam. Пробовал: {names}.",
                          "   Переименуй ярлык в точное название игры — после этого оформлю сам."]
        orig = match["appid"]
        item = steamweb.store_item(orig)
        game_name = clean_store_name(item.get("name") or match["name"])
        support = steamweb.controller_support(item)

        new_name = sc["name"]
        if is_exe_name(sc["name"], sc["exe"]) or not sc["name"].strip():
            new_name = game_name
        head = f"✓ {new_name}" + (f"  (было «{sc['name']}»)" if new_name != sc["name"] else "")
        lines.append(head)
        lines.append(f"   оригинал: {game_name}, store.steampowered.com/app/{orig}")
        lines += self.apply_launch(sc, orig)
        if self.dry_run:
            lines.append("   (пробный прогон — ничего не менял)")
            return orig, lines

        if new_name != sc["name"]:
            self.cdp.call("(a, n) => SteamClient.Apps.SetShortcutName(a, n)", appid, new_name)

        lines.append("   картинки: " + self.apply_art(appid, orig, item))
        lines.append("   Proton: " + self.apply_proton(appid, orig))
        lines.append("   раскладка: " + self.apply_layout(appid, orig, new_name, support, game_name))
        lines.append("   библиотеки: " + self.apply_redist(appid, orig, sc["exe"]))
        return orig, lines

    def apply_launch(self, sc, orig):
        try:
            info = steamweb.app_info(orig, console=self.console)
        except Exception:
            info = None
        move = launch.retarget(sc["exe"], info) if info else None
        if not move:
            hint = launch.launcher_hint(sc["exe"], info, exes_near(sc["exe"], limit=8))
            return ["   запуск: " + hint] if hint else []
        head = f"   запуск: ярлык вёл на «{os.path.basename(sc['exe'])}» ({move['was']}) — "
        if self.dry_run:
            return [head + f"переведу на игру: {move['rel']}"]
        self.cdp.call("(a, e) => SteamClient.Apps.SetShortcutExe(a, e)", sc["appid"], f'"{move["exe"]}"')
        self.cdp.call("(a, d) => SteamClient.Apps.SetShortcutStartDir(a, d)", sc["appid"], f'"{move["start_dir"]}"')
        was = sc["exe"]
        sc["exe"], sc["start_dir"] = move["exe"], move["start_dir"]
        for _ in range(10):
            if self.shortcut_exe(sc["appid"]) == move["exe"]:
                return [head + f"перевёл на игру: {move['rel']}"]
            time.sleep(0.5)
        return [head + f"перевёл на игру: {move['rel']}; Steam пока не записал, проверь свойства ярлыка "
                f"(было {was})"]

    def shortcut_exe(self, appid):
        path = os.path.join(STEAM, "userdata", self.user, "config", "shortcuts.vdf")
        try:
            return next((s["exe"] for s in vdf.read_shortcuts(path) if s["appid"] == appid), None)
        except Exception:
            return None

    def apply_art(self, appid, orig, item):
        have = existing_art(self.grid, appid)
        urls = steamweb.artwork_urls(item)
        logo_url, logo_pos = (None, None)
        if "logo" not in have:
            logo_url, logo_pos = steamweb.logo_info(orig, console=self.console)
        urls["logo"] = logo_url
        done, missing = [], []
        for kind in ("poster", "hero", "logo", "wide"):
            if kind in have:
                continue
            url = urls.get(kind)
            if not url:
                missing.append(ART_NAMES[kind])
                continue
            try:
                data = steamweb.get_bytes(url)
            except Exception:
                missing.append(ART_NAMES[kind])
                continue
            ext = "png" if url.split("?")[0].lower().endswith(".png") else "jpg"
            self.cdp.call("(a, b, e, t) => SteamClient.Apps.SetCustomArtworkForApp(a, b, e, t)",
                          appid, base64.b64encode(data).decode(), ext, ART_TYPES[kind])
            done.append(ART_NAMES[kind])
        if logo_pos and "логотип" in done and not os.path.exists(os.path.join(self.grid, f"{appid}.json")):
            try:
                position = {"nVersion": 1, "logoPosition": {
                    "pinnedPosition": logo_pos.get("pinned_position", "BottomLeft"),
                    "nWidthPct": float(logo_pos.get("width_pct", 50)),
                    "nHeightPct": float(logo_pos.get("height_pct", 50))}}
                self.cdp.call("(a, j) => SteamClient.Apps.SetCustomLogoPositionForApp(a, j)",
                              appid, json.dumps(position))
            except (ValueError, TypeError, JsError):
                pass
        time.sleep(0.5)
        now = existing_art(self.grid, appid)
        parts = []
        if done:
            parts.append(", ".join(done))
        if have:
            parts.append("уже были: " + ", ".join(ART_NAMES[k] for k in ("poster", "hero", "logo", "wide") if k in have))
        if missing:
            parts.append("нет у оригинала: " + ", ".join(missing))
        lost = [ART_NAMES[k] for k in ("poster", "hero", "logo", "wide") if k not in now and ART_NAMES[k] in done]
        if lost:
            parts.append("НЕ ЗАПИСАЛИСЬ: " + ", ".join(lost))
        return "; ".join(parts) or "—"

    def apply_proton(self, appid, orig):
        tools = self.cdp.call(COMPAT_TOOLS_JS, appid) or []
        available = [t["strToolName"] for t in tools]
        try:
            counts = self.protondb().get(str(orig))
        except Exception as e:
            counts = None
            log_step(self.progress, f"ProtonDB недоступна: {e}")
        tool, why = protondb.choose_tool(counts, available)
        self.tool = tool
        if not tool:
            return "не выбрал — нет установленных Proton"
        before = compat_tool_in_config(appid)
        self.cdp.call("(a, t) => SteamClient.Apps.SpecifyCompatTool(a, t)", appid, tool)
        display = next((t["strDisplayName"] for t in tools if t["strToolName"] == tool), tool)
        after = None
        for _ in range(10):
            after = compat_tool_in_config(appid)
            if after == tool:
                break
            time.sleep(0.5)
        text = f"{display} ({why})"
        if before and before != tool:
            text += f", было {before}"
        if after != tool:
            text += " — Steam пока не записал, проверь в свойствах игры"
        return text

    def apply_layout(self, appid, orig, name, support, game_name):
        if has_layout(self.config_files, name):
            return "уже своя, не трогал"
        layouts = self.cdp.call(QUERY_LAYOUTS_JS, orig, self.ctrl_index, DECK_CONTROLLER_TYPE, game_name) or {}
        url, title, why = choose_layout(layouts, support)
        self.cdp.call("(a, i, u) => window.__nonsteamStore.SetActiveConfigForApp(a, i, u, false)",
                      appid, self.ctrl_index, url)
        for _ in range(10):
            if has_layout(self.config_files, name):
                return f"«{title}» — {why}"
            time.sleep(0.5)
        return f"«{title}» — {why}; Steam пока не записал, проверь в настройках контроллера"

    def apply_redist(self, appid, orig, exe):
        try:
            depots = steamweb.shared_depots(orig, console=self.console)
        except Exception:
            depots = None
        local = redist.game_needs(exe)
        tool = compat_tool_in_config(appid) or self.tool or compat_tool_in_config(0)
        result = redist.ensure(appid, tool, (depots or []) + local, say=lambda t: log_step(self.progress, "   " + t),
                               download=self.fetcher, retry_fetch=not self.auto)
        self.redist[appid] = {"depots": depots, "local": local, "checks": redist.LOCAL_CHECKS, "exe": exe,
                              "tries": result["tries"]}
        return redist.describe(result, depots is None)


def original_depots(orig):
    try:
        with Cdp() as cdp:
            return steamweb.shared_depots(orig, timeout=10, retries=0, console=lambda c: cdp.call(CONSOLE_JS, c))
    except SteamUnavailable:
        return steamweb.shared_depots(orig, timeout=10, retries=0)


def redist_pass(state, shortcuts, skip, args, progress, fetcher):
    blocks = []
    done = state.get("done") or {}
    for sc in shortcuts:
        key = str(sc["appid"])
        entry = done.get(key)
        if not entry or not entry.get("orig") or key in skip or (args.appid and sc["appid"] not in args.appid):
            continue
        info = entry.get("redist") or {}
        depots, tries = info.get("depots"), info.get("tries") or {}
        if depots is None:
            try:
                depots = original_depots(entry["orig"])
            except Exception:
                depots = None
        same = info.get("exe") == sc["exe"] and info.get("checks") == redist.LOCAL_CHECKS
        local = info.get("local") if same else None
        if local is None:
            local = redist.game_needs(sc["exe"])
        fresh = {"depots": depots, "local": local, "checks": redist.LOCAL_CHECKS, "exe": sc["exe"], "tries": tries}
        planned = redist.plan(sc["appid"], (depots or []) + local, tries, AUTO_TRIES)
        fetchable = [k for k in planned["absent"] if redist.PACKAGES[k].get("fetch") and (
            not args.auto or tries.get(redist.FETCH + k, 0) < AUTO_TRIES)]
        if not planned["todo"] and not fetchable:
            if fresh != info:
                entry["redist"] = fresh
                save_state(state)
            continue
        log_step(progress, f"Библиотеки: {sc['name']}")
        tool = compat_tool_in_config(sc["appid"]) or compat_tool_in_config(0)
        result = redist.ensure(sc["appid"], tool, (depots or []) + local, tries, AUTO_TRIES,
                               say=lambda t: log_step(progress, "   " + t), download=fetcher,
                               retry_fetch=not args.auto)
        entry["redist"] = dict(fresh, tries=result["tries"])
        save_state(state)
        if result["done"] or result["failed"] or result["fetched"] or result["fetch_errors"]:
            mark = "✗" if result["failed"] or result["fetch_errors"] else "✓"
            blocks.append(f"{mark} {sc['name']}\n   библиотеки: {redist.describe(result, depots is None)}")
    return blocks


def main():
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--appid", type=int, action="append")
    parser.add_argument("--no-gui", action="store_true")
    parser.add_argument("--auto", action="store_true")
    args = parser.parse_args()
    gui = not (args.no_gui or args.auto)
    progress = Progress(gui)
    steam_ok = True
    try:
        with run_lock(progress):
            report = run(args, progress)
    except SteamUnavailable:
        steam_ok = False
        report = ("Нет связи со Steam: его порт отладки закрыт.\n\n"
                  "Если только что ставили программу — перезапусти Steam. Иначе запусти установку ещё раз —\n"
                  "она проверит порт и подскажет, что делать:\n" + update.INSTALL_CMD)
        if args.auto:
            report = ("Есть новые игры, но нет связи со Steam (автоматический запуск): порт отладки закрыт.\n\n"
                      "Появится связь — оформлю сам.")
    except Exception as e:
        report = f"Что-то сломалось: {type(e).__name__}: {e}\n\n{traceback.format_exc()}"
    finally:
        progress.close()
    extra = ""
    if not args.auto:
        extra = "\n\n".join(x for x in (
            layouts.report_line(load_state()) if steam_ok and not args.dry_run else "", update.report_line()) if x)
    if report is None:
        if not args.auto:
            show_report(nothing_new(), gui, save=None, extra=extra)
        return
    show_report(report, gui, save=MANUAL_REPORT if args.dry_run or args.appid else REPORT, extra=extra)


def run(args, progress):
    user = find_user_dir()
    if not user:
        return "Не нашёл профиль Steam: войди в Steam хотя бы раз и нажми ещё раз."
    shortcuts_path = os.path.join(STEAM, "userdata", user, "config", "shortcuts.vdf")
    state = load_state()
    done = state.setdefault("done", {})
    failed = state.setdefault("failed", {})

    shortcuts = read_shortcuts(shortcuts_path)
    todo, blocks = [], []
    for sc in shortcuts:
        if args.appid and sc["appid"] not in args.appid:
            continue
        key = str(sc["appid"])
        wrong = wrong_target(sc)
        if wrong:
            if not (args.auto and gave_up(failed.get(key), sc)):
                blocks.append("\n".join(wrong))
                if not args.dry_run:
                    failed[key] = {"name": sc["name"], "exe": sc["exe"], "tries": AUTO_TRIES}
                    save_state(state)
            continue
        if not sc["exe"].lower().endswith(launch.RUNNABLE):
            continue
        if key in done and not (args.all or args.appid):
            continue
        if args.auto and gave_up(failed.get(key), sc):
            continue
        todo.append(sc)
    fetcher = Fetcher(progress)
    if todo:
        processed = process_all(args, progress, user, shortcuts_path, state, todo, fetcher)
        if isinstance(processed, str):
            return processed
        blocks += processed
    fixed = [] if args.dry_run else redist_pass(state, shortcuts, {str(sc["appid"]) for sc in todo}, args, progress,
                                                fetcher)
    if not blocks and not fixed:
        return None
    parts = []
    if blocks:
        ok = sum(1 for b in blocks if b.startswith("✓"))
        head = f"Оформлено игр: {ok} из {len(blocks)}."
        if args.auto:
            head += "  (автоматически)"
        if args.dry_run:
            head += "  (пробный прогон)"
        parts.append(head + "\n\n" + "\n\n".join(blocks))
    if fixed:
        head = "Библиотеки для уже оформленных игр:" + ("  (автоматически)" if args.auto else "")
        parts.append(head + "\n\n" + "\n\n".join(fixed))
    return "\n\n".join(parts)


def process_all(args, progress, user, shortcuts_path, state, todo, fetcher=None):
    done, failed = state["done"], state["failed"]
    log_step(progress, "Подключаюсь к Steam…")
    with Cdp() as cdp:
        if not cdp.eval(STORE_JS):
            return "Не нашёл в Steam модуль раскладок — видимо, Steam обновился. Нужна правка инструмента."
        runner = Runner(cdp, user, progress, args.dry_run, fetcher, args.auto)
        if not args.dry_run:
            backup([shortcuts_path, os.path.join(STEAM, "config", "config.vdf")] + runner.config_files)
        blocks = []
        for i, sc in enumerate(todo, 1):
            log_step(progress, f"[{i}/{len(todo)}] {sc['name']}")
            try:
                orig, lines = runner.process(sc)
            except JsError as e:
                orig, lines = None, [f"✗ {sc['name']}: Steam вернул ошибку: {e}"]
            except Exception as e:
                orig, lines = None, [f"✗ {sc['name']}: {type(e).__name__}: {e}"]
            blocks.append("\n".join(lines))
            if args.dry_run:
                continue
            key = str(sc["appid"])
            if orig:
                done[key] = {"orig": orig, "at": time.strftime("%Y-%m-%d %H:%M")}
                if sc["appid"] in runner.redist:
                    done[key]["redist"] = runner.redist[sc["appid"]]
                failed.pop(key, None)
            else:
                prev = failed.get(key) or {}
                same = prev.get("name") == sc["name"] and prev.get("exe", sc["exe"]) == sc["exe"]
                tries = prev.get("tries", 0) + 1 if same else 1
                if sc["appid"] in runner.not_found:
                    tries = AUTO_TRIES
                failed[key] = {"name": sc["name"], "exe": sc["exe"], "tries": tries}
            save_state(state)
    return blocks


if __name__ == "__main__":
    main()

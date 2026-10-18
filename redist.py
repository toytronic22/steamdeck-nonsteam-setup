import glob
import mmap
import os
import re
import shutil
import signal
import socket
import subprocess
import time

HOME = os.path.expanduser("~")
STEAM = os.path.join(HOME, ".local/share/Steam")
COMMON = os.path.join(STEAM, "steamapps", "common")
SHARED = os.path.join(COMMON, "Steamworks Shared", "_CommonRedist")
SHARED_APP = "228980"
DEPOT_DOWNLOADS = [os.path.join(STEAM, "ubuntu12_32", "steamapps", "content", f"app_{SHARED_APP}"),
                   os.path.join(STEAM, "steamapps", "content", f"app_{SHARED_APP}")]
COMPAT = os.path.join(STEAM, "steamapps", "compatdata")
TOOL_DIRS = [os.path.join(STEAM, "compatibilitytools.d"), "/usr/share/steam/compatibilitytools.d"]
DATA = os.path.join(HOME, ".local/share/nonsteam-setup")
LOGS = os.path.join(DATA, "logs")
PREFIX_BACKUPS = os.path.join(DATA, "prefix-backups")
OWN = os.path.join(DATA, "redist")
PHYSX_LOADER = "physx-loader"
NEEDS_RE = re.compile(rb"(physxloader)\.dll", re.I)
LOCAL = [(PHYSX_LOADER, b"physxloader", "physxcore.dll")]
LOCAL_CHECKS = [mark for mark, _, _ in LOCAL]
TIMEOUT = 180
SCREEN_WAIT = 60
SCREEN_SETTLE = 5
SCREEN_CHANGES = 3
SCREEN_LOST = "экран закрылся"
CONSOLE_LOG = os.path.join(STEAM, "logs", "console_log.txt")
FETCH_TIMEOUT = 300
FETCH_DONE = re.compile(r'Depot download complete : "[^"]*depot_(\d+)"')
FETCH_FAILED = re.compile(r"Depot download failed : ([^\r\n]*)")
FETCH = "fetch:"
BUILTIN_TAGS = (b"Wine placeholder DLL", b"Wine builtin DLL")


def vc_runtime(years):
    return [rf"Visual C\+\+ (?:{years}) {arch} Minimum Runtime" for arch in ("x64", "x86")]


VC_OLD = ["vcredist_x86.exe", "vcredist_x64.exe"]

PACKAGES = {
    "vc2022": {"title": "Visual C++ 2015–2022", "depots": {"228986", "228987", "228988", "228989"}, "fetch": "228989",
               "variants": [("vcredist/2022", vc_runtime("2022")),
                            ("vcredist/2019", vc_runtime("2019|2022")),
                            ("vcredist/2015", vc_runtime("2015|2017|2019|2022"))],
               "files": ["vc_redist.x86.exe", "vc_redist.x64.exe"], "args": ["/q", "/norestart"]},
    "vc2013": {"title": "Visual C++ 2013", "depots": {"228985"}, "fetch": "228985",
               "variants": [("vcredist/2013", vc_runtime("2013"))], "files": VC_OLD, "args": ["/quiet", "/norestart"]},
    "vc2012": {"title": "Visual C++ 2012", "depots": {"228984"}, "fetch": "228984",
               "variants": [("vcredist/2012", vc_runtime("2012"))], "files": VC_OLD, "args": ["/quiet", "/norestart"]},
    "vc2010": {"title": "Visual C++ 2010", "depots": {"228983"}, "fetch": "228983",
               "variants": [("vcredist/2010", [r"Visual C\+\+ 2010\s+x64 Redistributable",
                                               r"Visual C\+\+ 2010\s+x86 Redistributable"])],
               "files": VC_OLD, "args": ["/q", "/norestart"]},
    "vc2008": {"title": "Visual C++ 2008", "depots": {"228982"}, "fetch": "228982",
               "variants": [("vcredist/2008", [r"Visual C\+\+ 2008 Redistributable - x64",
                                               r"Visual C\+\+ 2008 Redistributable - x86"])],
               "files": VC_OLD, "args": ["/q", "/norestart"]},
    "vc2005": {"title": "Visual C++ 2005", "depots": {"228981"}, "fetch": "228981",
               "variants": [("vcredist/2005", [r"Visual C\+\+ 2005 Redistributable(?! \(x64\))",
                                               r"Visual C\+\+ 2005 Redistributable \(x64\)"])],
               "files": VC_OLD, "args": ["/q"]},
    "directx": {"title": "DirectX", "depots": {"228990"}, "fetch": "228990", "variants": [("DirectX/Jun2010", None)],
                "files": ["DXSETUP.exe"], "args": ["/silent"],
                "dlls": ["windows/system32/d3dx9_43.dll", "windows/syswow64/d3dx9_43.dll"]},
    "openal": {"title": "OpenAL", "depots": {"229020"}, "fetch": "229020",
               "variants": [("OpenAL/*", None), ("OpenAL", None)], "files": ["oalinst.exe"], "args": ["/s"],
               "dlls": ["windows/syswow64/OpenAL32.dll", "windows/system32/OpenAL32.dll"]},
    "physx": {"title": "PhysX", "depots": {"229030", "229031", "229032", "229033", PHYSX_LOADER},
              "variants": [(os.path.join(OWN, "PhysX"), None)], "files": ["PhysX_9.23.1019_SystemSoftware.exe"],
              "args": ["/s"], "dlls": ["Program Files (x86)/NVIDIA Corporation/PhysX/Common/PhysXLoader.dll"]},
}
ORDER = ["vc2022", "vc2013", "vc2012", "vc2010", "vc2008", "vc2005", "directx", "openal", "physx"]
ALWAYS = ["vc2022"]


def needed(depots):
    keys = set(ALWAYS)
    for depot in depots or []:
        keys.update(k for k, pkg in PACKAGES.items() if str(depot) in pkg["depots"])
    return [k for k in ORDER if k in keys]


def mentioned(path):
    try:
        with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
            return {m.group(1).lower() for m in NEEDS_RE.finditer(data)}
    except (OSError, ValueError):
        return set()


def game_needs(exe):
    folder = os.path.dirname(exe)
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    have = {n.lower() for n in names}
    found = set()
    for path in [exe] + [os.path.join(folder, n) for n in sorted(names) if n.lower().endswith(".dll")]:
        found |= mentioned(path)
    return [mark for mark, dll, own in LOCAL if dll in found and own not in have]


def shared_roots():
    return [SHARED] + [p for root in DEPOT_DOWNLOADS
                       for p in sorted(glob.glob(os.path.join(root, "depot_*", "_CommonRedist")))]


def installer(key):
    pkg = PACKAGES[key]
    for folder, patterns in pkg.get("variants", []):
        paths = [folder] if os.path.isabs(folder) else [
            p for root in shared_roots() for p in sorted(glob.glob(os.path.join(root, folder)), reverse=True)]
        for path in paths:
            try:
                names = {n.lower(): n for n in os.listdir(path)}
            except OSError:
                continue
            if all(f.lower() in names for f in pkg["files"]):
                return [os.path.join(path, names[f.lower()]) for f in pkg["files"]], patterns
    return None


def prefix(appid):
    return os.path.join(COMPAT, str(appid), "pfx")


def is_native(path):
    if os.path.islink(path) and "/wine" in os.readlink(path):
        return False
    try:
        with open(path, "rb") as f:
            f.seek(0x40)
            return not f.read(20).startswith(BUILTIN_TAGS)
    except OSError:
        return False


def read_registry(appid):
    try:
        with open(os.path.join(prefix(appid), "system.reg"), "rb") as f:
            return f.read().decode("latin-1")
    except OSError:
        return ""


def installed(appid, key, registry):
    pkg = PACKAGES[key]
    if "dlls" in pkg:
        drive = os.path.join(prefix(appid), "drive_c")
        return all(is_native(os.path.join(drive, d)) for d in pkg["dlls"])
    if not pkg.get("variants"):
        return False
    found = installer(key)
    patterns = found[1] if found else pkg["variants"][-1][1]
    return all(re.search(p, registry, re.I) for p in patterns)


def plan(appid, depots, tries=None, max_tries=None):
    registry = read_registry(appid)
    need = needed(depots)
    had = [k for k in need if installed(appid, k, registry)]
    absent = [k for k in need if k not in had and installer(k) is None]
    todo = [k for k in need if k not in had and k not in absent]
    stuck = [k for k in todo if max_tries is not None and (tries or {}).get(k, 0) >= max_tries]
    return {"had": had, "absent": absent, "todo": [k for k in todo if k not in stuck], "stuck": stuck}


def log_end():
    try:
        return os.path.getsize(CONSOLE_LOG)
    except OSError:
        return 0


def log_since(offset):
    try:
        with open(CONSOLE_LOG, "rb") as f:
            if f.seek(0, os.SEEK_END) < offset:
                offset = 0
            f.seek(offset)
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def wait_download(depot, start, timeout, poll=1):
    deadline = time.time() + timeout
    while True:
        text = log_since(start)
        if depot in FETCH_DONE.findall(text):
            return None
        failed = FETCH_FAILED.search(text)
        if failed:
            return failed.group(1).strip() or "Steam не сказал почему"
        if time.time() >= deadline:
            return f"Steam не скачал за {max(1, round(timeout / 60))} мин"
        time.sleep(poll)


def forget_download(depot):
    for root in DEPOT_DOWNLOADS:
        try:
            os.remove(os.path.join(root, f"state_{SHARED_APP}_{depot}.patch"))
        except OSError:
            pass


def fetch(keys, command, say=print, timeout=FETCH_TIMEOUT):
    got, errors = [], {}
    for key in keys:
        depot = PACKAGES[key].get("fetch")
        if not depot or installer(key):
            continue
        say(f"скачиваю {PACKAGES[key]['title']} через Steam…")
        forget_download(depot)
        start = log_end()
        command(f"download_depot {SHARED_APP} {depot}")
        error = wait_download(depot, start, timeout)
        if error is None and installer(key):
            got.append(key)
        else:
            errors[key] = error or "скачал, но установщика в пакете нет"
    return got, errors


def proton_dir(tool):
    if not tool:
        return None
    if tool.startswith("proton_"):
        want = "proton" + tool[len("proton_"):].lower()
        for name in sorted(os.listdir(COMMON)):
            key = re.sub(r"[^0-9a-z]+", "", re.sub(r"\(.*?\)", "", name.lower()))
            if key in (want, want + "0") and os.path.isfile(os.path.join(COMMON, name, "proton")):
                return os.path.join(COMMON, name)
        return None
    for base in TOOL_DIRS:
        for manifest in glob.glob(os.path.join(base, "*", "compatibilitytool.vdf")):
            try:
                with open(manifest, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            folder = os.path.dirname(manifest)
            if re.search(rf'"{re.escape(tool)}"\s*\{{', text) and os.path.isfile(os.path.join(folder, "proton")):
                return folder
    return None


def wine_bin(proton, name):
    for sub in ("files", "dist"):
        path = os.path.join(proton, sub, "bin", name)
        if os.path.isfile(path):
            return path
    return None


def proc_environ(pid):
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            return f.read().split(b"\0")
    except OSError:
        return []


def server_alive(pfx):
    try:
        st = os.stat(pfx)
    except OSError:
        return False
    path = f"/tmp/.wine-{os.getuid()}/server-{st.st_dev:x}-{st.st_ino:x}/socket"
    if not os.path.exists(path):
        return False
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(path)
        return True
    except OSError:
        return False
    finally:
        s.close()


def steam_launched(appid):
    want = f"AppId={appid}".encode()
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                args = f.read().split(b"\0")
        except OSError:
            continue
        if b"SteamLaunch" in args and want in args:
            return True
    return False


def busy(appid):
    if steam_launched(appid):
        return True
    compat = os.path.join(COMPAT, str(appid))
    pfx = prefix(appid)
    marks = {f"{k}={v}{tail}".encode() for k, v in (("STEAM_COMPAT_DATA_PATH", compat), ("WINEPREFIX", pfx))
             for tail in ("", "/")}
    me = os.getpid()
    for pid in os.listdir("/proc"):
        if pid.isdigit() and int(pid) != me and marks.intersection(proc_environ(pid)):
            return True
    return server_alive(pfx)


def is_steam(pid):
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip() == "steam"
    except OSError:
        return False


def steam_screen():
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or not is_steam(pid):
            continue
        env = {}
        for item in proc_environ(pid):
            k, _, v = item.partition(b"=")
            if k in (b"DISPLAY", b"XAUTHORITY") and v:
                env[k.decode()] = v.decode()
        if "DISPLAY" in env:
            return env, int(pid)
    return None, None


def screen_env():
    env, owner = steam_screen()
    if os.environ.get("DISPLAY"):
        return {}, owner if env and env["DISPLAY"] == os.environ["DISPLAY"] else None
    return env, owner


def steam_alive(owner):
    return owner is None or is_steam(owner)


def wait_screen():
    deadline = time.time() + SCREEN_WAIT
    while time.time() < deadline:
        env, owner = steam_screen()
        time.sleep(SCREEN_SETTLE if env else 1)
        if env and is_steam(owner):
            return env, owner
    return None, None


def backup_prefix(appid):
    pfx = prefix(appid)
    if not os.path.isdir(pfx):
        return
    base = os.path.join(PREFIX_BACKUPS, str(appid))
    target = os.path.join(base, time.strftime("%Y-%m-%d_%H%M%S"))
    os.makedirs(target, exist_ok=True)
    for name in ("system.reg", "user.reg", "userdef.reg"):
        if os.path.exists(os.path.join(pfx, name)):
            shutil.copy2(os.path.join(pfx, name), target)
    for old in sorted(glob.glob(os.path.join(base, "*")))[:-3]:
        shutil.rmtree(old, ignore_errors=True)


def run_installer(proton, exe, args, env, log, alive=lambda: True):
    log.write(f"\n=== {time.strftime('%H:%M:%S')} {exe} {' '.join(args)}\n")
    log.flush()
    p = subprocess.Popen([os.path.join(proton, "proton"), "run", exe, *args], env=env,
                         stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + TIMEOUT
    while True:
        try:
            code = p.wait(timeout=1)
            break
        except subprocess.TimeoutExpired:
            code = SCREEN_LOST if not alive() else "таймаут" if time.time() > deadline else None
            if code:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
                break
    log.write(f"=== {time.strftime('%H:%M:%S')} код {code}\n")
    log.flush()
    return code


def kill_wine(proton, appid, log):
    if steam_launched(appid):
        return False
    server = wine_bin(proton, "wineserver")
    if server:
        env = dict(os.environ, WINEPREFIX=prefix(appid))
        subprocess.run([server, "-k"], env=env, timeout=60, check=False, stdout=log, stderr=subprocess.STDOUT)
    return True


def stop_wine(proton, appid, log):
    server = wine_bin(proton, "wineserver")
    if not server:
        return True
    env = dict(os.environ, WINEPREFIX=prefix(appid))
    waiter = subprocess.Popen([server, "-w"], env=env, stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + 60
    while waiter.poll() is None:
        if steam_launched(appid):
            waiter.terminate()
            waiter.wait()
            log.write("=== игру запустили во время установки — Wine не трогаю\n")
            return False
        if time.time() > deadline:
            waiter.terminate()
            waiter.wait()
            subprocess.run([server, "-k"], env=env, timeout=60, check=False, stdout=log, stderr=subprocess.STDOUT)
            return True
        time.sleep(1)
    return True


def ensure(appid, tool, depots, tries=None, max_tries=None, say=print, download=None, retry_fetch=True):
    result = plan(appid, depots, tries, max_tries)
    result.update(done=[], failed=[], skipped=None, tries=dict(tries or {}), log=None, fetched=[], fetch_errors={})
    want = [k for k in result["absent"] if PACKAGES[k].get("fetch") and (
        retry_fetch or max_tries is None or result["tries"].get(FETCH + k, 0) < max_tries)]
    if download and want:
        got, errors = download(want)
        for key in got:
            result["tries"].pop(FETCH + key, None)
        for key in errors:
            result["tries"][FETCH + key] = result["tries"].get(FETCH + key, 0) + 1
        result.update(plan(appid, depots, result["tries"], max_tries), fetched=got, fetch_errors=errors)
    if not result["todo"]:
        return result
    if busy(appid):
        result["skipped"] = "игра запущена — поставлю, когда закроется"
        return result
    proton = proton_dir(tool)
    if not proton:
        result["skipped"] = f"не нашёл папку Proton «{tool}»" if tool else "у игры не выбран Proton"
        return result
    screen, owner = screen_env()
    if screen is None:
        result["skipped"] = "не нашёл экран Steam, без него установщики не запускаются"
        return result

    compat = os.path.join(COMPAT, str(appid))
    os.makedirs(compat, exist_ok=True)
    backup_prefix(appid)
    env = dict(os.environ, **screen, STEAM_COMPAT_CLIENT_INSTALL_PATH=STEAM, STEAM_COMPAT_DATA_PATH=compat,
               PROTON_USE_XALIA="0")
    env.pop("WINEPREFIX", None)
    os.makedirs(LOGS, exist_ok=True)
    result["log"] = os.path.join(LOGS, f"redist-{appid}.txt")
    with open(result["log"], "w") as log:
        log.write(f"Proton: {proton}\n")
        launched = lost = False
        queue, changes = list(result["todo"]), 0
        while queue:
            if steam_launched(appid):
                launched = True
                break
            key = queue[0]
            say(f"ставлю {PACKAGES[key]['title']}…")
            exes, _ = installer(key)
            codes = []
            for exe in exes:
                codes.append(run_installer(proton, exe, PACKAGES[key]["args"], env, log, lambda: steam_alive(owner)))
                if codes[-1] == SCREEN_LOST:
                    break
            if SCREEN_LOST not in codes:
                queue.pop(0)
                continue
            if not kill_wine(proton, appid, log):
                launched = True
                break
            changes += 1
            screen, owner = wait_screen() if changes <= SCREEN_CHANGES else (None, None)
            if screen is None:
                lost = True
                break
            env.pop("XAUTHORITY", None)
            env.update(screen)
            log.write(f"=== экран Steam сменился, ставлю заново на {screen['DISPLAY']}\n")
            say("экран Steam сменился — ставлю заново…")
        launched = not stop_wine(proton, appid, log) or launched
    registry = read_registry(appid)
    for key in result["todo"]:
        if installed(appid, key, registry):
            result["done"].append(key)
            result["tries"].pop(key, None)
        elif not (launched or lost):
            result["failed"].append(key)
            result["tries"][key] = result["tries"].get(key, 0) + 1
    if launched or lost:
        result["todo"] = [k for k in result["todo"] if k not in result["done"]]
        if result["todo"]:
            result["skipped"] = ("игру запустили во время установки — проверю, когда закроется" if launched
                                 else "экран Steam закрылся во время установки — поставлю при следующем запуске")
    return result


def titles(keys):
    return ", ".join(PACKAGES[k]["title"] for k in keys)


def fetch_hint(keys):
    hints = []
    if any(PACKAGES[k].get("fetch") for k in keys):
        hints.append("скачаю через Steam при следующем запуске")
    if "physx" in keys:
        folder = PACKAGES["physx"]["variants"][0][0].replace(HOME, "~", 1)
        hints.append(f"PhysX: скачай с сайта NVIDIA {PACKAGES['physx']['files'][0]} и положи в {folder}")
    return "; ".join(hints)


def fetch_problems(errors):
    return "; ".join(f"{PACKAGES[k]['title']} не скачал через Steam: {why}" for k, why in errors.items())


def status(result):
    parts = []
    if result["had"]:
        parts.append("есть " + titles(result["had"]))
    if result["todo"]:
        parts.append(f"нет {titles(result['todo'])} — поставлю при следующем запуске")
    if result["stuck"]:
        parts.append(f"нет {titles(result['stuck'])} — не встают с нескольких попыток")
    if result["absent"]:
        parts.append("нет на деке: " + titles(result["absent"]))
        if fetch_hint(result["absent"]):
            parts.append(fetch_hint(result["absent"]))
    return "; ".join(parts) or "не нужны"


def describe(result, unknown=False):
    parts = []
    if result.get("fetched"):
        parts.append("скачал через Steam " + titles(result["fetched"]))
    if result["done"]:
        parts.append("поставил " + titles(result["done"]))
    if result["failed"]:
        parts.append(f"НЕ ВСТАЛИ: {titles(result['failed'])} (журнал {result['log']})")
    if result["skipped"]:
        parts.append(f"{titles(result['todo'])} не ставил: {result['skipped']}")
    if result["stuck"]:
        parts.append(f"{titles(result['stuck'])} не встают с нескольких попыток, больше не пробую")
    if result["had"]:
        parts.append("уже были: " + titles(result["had"]))
    if result.get("fetch_errors"):
        parts.append(fetch_problems(result["fetch_errors"]))
        rest = [k for k in result["absent"] if k not in result["fetch_errors"]]
    else:
        rest = result["absent"]
    if rest:
        parts.append("нет на деке: " + titles(rest))
        if fetch_hint(rest):
            parts.append(fetch_hint(rest))
    if unknown:
        parts.append("не узнал у Steam, что ещё нужно оригиналу, — спрошу в следующий раз")
    return "; ".join(parts) or "—"

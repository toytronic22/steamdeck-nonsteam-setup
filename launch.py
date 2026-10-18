import os
import re

SETTINGS = re.compile(r"config|settings|options|setup|настро", re.I)
LAUNCHER = re.compile(r"launch", re.I)
OPTION = re.compile(r"^option\d+$")
RUNNABLE = (".exe", ".bat", ".cmd")


def _rel(path):
    return re.sub(r"^(\./|/)+", "", (path or "").replace("\\", "/"))


def entries(info):
    launch = ((info or {}).get("config") or {}).get("launch") or {}
    out = []
    for key in sorted(launch, key=lambda k: int(k) if str(k).isdigit() else 1 << 30):
        item = launch[key]
        if not isinstance(item, dict) or not item.get("executable"):
            continue
        cfg = item.get("config") or {}
        exe = _rel(item["executable"])
        oslist = cfg.get("oslist")
        if oslist and "windows" not in oslist:
            continue
        if not oslist and not exe.lower().endswith(RUNNABLE):
            continue
        out.append({"exe": exe, "type": str(item.get("type") or "").lower(), "desc": item.get("description") or "",
                    "beta": bool(cfg.get("betakey")), "workingdir": _rel(item.get("workingdir"))})
    return out


def main_entry(items):
    return next((e for e in items if not e["beta"] and not OPTION.match(e["type"])), None)


def current_entry(items, exe):
    path = exe.replace("\\", "/").lower()
    return next((e for e in items if path.endswith("/" + e["exe"].lower())), None)


def game_root(exe, entry):
    return exe[:len(exe) - len(entry["exe"]) - 1]


def find_ci(root, rel, want_dir=False):
    path = root
    for part in _rel(rel).split("/"):
        if not part:
            continue
        try:
            names = os.listdir(path)
        except OSError:
            return None
        hit = next((n for n in sorted(names) if n.lower() == part.lower()), None)
        if hit is None:
            return None
        path = os.path.join(path, hit)
    ok = os.path.isdir(path) if want_dir else os.path.isfile(path)
    return path if ok else None


def is_launcher(path):
    return bool(LAUNCHER.search(os.path.basename(path)))


def retarget(exe, info):
    items = entries(info)
    cur, main = current_entry(items, exe), main_entry(items)
    if not cur or not main or cur["exe"].lower() == main["exe"].lower():
        return None
    if not SETTINGS.search(cur["desc"]) or is_launcher(main["exe"]):
        return None
    root = game_root(exe, cur)
    target = find_ci(root, main["exe"])
    if not target:
        return None
    start = (find_ci(root, main["workingdir"], want_dir=True) if main["workingdir"] else None) or os.path.dirname(target)
    return {"exe": target, "start_dir": start, "was": cur["desc"], "rel": os.path.relpath(target, root)}


def main_exe_on_disk(exe, info):
    items = entries(info)
    main = main_entry(items)
    if not main or is_launcher(main["exe"]):
        return None
    cur = current_entry(items, exe)
    roots = [game_root(exe, cur)] if cur else []
    folder = os.path.dirname(exe)
    for _ in range(3):
        roots.append(folder)
        folder = os.path.dirname(folder)
    for root in roots:
        found = find_ci(root, main["exe"])
        if found:
            return found
    return None


def launcher_hint(exe, info, near):
    if not is_launcher(exe):
        return None
    folder = os.path.dirname(exe)
    found = [main_exe_on_disk(exe, info)] + [os.path.join(folder, rel) for rel in near]
    seen, shown = set(), []
    for path in found:
        if not path or is_launcher(path) or os.path.normcase(path) == os.path.normcase(exe):
            continue
        rel = os.path.relpath(path, folder)
        if rel.lower() not in seen:
            seen.add(rel.lower())
            shown.append(rel)
    text = f"ярлык ведёт на лаунчер «{os.path.basename(exe)}». Если кнопок не видно — направь ярлык на exe игры"
    return text + (": " + ", ".join(shown[:3]) + "." if shown else ".")

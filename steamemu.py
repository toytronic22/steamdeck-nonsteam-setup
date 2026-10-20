import os
import re
import shutil

import launch

LOADERS = {"steamclient64.ini": ("launcher", ("steamclientpath64", "steamclientpath")),
           "coldclientloader.ini": ("steamclient", ("steamclient64dll", "steamclientdll"))}
RENAME = {"steamclient64.dll": "gbe_client64.dll", "steamclient.dll": "gbe_client.dll"}
SECTION = re.compile(r"^(?:\xef\xbb\xbf)?\s*\[([^\]]*)\]")
KEY = re.compile(r'^(\s*([^=;#\s][^=]*?)\s*=\s*)("?)(.*?)("?)(\s*)$')
ABSOLUTE = re.compile(r"^([a-z]:|/)", re.I)


def _read(path):
    with open(path, "rb") as f:
        return f.read().decode("latin-1")


def inis(folder):
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    return [(os.path.join(folder, n), LOADERS[n.lower()]) for n in names
            if n.lower() in LOADERS and os.path.isfile(os.path.join(folder, n))]


def changes(folder, ini, section, keys):
    lines = _read(ini).splitlines(keepends=True)
    found, current = [], None
    for i, line in enumerate(lines):
        head = SECTION.match(line)
        if head:
            current = head.group(1).strip().lower()
            continue
        m = KEY.match(line)
        if current != section or not m or m.group(2).lower() not in keys:
            continue
        value = m.group(4)
        rel = value.replace("\\", "/")
        base = rel.rsplit("/", 1)[-1]
        new = RENAME.get(base.lower())
        dll = launch.find_ci(folder, rel) if new and not ABSOLUTE.match(rel) else None
        if not dll:
            continue
        now = value[:len(value) - len(base)] + new
        found.append({"ini": ini, "line": i, "dll": dll, "copy": os.path.join(os.path.dirname(dll), new),
                      "was": value, "now": now, "text": m.group(1) + m.group(3) + now + m.group(5) + m.group(6)})
    return lines, found


def plan(exe):
    folder = os.path.dirname(exe)
    return [c for ini, (section, keys) in inis(folder) for c in changes(folder, ini, section, keys)[1]]


def fix(exe):
    folder = os.path.dirname(exe)
    done = []
    for ini, (section, keys) in inis(folder):
        lines, found = changes(folder, ini, section, keys)
        if not found:
            continue
        for c in found:
            shutil.copy2(c["dll"], c["copy"])
            lines[c["line"]] = c["text"]
        if not os.path.exists(ini + ".orig"):
            shutil.copy2(ini, ini + ".orig")
        with open(ini + ".tmp", "wb") as f:
            f.write("".join(lines).encode("latin-1"))
        os.replace(ini + ".tmp", ini)
        done += found
    return done


def describe(items, dry_run=False):
    parts = []
    for ini in sorted({c["ini"] for c in items}):
        swaps = ", ".join(f"{os.path.basename(c['dll'])} → {os.path.basename(c['copy'])}"
                          for c in items if c["ini"] == ini)
        parts.append(f"{'заменю ' if dry_run else ''}в {os.path.basename(ini)} {swaps}")
    return ("эмулятор Steam: " + "; ".join(parts) + " (копия рядом, старый ini — .orig): под именем steamclient "
            "Proton подменяет эмулятор настоящим Steam, и игра сразу закрывается")

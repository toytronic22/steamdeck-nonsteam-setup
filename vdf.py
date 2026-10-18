import re
import struct


def _read_cstr(data, pos):
    end = data.index(b"\x00", pos)
    return data[pos:end].decode("utf-8", errors="replace"), end + 1


def _read_map(data, pos):
    result = {}
    while True:
        kind = data[pos]
        pos += 1
        if kind == 0x08:
            return result, pos
        key, pos = _read_cstr(data, pos)
        if kind == 0x00:
            result[key], pos = _read_map(data, pos)
        elif kind == 0x01:
            result[key], pos = _read_cstr(data, pos)
        elif kind == 0x02:
            result[key] = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        elif kind == 0x07:
            result[key] = struct.unpack_from("<Q", data, pos)[0]
            pos += 8
        else:
            raise ValueError(f"unknown binary VDF type {kind} at {pos}")


def read_shortcuts(path):
    with open(path, "rb") as f:
        data = f.read()
    root, _ = _read_map(data, 0)
    shortcuts = []
    for entry in (root.get("shortcuts") or {}).values():
        lowered = {k.lower(): v for k, v in entry.items()}
        appid = lowered.get("appid")
        if appid is None:
            continue
        shortcuts.append({
            "appid": appid & 0xFFFFFFFF,
            "name": lowered.get("appname", ""),
            "exe": lowered.get("exe", "").strip().strip('"'),
            "start_dir": lowered.get("startdir", "").strip().strip('"'),
            "icon": lowered.get("icon", "").strip().strip('"'),
        })
    return shortcuts


def text_vdf_top_keys(path, section="controller_config"):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        return set()
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    keys, depth, inside, last = set(), 0, False, None
    for quoted, brace in tokens:
        if brace == "{":
            depth += 1
            if depth == 1 and last == section:
                inside = True
            elif depth == 2 and inside and last is not None:
                keys.add(last)
            last = None
        elif brace == "}":
            depth -= 1
            if depth == 0:
                inside = False
            last = None
        else:
            last = quoted
    return keys


TEXT_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])', re.S)
TEXT_ESCAPE = re.compile(r"\\(.)", re.S)


def _unescape(text):
    return TEXT_ESCAPE.sub(lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), text)


def parse_text_block(text):
    stack, key = [], None
    for m in TEXT_TOKEN.finditer(text):
        quoted, brace = m.groups()
        if brace == "{":
            child = {}
            if stack and key is not None:
                stack[-1][key] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if not stack:
                return None
            block = stack.pop()
            key = None
            if not stack:
                return block
        elif key is None:
            key = _unescape(quoted)
        else:
            if stack:
                stack[-1][key] = _unescape(quoted)
            key = None
    return None

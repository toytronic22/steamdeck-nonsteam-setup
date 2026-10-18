import codecs
import collections
import json
import os
import re
import tarfile
import tempfile
import time
import urllib.request

LIST_URL = "https://api.github.com/repos/bdefore/protondb-data/contents/reports"
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
RECENT_DAYS = 730
MIN_REPORTS = 3


def latest_dump():
    with urllib.request.urlopen(LIST_URL, timeout=30) as r:
        files = json.load(r)
    best = None
    for f in files:
        m = re.fullmatch(r"reports_([a-z]{3})(\d+)_(\d{4})\.tar\.gz", f["name"])
        if not m or m.group(1) not in MONTHS:
            continue
        key = (int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
        if best is None or key > best[0]:
            best = (key, f["name"], f["download_url"])
    if not best:
        raise RuntimeError("no ProtonDB dump found")
    return best[1], best[2]


def iter_reports(path):
    decoder = json.JSONDecoder()
    utf8 = codecs.getincrementaldecoder("utf-8")()
    with tarfile.open(path, "r:gz") as tf:
        member = next(m for m in tf.getmembers() if m.isfile())
        f = tf.extractfile(member)
        buf = ""
        while True:
            chunk = f.read(1 << 20)
            buf += utf8.decode(chunk, final=not chunk)
            pos = 0
            while True:
                while pos < len(buf) and buf[pos] in " \n\r\t,[":
                    pos += 1
                if pos >= len(buf) or buf[pos] == "]":
                    break
                try:
                    obj, end = decoder.raw_decode(buf, pos)
                except json.JSONDecodeError:
                    break
                yield obj
                pos = end
            buf = buf[pos:]
            if not chunk:
                break


def variant_key(responses):
    variant = responses.get("variant")
    custom = (responses.get("customProtonVersion") or "").strip()
    version = (responses.get("protonVersion") or "").strip()
    if variant in ("native", "notListed"):
        return None
    if variant == "official":
        return "official"
    if variant == "experimental":
        return "experimental"
    if variant == "ge":
        return "ge:" + custom if custom else "ge"
    if variant == "older":
        return "older:" + (custom or version) if (custom or version) else None
    if version:
        low = version.lower()
        if "experimental" in low:
            return "experimental"
        if "ge" in low:
            return "ge:" + version
        return "older:" + version
    return None


def build_index(dump_path):
    cutoff = time.time() - RECENT_DAYS * 86400
    recent = collections.defaultdict(collections.Counter)
    alltime = collections.defaultdict(collections.Counter)
    for report in iter_reports(dump_path):
        responses = report.get("responses") or {}
        if responses.get("verdict") != "yes":
            continue
        appid = str((report.get("app") or {}).get("steam", {}).get("appId") or "")
        if not appid.isdigit():
            continue
        key = variant_key(responses)
        if not key:
            continue
        alltime[appid][key] += 1
        if report.get("timestamp", 0) >= cutoff:
            recent[appid][key] += 1
    index = {}
    for appid, counts in alltime.items():
        chosen = recent.get(appid)
        if not chosen or sum(chosen.values()) < MIN_REPORTS:
            chosen = counts
        index[appid] = dict(chosen.most_common(6))
    return index


def load_index(cache_dir, max_age_days=30, log=print):
    path = os.path.join(cache_dir, "protondb-index.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age_days * 86400:
        with open(path) as f:
            return json.load(f)
    try:
        name, url = latest_dump()
        log(f"Обновляю базу ProtonDB ({name}), это пара минут…")
        with tempfile.TemporaryDirectory() as tmp:
            dump = os.path.join(tmp, name)
            urllib.request.urlretrieve(url, dump)
            index = build_index(dump)
        os.makedirs(cache_dir, exist_ok=True)
        with open(path + ".tmp", "w") as f:
            json.dump({"source": name, "built": int(time.time()), "apps": index}, f)
        os.replace(path + ".tmp", path)
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        if os.path.exists(path):
            log(f"ProtonDB не обновилась ({e}), беру старую базу")
            with open(path) as f:
                return json.load(f)
        raise


def _proton_number(text):
    m = re.search(r"(\d+)(?:\.(\d+))?", text)
    if not m:
        return None
    major, minor = int(m.group(1)), m.group(2)
    if major >= 7:
        return f"proton_{major}"
    return f"proton_{major}{minor if minor and minor != '0' else ''}"


def _stable_valve(available):
    best = None
    for name in available:
        m = re.fullmatch(r"proton_(\d+)", name)
        if m and 7 <= int(m.group(1)) <= 30 and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), name)
    return best[1] if best else None


def _newest_ge(available):
    ge = [n for n in available if n.lower().startswith("ge-proton")]

    def key(n):
        return [int(x) for x in re.findall(r"\d+", n)]

    return max(ge, key=key) if ge else None


def choose_tool(counts, available):
    available = list(available)
    fallback = "proton_experimental" if "proton_experimental" in available else _stable_valve(available)
    if not counts:
        return fallback, "в ProtonDB нет отчётов"
    total = sum(counts.values())
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    if total < MIN_REPORTS:
        return fallback, f"в ProtonDB мало отчётов ({total})"
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return fallback, f"в ProtonDB ничья: {ranked[0][0]} и {ranked[1][0]}"
    for key, n in ranked:
        why = f"ProtonDB: {key} — {n} из {total} хороших отчётов"
        if key == "official":
            tool = _stable_valve(available)
        elif key == "experimental":
            tool = "proton_experimental" if "proton_experimental" in available else None
        elif key.startswith("ge"):
            want = key.split(":", 1)[1] if ":" in key else ""
            tool = want if want in available else _newest_ge(available)
        else:
            tool = _proton_number(key.split(":", 1)[1])
            tool = tool if tool in available else None
        if tool:
            return tool, why
    return fallback, "варианты из ProtonDB не установлены"

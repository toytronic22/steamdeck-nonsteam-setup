import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request

import redist
import vdf

CDN = "https://shared.cloudflare.steamstatic.com/store_item_assets/"
UA = {"User-Agent": "nonsteam-setup/1.0"}
FULL_CONTROLLER = 28
GAME_TYPE = 0
PARTIAL_CONTROLLER = 18
SHARED_APP = "228980"
STEAM_TIMEOUT = 15


def get_json(url, timeout=20, retries=2, data=None):
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as e:
            last = e
            time.sleep(1 + attempt * 2)
    raise last


def get_bytes(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def normalize(name):
    name = re.sub(r"[™®©]", "", name)
    name = unicodedata.normalize("NFKD", name)
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    name = name.lower().replace("&", " and ")
    name = re.sub(r"[^a-z0-9а-яё]+", " ", name)
    return " ".join(name.split())


EDITION = re.compile(r"\s+(?:(?:game of the year|goty|complete|definitive|deluxe|enhanced|ultimate|gold|premium"
                     r"|anniversary|standard|special)\s+edition|game of the year|goty|remastered)$")


def _main_title(name):
    return normalize(re.split(r"[:\-–—]", name, 1)[0])


def _base_title(name):
    return EDITION.sub("", normalize(name))


def _subtitle(name):
    parts = re.split(r"[:\-–—]", name, 1)
    return normalize(parts[1]) if len(parts) > 1 else ""


def search_store(term):
    url = "https://store.steampowered.com/api/storesearch/?" + urllib.parse.urlencode(
        {"term": term, "l": "english", "cc": "us"})
    return [{"appid": item["id"], "name": item["name"]} for item in get_json(url).get("items", [])]


def search_community(term):
    url = "https://steamcommunity.com/actions/SearchApps/" + urllib.parse.quote(term)
    return [{"appid": int(item["appid"]), "name": item["name"]} for item in get_json(url) or []]


def item_types(appids):
    if not appids:
        return {}
    query = {"ids": [{"appid": a} for a in appids], "context": {"language": "english", "country_code": "US"}}
    url = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json=" + urllib.parse.quote(
        json.dumps(query))
    items = get_json(url).get("response", {}).get("store_items", [])
    return {it["appid"]: it.get("type") for it in items if "appid" in it}


def match_game(candidate):
    want = normalize(candidate)
    if not want:
        return None
    items = search_store(candidate) or search_community(candidate)
    types = item_types([item["appid"] for item in items])
    items = [item for item in items if types.get(item["appid"], GAME_TYPE) == GAME_TYPE]
    base = EDITION.sub("", want)
    for title, wanted in ((normalize, want), (_base_title, want), (normalize, base), (_base_title, base)):
        for item in items:
            if title(item["name"]) == wanted:
                return item
    for title in (lambda n: {_subtitle(n), EDITION.sub("", _subtitle(n))},
                  lambda n: {_main_title(n), _main_title(n).removeprefix("the ")}):
        found = [item for item in items if title(item["name"]) & {want, base}]
        if found:
            return found[0] if len(found) == 1 else None
    return None


def store_item(appid):
    query = {
        "ids": [{"appid": appid}],
        "context": {"language": "english", "country_code": "US"},
        "data_request": {"include_assets": True, "include_basic_info": True},
    }
    url = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json=" + urllib.parse.quote(
        json.dumps(query))
    items = get_json(url).get("response", {}).get("store_items", [])
    return items[0] if items else {}


def controller_support(item):
    ids = set((item.get("categories") or {}).get("controller_categoryids") or [])
    if FULL_CONTROLLER in ids:
        return "full"
    if PARTIAL_CONTROLLER in ids:
        return "partial"
    return "none"


def _asset_url(item, *names):
    assets = item.get("assets") or {}
    fmt = assets.get("asset_url_format")
    if not fmt:
        return None
    for name in names:
        if assets.get(name):
            return CDN + fmt.replace("${FILENAME}", assets[name])
    return None


def artwork_urls(item):
    return {
        "poster": _asset_url(item, "library_capsule_2x", "library_capsule"),
        "hero": _asset_url(item, "library_hero", "library_hero_2x"),
        "wide": _asset_url(item, "header_2x", "header", "main_capsule"),
    }


_app_info = {}


def steam_app_info(appid, console, timeout=STEAM_TIMEOUT, poll=0.2):
    start = redist.log_end()
    console(f"app_info_print {appid}")
    head = re.compile(rf'\] "{appid}"\r?\n\{{')
    deadline = time.time() + timeout
    while True:
        text = redist.log_since(start)
        found = head.search(text)
        if found:
            info = vdf.parse_text_block(text[found.start() + 1:])
            if info is not None:
                return info
        if time.time() >= deadline:
            return None
        time.sleep(poll)


def app_info(appid, timeout=25, retries=2, console=None):
    if appid not in _app_info:
        info = None
        if console:
            try:
                info = steam_app_info(appid, console)
            except Exception:
                info = None
        if not info:
            data = get_json(f"https://api.steamcmd.net/v1/info/{appid}", timeout=timeout, retries=retries)
            info = data["data"][str(appid)]
        _app_info[appid] = _lower_keys(info)
    return _app_info[appid]


def _lower_keys(value):
    if isinstance(value, dict):
        return {str(k).lower(): _lower_keys(v) for k, v in value.items()}
    return value


def shared_depots(appid, timeout=25, retries=2, console=None):
    depots = app_info(appid, timeout, retries, console).get("depots") or {}
    return sorted(k for k, v in depots.items()
                  if isinstance(v, dict) and str(v.get("depotfromapp")) == SHARED_APP)


def logo_info(appid, console=None):
    try:
        assets = app_info(appid, console=console)["common"].get("library_assets_full") or {}
        logo = assets.get("library_logo") or {}
        images = logo.get("image2x") or logo.get("image") or {}
        path = images.get("english") or next(iter(images.values()), None)
        if path:
            return CDN + f"steam/apps/{appid}/{path}", logo.get("logo_position")
    except Exception:
        pass
    return CDN + f"steam/apps/{appid}/logo.png", None

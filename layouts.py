import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from steamcdp import Cdp, SteamUnavailable
from update import INSTALL_CMD

DATA = os.path.join(os.path.expanduser("~"), ".local/share/nonsteam-setup")
STATE = os.path.join(DATA, "state.json")
SERVICE = "nonsteam-layouts.service"
BUTTON_PENDING = os.path.join(DATA, "button-pending")
LAYOUTS_OFF = os.path.join(DATA, "layouts-off.json")
FUSE = os.path.join(DATA, "layouts-fuse.json")
ADD_BUTTON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "add_to_steam.py")
VERSION = 5
TICK = 5
QUICK = 60
FUSE_LIMIT = 3

STORE_JS = """
window.__nonsteamStore = (() => {
  const fits = v => v && typeof v === "object" && typeof v.QueryConfigsForApp === "function"
                     && typeof v.GetWorkshopConfigsForApp === "function";
  if (fits(window.controllerConfiguratorStore)) return window.controllerConfiguratorStore;
  if (fits(window.__nonsteamStore)) return window.__nonsteamStore;
  let req;
  try { window.webpackChunksteamui.push([[Math.random()], {}, r => { req = r }]) } catch (e) { return null }
  const cache = req && req.c;
  if (!cache || typeof cache !== "object") return null;
  for (const id of Object.keys(cache)) {
    const m = cache[id] && cache[id].exports;
    if (!m || typeof m !== "object") continue;
    for (const k of Object.keys(m)) {
      let v; try { v = m[k] } catch (e) { continue }
      if (fits(v)) return v;
    }
  }
  return null;
})();
!!window.__nonsteamStore
"""

PATCH_JS = """
(version, map) => {
  const s = window.__nonsteamStore;
  if (!s) return "не нашёл в Steam модуль раскладок";
  const proto = Object.getPrototypeOf(s);
  if (typeof proto.GetConfigsForApp !== "function" || typeof proto.QueryConfigsForApp !== "function")
    return "в модуле раскладок Steam нет нужных методов";
  window.__nonsteamOrig = map;
  if (s.__nonsteamLayouts !== version) {
    const DECK = 4;
    const ASK_AGAIN = 300000;
    const asked = new Map();
    const marked = new WeakMap();
    const mark = (x, official) => {
      let copy = marked.get(x);
      if (!copy || copy.__from !== official) {
        copy = Object.assign({}, x, {
          bOfficial: true, bProgenitorOfficial: official.bProgenitorOfficial,
          bRecommended: official.bRecommended, bProgenitorRecommended: official.bProgenitorRecommended,
        });
        Object.defineProperty(copy, "__from", {value: official});
        marked.set(x, copy);
      }
      return copy;
    };
    const isDeck = x => x.nControllerType === DECK && !x.bOfficial && !!x.URL && x.URL.startsWith("workshop");
    const installs = items => {
      const out = new Map();
      try {
        const ws = window.workshopStore;
        const files = ws && ws.m_mapPublishedFiles;
        if (!files || typeof files.get !== "function" || typeof ws.GetPublishedFiles !== "function") return out;
        const queue = Array.isArray(ws.m_LoadQueue) ? ws.m_LoadQueue : [];
        const missing = [];
        for (const x of items) {
          const id = String(x.publishedFileID || "");
          if (!id || id === "0") continue;
          const file = files.get(id) && files.get(id).file;
          const n = file ? Number(file.lifetime_subscriptions || file.subscriptions) : NaN;
          if (Number.isFinite(n)) out.set(id, n);
          else if (!queue.includes(id) && !(Date.now() - (asked.get(id) || 0) < ASK_AGAIN)) missing.push(id);
        }
        if (missing.length) {
          for (const id of missing) asked.set(id, Date.now());
          ws.GetPublishedFiles(missing);
        }
      } catch (e) {}
      return out;
    };
    const ru = /^ru/i.test(document.documentElement.lang || navigator.language || "");
    const label = n => {
      const num = n.toLocaleString(ru ? "ru-RU" : "en-US");
      if (!ru) return num + (n === 1 ? " install" : " installs") + " on Steam Deck";
      const form = new Intl.PluralRules("ru-RU").select(n);
      return num + " " + (form === "one" ? "установка" : form === "many" ? "установок" : "установки") + " на Steam Deck";
    };
    const counted = new WeakMap();
    const count = (x, n) => {
      let copy = counted.get(x);
      if (!copy || copy.__installs !== n) {
        copy = Object.assign({}, x, {Title: label(n) + " · " + (x.Title || "")});
        Object.defineProperty(copy, "__installs", {value: n});
        counted.set(x, copy);
      }
      return copy;
    };
    class Ranked extends Array {
      sort(cmp) {
        const order = (a, b) => {
          if (!cmp) return String(a) < String(b) ? -1 : String(a) > String(b) ? 1 : 0;
          try { return cmp(a, b) } catch (e) { return 0 }
        };
        const items = Array.from(this);
        const rank = x => isDeck(x) ? (x.__installs === undefined ? -1 : x.__installs) : -2;
        items.sort((a, b) => rank(b) - rank(a) || order(a, b));
        items.forEach((x, i) => { this[i] = x });
        return this;
      }
    }
    s.GetConfigsForApp = function (appid) {
      const own = proto.GetConfigsForApp.call(this, appid);
      try {
        const orig = window.__nonsteamOrig[appid];
        if (!orig) return own;
        const theirs = proto.GetConfigsForApp.call(this, orig)
          .filter(x => x.URL && (x.URL.startsWith("workshop") || x.bOfficial));
        if (!theirs.length) return own;
        const official = new Map(theirs.filter(x => x.bOfficial).map(x => [x.URL, x]));
        const seen = new Set(own.map(x => x.URL));
        const all = own.map(x => !x.bOfficial && official.has(x.URL) ? mark(x, official.get(x.URL)) : x)
          .concat(theirs.filter(x => !seen.has(x.URL)));
        const known = installs(all.filter(isDeck));
        const id = x => String(x.publishedFileID || "");
        return Ranked.from(all.map(x => isDeck(x) && known.has(id(x)) ? count(x, known.get(id(x))) : x));
      } catch (e) {
        return own;
      }
    };
    s.QueryConfigsForApp = function (appid, index) {
      try {
        const orig = window.__nonsteamOrig[appid];
        if (orig) {
          proto.QueryConfigsForApp.call(this, orig, index);
          const deck = Array.from(this.m_controllerList || [])
            .some(c => c && c.nControllerIndex === index && c.eControllerType === DECK);
          if (this.m_bFilterOtherControllerTypes && deck) SteamClient.Input.QueryControllerConfigsForApp(orig, index, false);
        }
      } catch (e) {}
      return proto.QueryConfigsForApp.call(this, appid, index);
    };
    s.__nonsteamLayouts = version;
  }
  return "";
}
"""

CHECK_JS = f"""
!!window.__nonsteamStore && window.__nonsteamStore.__nonsteamLayouts === {VERSION}
  && (!window.controllerConfiguratorStore || window.controllerConfiguratorStore === window.__nonsteamStore)
"""


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_json(path, data):
    os.makedirs(DATA, exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(path + ".tmp", path)


def fuse_step(count, lived):
    if lived is None:
        return count, False
    count = count + 1 if lived < QUICK else 0
    return count, count >= FUSE_LIMIT


class Fuse:
    def __init__(self):
        self.count = (read_json(FUSE) or {}).get("quick", 0)
        self.since = None

    def save(self, count):
        if count != self.count:
            self.count = count
            write_json(FUSE, {"quick": count})

    def patched(self):
        if self.since is None:
            self.since = time.monotonic()

    def alive(self):
        if self.since is not None and self.count and time.monotonic() - self.since >= QUICK:
            self.save(0)

    def lost(self):
        lived = None if self.since is None else time.monotonic() - self.since
        self.since = None
        count, blown = fuse_step(self.count, lived)
        self.save(count)
        if blown:
            write_json(LAYOUTS_OFF, {"at": time.strftime("%Y-%m-%d %H:%M"), "quick": count})
        return blown


def state_mtime():
    try:
        return os.path.getmtime(STATE)
    except OSError:
        return None


def mapping(state):
    return {k: v["orig"] for k, v in (state.get("done") or {}).items() if v.get("orig")}


def ensure(cdp, state):
    games = mapping(state)
    if not cdp.eval(STORE_JS):
        return "не нашёл в Steam модуль раскладок", games
    return cdp.call(PATCH_JS, VERSION, games), games


def service_active():
    try:
        return subprocess.run(["systemctl", "--user", "is-active", "--quiet", SERVICE], check=False).returncode == 0
    except OSError:
        return False


def report_line(state):
    head = "Раскладки оригинала в меню контроллера"
    off = read_json(LAYOUTS_OFF)
    if off is not None:
        return (f"⚠ {head} выключены предохранителем ({off.get('at', '?')}): Steam {FUSE_LIMIT} раза подряд терял связь"
                " меньше чем через минуту после их подключения. Включить снова — запусти установку ещё раз:\n"
                + INSTALL_CMD)
    try:
        with Cdp() as cdp:
            error, games = ensure(cdp, state)
    except SteamUnavailable:
        return f"⚠ {head}: нет связи со Steam, проверить не смог."
    if error:
        return f"⚠ {head} не подключились: {error}. Видимо, Steam обновился — нужна правка инструмента."
    line = f"{head}: подключены, игр — {len(games)}."
    if not service_active():
        line += (f"\n⚠ Не работает служба {SERVICE}: после перезапуска Steam раскладки оригинала из меню пропадут."
                 " Запусти установку ещё раз:\n" + INSTALL_CMD)
    return line


def log(text):
    print(time.strftime("%H:%M:%S ") + text, flush=True)


def add_button():
    try:
        done = subprocess.run([sys.executable, ADD_BUTTON], capture_output=True, text=True, timeout=180, check=False)
        log("кнопка: " + " ".join((done.stdout + done.stderr).split()))
    except (OSError, subprocess.SubprocessError) as e:
        log(f"кнопка: {type(e).__name__}: {e}")


def watch():
    said = None
    fuse = Fuse()
    while True:
        try:
            with Cdp(timeout=30) as cdp:
                if os.path.exists(BUTTON_PENDING):
                    add_button()
                applied = None
                while True:
                    if os.path.exists(LAYOUTS_OFF):
                        text = "выключено предохранителем, жду повторной установки"
                    elif state_mtime() != applied or not cdp.eval(CHECK_JS):
                        mtime = state_mtime()
                        error, games = ensure(cdp, load_state())
                        text = f"не подключил: {error}" if error else f"подключил раскладки оригинала, игр — {len(games)}"
                        applied = None if error else mtime
                        if not error:
                            fuse.patched()
                    else:
                        text = said
                    if text != said:
                        log(text)
                        said = text
                    fuse.alive()
                    time.sleep(TICK)
        except Exception as e:
            if fuse.lost():
                log(f"предохранитель: Steam {FUSE_LIMIT} раза подряд терял связь сразу после подключения — выключаю")
            text = f"нет связи со Steam: {type(e).__name__}: {e}"
            if text != said:
                log(text)
                said = text
        time.sleep(TICK)


if __name__ == "__main__":
    watch()

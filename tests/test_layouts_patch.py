import json
import shutil
import subprocess
import unittest

import layouts

FAKE_STEAM = r"""
const calls = [];
globalThis.window = globalThis;
globalThis.document = {documentElement: {lang: LANG}};
globalThis.SteamClient = {Input: {QueryControllerConfigsForApp: (...a) => calls.push(a)}};
class Store {
  constructor() {
    this.m_mapAppConfigs = new Map();
    this.m_bFilterOtherControllerTypes = true;
    this.m_controllerList = [{eControllerType: 4, nControllerIndex: 15}, {eControllerType: 32, nControllerIndex: 0}];
  }
  QueryConfigsForApp(e, t) {
    this.m_mapAppConfigs.set(e, []);
    SteamClient.Input.QueryControllerConfigsForApp(e, t, this.m_bFilterOtherControllerTypes);
  }
  GetConfigsForApp(e) { return this.m_mapAppConfigs.has(e) ? this.m_mapAppConfigs.get(e) : [] }
  BControllerTypesEquivalent(a, b) { return [2, 3, 4, 34, 45, 48].includes(b) }
  GetWorkshopConfigsForApp(e, t) {
    return this.GetConfigsForApp(e).filter(x => x.URL.startsWith("workshop") && this.BControllerTypesEquivalent(t, x.nControllerType));
  }
}
const loads = [];
globalThis.workshopStore = {
  m_mapPublishedFiles: new Map(), m_LoadQueue: [],
  GetPublishedFiles(ids) { loads.push(ids.slice()); return [] },
};
const installed = (id, n) => workshopStore.m_mapPublishedFiles.set(id, {file: {lifetime_subscriptions: n}});
const rec = (id, type, playtime, extra) => Object.assign(
  {URL: "workshop://" + id, publishedFileID: id, nControllerType: type, Title: "t" + id, playtime: String(playtime), bOfficial: false},
  extra || {});
const byPlaytime = (a, b) => Number(b.playtime) - Number(a.playtime);
const shown = (s, app) => s.GetWorkshopConfigsForApp(app, 4).filter(x => !x.bOfficial).sort(byPlaytime)
  .map(x => [x.publishedFileID, x.Title]);
window.__nonsteamStore = new Store();
const result = (PATCH)(5, {"100": 200});
const s = window.__nonsteamStore;
"""


@unittest.skipUnless(shutil.which("node"), "нужен node")
class PatchInSteam(unittest.TestCase):
    def run_js(self, scenario, lang="ru"):
        script = (FAKE_STEAM.replace("PATCH", layouts.PATCH_JS).replace("LANG", json.dumps(lang))
                  + "console.log(JSON.stringify((() => {" + scenario + "})()));")
        done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30, check=True)
        return json.loads(done.stdout)

    def test_deck_layouts_go_first_by_installs_with_count_in_title(self):
        got = self.run_js("""
          s.m_mapAppConfigs.set(200, [rec("1", 2, 900), rec("2", 4, 5), rec("3", 4, 50), rec("4", 4, 70), rec("5", 2, 10)]);
          installed("2", 6332); installed("3", 12);
          return shown(s, 100);
        """)
        self.assertEqual(got, [["2", "6\u00a0332 установки на Steam Deck · t2"], ["3", "12 установок на Steam Deck · t3"],
                               ["4", "t4"], ["1", "t1"], ["5", "t5"]])

    def test_missing_installs_are_asked_once(self):
        got = self.run_js("""
          s.m_mapAppConfigs.set(200, [rec("2", 4, 5), rec("3", 4, 50), rec("1", 2, 9)]);
          installed("3", 7);
          shown(s, 100); shown(s, 100);
          return loads;
        """)
        self.assertEqual(got, [["2"]])

    def test_queued_installs_are_not_asked_again(self):
        got = self.run_js("""
          s.m_mapAppConfigs.set(200, [rec("2", 4, 5)]);
          workshopStore.m_LoadQueue.push("2");
          shown(s, 100);
          return loads;
        """)
        self.assertEqual(got, [])

    def test_deck_asks_original_for_all_controller_types(self):
        got = self.run_js("s.QueryConfigsForApp(100, 15); return calls;")
        self.assertEqual(got, [[200, 15, True], [200, 15, False], [100, 15, True]])

    def test_other_controller_asks_as_before(self):
        got = self.run_js("s.QueryConfigsForApp(100, 0); return calls;")
        self.assertEqual(got, [[200, 0, True], [100, 0, True]])

    def test_unfiltered_steam_asks_once(self):
        got = self.run_js("s.m_bFilterOtherControllerTypes = false; s.QueryConfigsForApp(100, 15); return calls;")
        self.assertEqual(got, [[200, 15, False], [100, 15, False]])

    def test_steam_game_is_untouched(self):
        got = self.run_js("""
          s.m_mapAppConfigs.set(300, [rec("1", 4, 1), rec("2", 2, 5)]);
          installed("1", 99);
          s.QueryConfigsForApp(300, 15);
          s.m_mapAppConfigs.set(300, [rec("1", 4, 1), rec("2", 2, 5)]);
          return [calls, shown(s, 300), loads];
        """)
        self.assertEqual(got, [[[300, 15, True]], [["2", "t2"], ["1", "t1"]], []])

    def test_official_layouts_keep_steam_order_and_title(self):
        got = self.run_js("""
          s.m_mapAppConfigs.set(200, [rec("1", 4, 0, {bOfficial: true, nSortIdx: 2}), rec("2", 4, 0, {bOfficial: true, nSortIdx: 1})]);
          installed("1", 500);
          return s.GetConfigsForApp(100).filter(x => x.bOfficial).sort((a, b) => a.nSortIdx - b.nSortIdx).map(x => x.Title);
        """)
        self.assertEqual(got, ["t2", "t1"])

    def test_broken_steam_order_still_lists_everything(self):
        got = self.run_js("""
          s.m_mapAppConfigs.set(200, [rec("1", 2, 1), rec("2", 4, 1), rec("3", 2, 1)]);
          installed("2", 3);
          return s.GetWorkshopConfigsForApp(100, 4).sort(() => { throw new Error("x") }).map(x => x.publishedFileID);
        """)
        self.assertEqual(got[0], "2")
        self.assertEqual(sorted(got), ["1", "2", "3"])

    def test_russian_plural_forms(self):
        got = self.run_js("""
          s.m_mapAppConfigs.set(200, [1, 3, 5, 21, 11].map((n, i) => rec(String(i + 1), 4, 0)));
          [1, 3, 5, 21, 11].forEach((n, i) => installed(String(i + 1), n));
          return shown(s, 100).map(x => x[1].split(" на ")[0]);
        """)
        self.assertEqual(got, ["21 установка", "11 установок", "5 установок", "3 установки", "1 установка"])

    def test_english_label(self):
        got = self.run_js("""
          s.m_mapAppConfigs.set(200, [rec("1", 4, 0), rec("2", 4, 0)]);
          installed("1", 6332); installed("2", 1);
          return shown(s, 100).map(x => x[1]);
        """, lang="en")
        self.assertEqual(got, ["6,332 installs on Steam Deck · t1", "1 install on Steam Deck · t2"])


if __name__ == "__main__":
    unittest.main()

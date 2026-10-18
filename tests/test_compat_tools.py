import json
import shutil
import subprocess
import unittest

import main

FAKE_STEAM = r"""
globalThis.window = globalThis;
const asked = [];
const answer = {ok: true, tools: [
  {name: "proton_experimental", display_name: "Proton Experimental", is_default: false},
  {name: "proton_11", display_name: "Proton 11.0-2", is_default: true},
]};
const compatModule = (je,te,t)=>{"use strict";t.d(te,{jI:()=>S});var e=1,j;(O=>{function m(k){return asked.push(k),Promise.resolve({BSuccess:()=>answer.ok,GetEResult:()=>2,Body:()=>({toObject:()=>({tools:answer.tools,aliases:[]})})})}O.GetCompatTools=m,O.GetCompatToolsHandler={name:"CompatManager.GetCompatTools#1"}})(j||(j={}));const S={};};
const req = id => ({});
req.m = {"10": () => 0, "36581": compatModule};
req.d = (exp, defs) => { for (const k in defs) Object.defineProperty(exp, k, {enumerable: true, get: defs[k]}) };
window.webpackChunksteamui = {push: ([ids, mods, run]) => run(req)};
globalThis.SteamClient = {Apps: {}};
const tools = COMPAT_TOOLS;
"""


@unittest.skipUnless(shutil.which("node"), "нужен node")
class CompatToolsInSteam(unittest.TestCase):
    def run_js(self, scenario):
        script = (FAKE_STEAM.replace("COMPAT_TOOLS", main.COMPAT_TOOLS_JS)
                  + "(async () => {" + scenario + "})().then(r => console.log(JSON.stringify(r)), "
                  + "e => console.log(JSON.stringify({error: String(e.message || e)})));")
        done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30, check=True)
        return json.loads(done.stdout)

    def test_new_steam_asks_compat_manager(self):
        got = self.run_js("return [await tools(3330089986), asked];")
        self.assertEqual(got, [[{"strToolName": "proton_experimental", "strDisplayName": "Proton Experimental"},
                                {"strToolName": "proton_11", "strDisplayName": "Proton 11.0-2"}],
                               [{"appid": 3330089986}]])

    def test_old_steam_uses_its_own_list(self):
        got = self.run_js("""
          SteamClient.Apps.GetAvailableCompatTools = a => Promise.resolve([{strToolName: "proton_9", strDisplayName: "Proton 9.0-4", a}]);
          return [await tools(7), asked];
        """)
        self.assertEqual(got, [[{"strToolName": "proton_9", "strDisplayName": "Proton 9.0-4", "a": 7}], []])

    def test_steam_refusal_is_an_error(self):
        got = self.run_js("answer.ok = false; return await tools(7);")
        self.assertIn("error", got)


if __name__ == "__main__":
    unittest.main()

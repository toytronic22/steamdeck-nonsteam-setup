import os
import tempfile
import unittest
from unittest import mock

import layouts


class FuseStep(unittest.TestCase):
    def test_not_patched_does_not_count(self):
        self.assertEqual(layouts.fuse_step(2, None), (2, False))

    def test_quick_loss_counts(self):
        self.assertEqual(layouts.fuse_step(0, 5), (1, False))
        self.assertEqual(layouts.fuse_step(1, layouts.QUICK - 0.1), (2, False))

    def test_third_quick_loss_blows(self):
        self.assertEqual(layouts.fuse_step(layouts.FUSE_LIMIT - 1, 1), (layouts.FUSE_LIMIT, True))

    def test_long_life_resets(self):
        self.assertEqual(layouts.fuse_step(2, layouts.QUICK), (0, False))


class Fuse(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = 1000.0
        patches = [
            mock.patch.object(layouts, "DATA", self.tmp.name),
            mock.patch.object(layouts, "FUSE", os.path.join(self.tmp.name, "fuse.json")),
            mock.patch.object(layouts, "LAYOUTS_OFF", os.path.join(self.tmp.name, "off.json")),
            mock.patch.object(layouts.time, "monotonic", lambda: self.now),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def crash_after(self, fuse, seconds):
        fuse.patched()
        self.now += seconds
        fuse.alive()
        return fuse.lost()

    def test_three_quick_crashes_switch_layouts_off(self):
        fuse = layouts.Fuse()
        self.assertFalse(self.crash_after(fuse, 10))
        self.assertFalse(self.crash_after(fuse, 10))
        self.assertTrue(self.crash_after(fuse, 10))
        self.assertEqual(layouts.read_json(layouts.LAYOUTS_OFF)["quick"], 3)

    def test_count_survives_restart_of_service(self):
        self.crash_after(layouts.Fuse(), 10)
        self.crash_after(layouts.Fuse(), 10)
        self.assertTrue(self.crash_after(layouts.Fuse(), 10))

    def test_stable_minute_resets_count(self):
        fuse = layouts.Fuse()
        self.crash_after(fuse, 10)
        self.crash_after(fuse, 10)
        fuse.patched()
        self.now += layouts.QUICK
        fuse.alive()
        self.assertEqual(layouts.read_json(layouts.FUSE), {"quick": 0})
        self.assertFalse(fuse.lost())
        self.assertFalse(self.crash_after(fuse, 10))
        self.assertFalse(os.path.exists(layouts.LAYOUTS_OFF))

    def test_loss_before_patch_does_not_count(self):
        fuse = layouts.Fuse()
        for _ in range(5):
            self.assertFalse(fuse.lost())
        self.assertFalse(os.path.exists(layouts.LAYOUTS_OFF))

    def test_report_says_switched_off_without_touching_steam(self):
        layouts.write_json(layouts.LAYOUTS_OFF, {"at": "2026-10-03 12:00", "quick": 3})
        with mock.patch.object(layouts, "Cdp", side_effect=AssertionError("Steam touched")):
            line = layouts.report_line({})
        self.assertIn("выключены предохранителем (2026-10-03 12:00)", line)
        self.assertIn("запусти установку ещё раз", line)
        self.assertIn(layouts.INSTALL_CMD, line)


class Watch(unittest.TestCase):
    def test_does_not_patch_when_switched_off(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        off = os.path.join(tmp.name, "off.json")
        with open(off, "w") as f:
            f.write("{}")

        class FakeCdp:
            evals = []

            def __init__(self, timeout=60):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def eval(self, js):
                self.evals.append(js)
                return True

            def call(self, *args):
                raise AssertionError("patched while switched off")

        ticks = []

        def sleep(_):
            ticks.append(1)
            if len(ticks) > 3:
                raise KeyboardInterrupt

        with mock.patch.object(layouts, "Cdp", FakeCdp), \
                mock.patch.object(layouts, "LAYOUTS_OFF", off), \
                mock.patch.object(layouts, "BUTTON_PENDING", os.path.join(tmp.name, "none")), \
                mock.patch.object(layouts, "FUSE", os.path.join(tmp.name, "fuse.json")), \
                mock.patch.object(layouts.time, "sleep", sleep), \
                mock.patch("builtins.print"):
            with self.assertRaises(KeyboardInterrupt):
                layouts.watch()
        self.assertEqual(FakeCdp.evals, [])


if __name__ == "__main__":
    unittest.main()

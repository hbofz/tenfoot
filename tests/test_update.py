"""system/tenfoot-update against a local feed: signed fake releases whose install.sh just records its version."""
import base64
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import tarfile
import tempfile
import threading
import time
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("tenfoot_update", str(ROOT / "system" / "tenfoot-update"))
_spec = importlib.util.spec_from_loader("tenfoot_update", _loader)
up = importlib.util.module_from_spec(_spec)
_loader.exec_module(up)

INSTALL_SH = '#!/bin/sh\ncat VERSION > "$TENFOOT_TEST_DIR/version"\n[ ! -e FAIL ]\n'


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class Updater(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.feed, self.dir = self.tmp / "feed", self.tmp / "state"
        self.feed.mkdir()
        (self.dir / "releases").mkdir(parents=True)
        self.key = Ed25519PrivateKey.generate()
        pub = self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(self.feed)))
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{self.http.server_port}/"
        self.reboots = []
        self.healthy = True
        for name, value in {"FEED": base, "DIR": self.dir, "PUBLIC_KEY": base64.b64encode(pub).decode(),
                            "CONFIG": self.tmp / "config.toml", "synced": lambda: True, "AIRPLAY_UNIT": self.tmp / "none", "NIGHT": range(24),
                            "HEALTH_WAIT": 0, "reboot": lambda: self.reboots.append(1),
                            "answers": lambda url: self.healthy}.items():
            p = mock.patch.object(up, name, value)
            p.start()
            self.addCleanup(p.stop)
        mock.patch.dict(os.environ, TENFOOT_TEST_DIR=str(self.dir)).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.release("0.1.0", publish=False)
        self.box("0.1.0")

    def box(self, version):
        """A box as install.sh leaves it: that version installed, its release kept to go back to."""
        (self.dir / "version").write_text(version + "\n")
        rel = self.dir / "releases" / version
        rel.mkdir(exist_ok=True)
        self.write_release(rel, version)

    @staticmethod
    def write_release(d, version, fail=False):
        (d / "VERSION").write_text(version + "\n")
        (d / "install.sh").write_text(INSTALL_SH)
        (d / "install.sh").chmod(0o755)
        if fail:
            (d / "FAIL").write_text("")

    def release(self, version, publish=True, fail=False, tamper=False, sign_with=None, tar_version=None):
        """Put a release on the feed: its tarball, update.json and the signature."""
        src = self.tmp / f"src-{version}"
        src.mkdir(exist_ok=True)
        self.write_release(src, tar_version or version, fail)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            for f in src.iterdir():
                t.add(f, arcname=f.name)
        data = buf.getvalue()
        if not publish:
            return
        name = f"tenfoot-{version}.tar.gz"
        (self.feed / name).write_bytes(data + (b"x" if tamper else b""))
        m = json.dumps({"version": version, "notes": f"notes {version}", "url": up.FEED + name,
                        "sha256": hashlib.sha256(data).hexdigest()}).encode()
        (self.feed / "update.json").write_bytes(m)
        (self.feed / "update.json.sig").write_bytes((sign_with or self.key).sign(m))

    def status(self):
        return json.loads((self.dir / "status.json").read_text())

    def test_versions(self):
        self.assertTrue(up.newer("0.10.0", "0.9.1"))
        self.assertFalse(up.newer("0.1.0", "0.1.0"))
        self.assertTrue(up.newer("0.1.0", None))
        for bad in ("1", "0.1.0-rc1", "../0.1", "1.2.3.4", 5):
            with self.assertRaises(ValueError):
                up.parse(bad)

    def test_update_reboot_keep(self):
        self.release("0.2.0")
        up.main("check")
        st = self.status()
        self.assertEqual((st["version"], st["state"], st["pending"]["phase"], len(self.reboots)), ("0.2.0", "installing", "verifying", 1))
        up.main("check")  # after the reboot: it works, so it stays
        st = self.status()
        self.assertEqual((st["version"], st["state"], st.get("pending"), st["available"]), ("0.2.0", "idle", None, None))
        self.assertEqual([p.name for p in (self.dir / "releases").iterdir()], ["0.2.0"])  # the old one is let go
        up.main("check")  # nothing newer: no more reboots
        self.assertEqual(len(self.reboots), 1)

    def test_broken_release_rolls_back_and_isnt_tried_again(self):
        self.release("0.2.0")
        up.main("check")
        self.healthy = False
        up.main("check")
        st = self.status()
        self.assertEqual((st["version"], st["bad"], len(self.reboots)), ("0.1.0", ["0.2.0"], 2))
        self.assertIn("Went back to 0.1.0", st["error"])
        self.assertEqual([p.name for p in (self.dir / "releases").iterdir()], ["0.1.0"])  # the broken copy is gone
        self.healthy = True
        up.main("check")
        self.assertEqual((self.status()["available"], len(self.reboots)), (None, 2))
        self.release("0.2.1")  # a fixed one is fine
        up.main("check")
        self.assertEqual(self.status()["version"], "0.2.1")

    def test_failed_install_rolls_back_at_once(self):
        self.release("0.2.0", fail=True)
        up.main("check")
        st = self.status()
        self.assertEqual((st["version"], st["bad"], st.get("pending")), ("0.1.0", ["0.2.0"], None))
        self.assertIn("install failed", st["error"])

    def test_power_cut_during_install_rolls_back(self):
        self.release("0.2.0")
        with mock.patch.object(up, "run_install", side_effect=KeyboardInterrupt):  # stands in for the power going
            with self.assertRaises(KeyboardInterrupt):
                up.main("check")
        self.assertEqual(self.status()["pending"]["phase"], "installing")
        up.main("check")  # the next boot
        self.assertEqual((self.status()["version"], self.status()["bad"]), ("0.1.0", ["0.2.0"]))

    def test_nothing_unsigned_tampered_or_older(self):
        for kwargs in ({"sign_with": Ed25519PrivateKey.generate()}, {"tamper": True}, {"tar_version": "0.9.0"}):
            self.release("0.2.0", **kwargs)
            try:
                up.main("check")
            except (InvalidSignature, ValueError):
                pass
            self.assertEqual((self.status()["version"], self.reboots), ("0.1.0", []), kwargs)
        self.release("0.0.9")
        up.main("check")
        self.assertEqual((self.status()["available"], self.reboots), (None, []))

    def test_day_only_tells(self):
        self.release("0.2.0")
        with mock.patch.object(up, "NIGHT", range(0)):
            up.main("check")
        st = self.status()
        self.assertEqual((st["version"], st["available"]["version"], st["available"]["notes"], self.reboots), ("0.1.0", "0.2.0", "notes 0.2.0", []))
        up.main("now")  # the phone's button
        self.assertEqual((self.status()["version"], len(self.reboots)), ("0.2.0", 1))

    def test_no_night_install_on_an_unsynced_clock(self):
        self.release("0.2.0")
        with mock.patch.object(up, "synced", lambda: False):
            up.main("check")
        self.assertEqual((self.status()["available"]["version"], self.reboots), ("0.2.0", []))

    def test_reboot_stuck_only_when_safe(self):
        def ask(uptime=7200, users="1001 tenfoot yes lingering\n", updating=False):
            run = mock.Mock(return_value=mock.Mock(stdout=users))
            with mock.patch.object(up.time, "clock_gettime", lambda c: uptime), mock.patch.object(up.subprocess, "run", run):
                try:
                    up.reboot_stuck(updating)
                    return "rebooted"
                except SystemExit as e:
                    return f"declined {e.code}"
        self.assertEqual(ask(), "rebooted")
        self.assertEqual(ask(uptime=600), "declined 1")  # within an hour of starting: never a reboot loop
        self.assertEqual(ask(users="1001 tenfoot yes active\n1000 couch no active\n"), "declined 1")  # an admin's in
        self.assertEqual(ask(updating=True), "declined 1")
        self.assertEqual(ask(users="1001 tenfoot yes active\n1000 couch yes lingering\n"), "rebooted")  # nobody there
        self.assertEqual(len(self.reboots), 2)

    def test_a_download_cut_short_doesnt_stay_updating(self):
        (self.dir / "status.json").write_text(json.dumps({"state": "downloading", "bad": []}))
        with mock.patch.object(up, "NIGHT", range(0)):
            up.main("check")
        self.assertEqual(self.status()["state"], "idle")

    SIM = """Inst libexpat1 [2.8.3-1~deb13u1] (2.9.0-1~deb13u1 Debian-Security:13/stable-security [arm64])
Inst tzdata [2026c-0+deb13u1] (2026f-0+deb13u1 Debian:13-updates/stable-updates [all])
Inst libcamera0.7 [0.7.2+rpt20260817-1] (0.7.2+rpt20261009-1 Raspberry Pi Foundation:stable [arm64]) []
Inst ffmpeg [7:7.1.1-1+rpt3] (7:7.1.2-0+deb13u1 Debian-Security:13/stable-security [arm64])
Inst libwidevinecdm0 [4.10.2662.3+1] (4.10.2830.0+1 Raspberry Pi Foundation:stable [arm64])
Conf libexpat1 (2.9.0-1~deb13u1 Debian-Security:13/stable-security [arm64])
"""

    def test_os_plan(self):
        self.assertEqual(up.os_plan(self.SIM, []), [("libexpat1", "2.9.0-1~deb13u1"), ("tzdata", "2026f-0+deb13u1"),
                                                    ("libwidevinecdm0", "4.10.2830.0+1")])  # not Raspberry Pi's, nor their fork of ffmpeg
        self.assertEqual(up.os_plan(self.SIM, ["tzdata=2026f-0+deb13u1"])[1][0], "libwidevinecdm0")  # broke the box once: never again

    def os_box(self, extra="", fail=lambda args: False, changed=lambda n: True):
        """apt and dpkg, faked: returns the calls made. fail(args) -> that command fails; changed(n) -> whether the
        installed versions differ the n-th time they're asked for."""
        calls, asked = [], [0]

        def run(args, **kw):
            calls.append(args)
            out = ""
            if args[:1] == ["apt-get"] and "-s" in args:
                out = self.SIM if "upgrade" in args else "\n".join(f"Inst {n} [1] (2 Debian:13/stable [all])" for n in args[-3:]) + extra
            if args[:1] == ["dpkg-repack"]:
                for n in args[1:]:
                    (up.OS_PREV / f"{n}_old.deb").write_text("")
            if args[:1] == ["dpkg-query"]:
                asked[0] += 1
                out = "libexpat1=" + ("2" if asked[0] > 1 and changed(asked[0]) else "1")
            return mock.Mock(returncode=1 if fail(args) else 0, stdout=out, stderr="E: oops")
        p = mock.patch.object(up.subprocess, "run", run)
        p.start()
        self.addCleanup(p.stop)
        mock.patch.object(up, "OS_PREV", self.dir / "os-prev").start()
        return calls

    def test_os_update_keep(self):
        calls = self.os_box()
        up.main("os")
        st = self.status()
        self.assertEqual((st["pending"]["kind"], st["pending"]["phase"], len(self.reboots)), ("os", "verifying", 1))
        install = next(c for c in calls if c[:1] == ["apt-get"] and "install" in c and "-s" not in c and "-d" not in c)
        self.assertEqual(install[-3:], ["libexpat1", "tzdata", "libwidevinecdm0"])
        self.assertIn("Dpkg::Options::=--force-confold", install)  # never ask about config files: nobody's there
        self.assertIn("--no-remove", install)
        self.assertTrue((self.dir / "os-prev" / "tzdata_old.deb").exists())  # saved before
        up.main("check")  # after the reboot: working
        st = self.status()
        self.assertEqual((st.get("pending"), st["state"]), (None, "idle"))
        self.assertFalse((self.dir / "os-prev").exists())

    def test_os_update_rolls_back(self):
        calls = self.os_box()
        up.main("os")
        self.healthy = False
        up.main("check")
        st = self.status()
        self.assertEqual((st.get("pending"), st["os_failed"]["libexpat1=2.9.0-1~deb13u1"]), (None, 1))
        self.assertIn("previous versions are back", st["error"])
        self.assertEqual(calls[-1][:2], ["dpkg", "-i"])
        self.assertEqual(len(self.reboots), 2)
        self.assertEqual(len(up.os_plan(self.SIM, [k for k, n in st["os_failed"].items() if n >= 2])), 3)  # once: tried again
        up.main("os")
        self.healthy = True
        self.healthy = False
        up.main("check")
        self.assertEqual(up.os_plan(self.SIM, [k for k, n in self.status()["os_failed"].items() if n >= 2]), [])  # twice: not again

    def test_no_network_at_4am_is_not_a_bad_update(self):
        for fail in (lambda a: "-d" in a, lambda a: a[:1] == ["apt-get"] and "install" in a and "-s" not in a and "-d" not in a):
            self.reboots.clear()
            (self.dir / "status.json").unlink(missing_ok=True)
            self.os_box(fail=fail, changed=lambda n: False)
            up.main("os")
            st = self.status()
            self.assertEqual((st.get("pending"), st.get("os_failed"), self.reboots), (None, None, []))

    def test_a_half_done_install_rolls_back(self):
        self.os_box(fail=lambda a: a[:1] == ["apt-get"] and "install" in a and "-s" not in a and "-d" not in a)
        up.main("os")
        self.assertIn("didn't install cleanly", self.status()["error"])
        self.assertEqual(len(self.reboots), 1)

    def test_a_rollback_cut_short_resumes(self):
        calls = self.os_box()
        up.main("os")
        st = self.status()
        st["pending"].update(phase="rolling-back", why="left the TV not starting properly")  # the power went mid dpkg -i
        (self.dir / "status.json").write_text(json.dumps(st))
        up.main("check")
        self.assertEqual((self.status().get("pending"), calls[-1][:2]), (None, ["dpkg", "-i"]))

    def test_os_update_waits_if_more_would_change(self):
        for extra in ("\nInst libwlroots-0.20 [1] (2 Raspberry Pi Foundation:stable [arm64])", "\nRemv ntfs-3g [1]"):
            calls = self.os_box(extra=extra)
            up.main("os")
            self.assertEqual((self.status().get("pending"), self.reboots), (None, []))
            self.assertFalse(any(c[:1] == ["dpkg-repack"] for c in calls))

    def test_os_updates_only_on_their_night(self):
        self.os_box()
        days = {}
        for wday in range(7):
            with mock.patch.object(up.time, "localtime", lambda *a, w=wday: time.struct_time((2026, 11, 1, 4, 0, 0, w, 305, 0))):
                (self.dir / "status.json").unlink(missing_ok=True)
                self.reboots.clear()
                up.main("check")
                days[wday] = len(self.reboots)
        self.assertEqual(days, {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 1})

    def test_modes(self):
        self.release("0.2.0")
        (self.tmp / "config.toml").write_text('updates = "notify"\n')
        up.main("check")
        self.assertEqual((self.status()["available"]["version"], self.status()["mode"], self.reboots), ("0.2.0", "notify", []))
        (self.tmp / "config.toml").write_text('updates = "off"\n')
        up.main("check")
        self.assertEqual((self.status()["available"], self.reboots), (None, []))
        (self.tmp / "config.toml").write_text('updates = "of\n')  # broken: auto, so security fixes still come
        self.assertEqual(up.mode(), "auto")

    def test_tenfoot_reads_the_status(self):
        from tenfoot import updates
        self.release("0.2.0")
        with mock.patch.object(up, "NIGHT", range(0)):
            up.main("check")
        with mock.patch.object(updates, "STATUS", self.dir / "status.json"):
            s = updates.status()
        self.assertEqual((s["available"]["version"], s["state"], s["version"]), ("0.2.0", "idle", (ROOT / "VERSION").read_text().strip()))
        with mock.patch.object(updates, "STATUS", self.tmp / "missing.json"):
            self.assertEqual(updates.status()["state"], "idle")


if __name__ == "__main__":
    unittest.main()

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
                            "CONFIG": self.tmp / "config.toml", "AIRPLAY_UNIT": self.tmp / "none", "NIGHT": range(24),
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

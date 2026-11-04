"""python3 -m unittest discover tests : the parts with no TV or browser to hand."""
import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import numpy as np
import websocket
from cryptography.fernet import Fernet

from tenfoot import apps, cec, clock, config, health, idle, report, wipe, settings as phone_settings, controls, cursor, kiosk, links, lyrics, server, setup, sites, spotify, visualizer, watcher
from tenfoot.apps import app_of, to_url

JF = "http://192.168.1.20:8096"
SEARCH = "https://www.google.com/search?q="
SETTINGS = config.Settings(jellyfin_url=JF)
APPS = apps.load_apps(SETTINGS)
URLS = apps.app_urls(APPS)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"


class Config(unittest.TestCase):
    def write(self, text):
        d = tempfile.mkdtemp()
        p = Path(d) / "config.toml"
        p.write_text(text)
        return p

    def test_defaults_without_a_file(self):
        s = config.load("/nonexistent/config.toml")
        self.assertEqual((s.remote_mode, s.listen_host, s.screen), ("lan", "0.0.0.0", (1920, 1080)))

    def test_render_writes_the_home_screens_data(self):
        from tenfoot.__main__ import render
        run = Path(tempfile.mkdtemp())
        with mock.patch.object(config, "RUN", run):
            render(config.Settings())
        self.assertIn("window.APPS", (run / "config.js").read_text())

    def test_values(self):
        s = config.load(self.write('name = "Den"\nremote_mode = "tailscale"\nlatitude = 1.5\n'))
        self.assertEqual((s.name, s.listen_host, s.latitude), ("Den", "127.0.0.1", 1.5))

    def test_bad_values_stop_the_service(self):
        for text in ('nmae = "typo"\n', 'remote_mode = "public"\n', 'remote_mode = "url"\n'):
            with self.assertRaises(SystemExit):
                config.load(self.write(text))


class Clock(unittest.TestCase):
    def test_zone_names(self):
        self.assertEqual(clock.canonical("Europe/London"), "Europe/London")
        self.assertEqual(clock.canonical("UTC"), "Etc/UTC")
        self.assertEqual(clock.canonical("Asia/Calcutta"), "Asia/Kolkata")  # an old name Chrome still sends
        for bad in ("localtime", "posixrules", "../../etc/passwd", "/etc/passwd", "posix/Europe/London", "Mars/Base", "",
                    None, 5, "Europe/London\n"):
            self.assertIsNone(clock.canonical(bad), bad)

    def setUp(self):
        d = Path(tempfile.mkdtemp())
        for p in (mock.patch.object(clock, "CONFIG_DIR", d), mock.patch.object(clock, "current", lambda: "Europe/London")):
            p.start()
            self.addCleanup(p.stop)
        self.run_ = mock.patch.object(clock.subprocess, "run").start()
        self.addCleanup(mock.patch.stopall)

    def test_first_phone_sets_it_once(self):
        self.assertIsNone(clock.adopt("Mars/Base"))  # a bad guess changes nothing, and doesn't count
        self.assertIsNone(clock.adopt("UTC"))  # what privacy browsers say anywhere: doesn't count either
        self.assertFalse(clock.mark().exists())
        self.assertEqual(clock.adopt("America/Chicago"), "America/Chicago")
        self.assertEqual(self.run_.call_args[0][0], ["timedatectl", "set-timezone", "America/Chicago"])
        self.assertEqual(clock.mark().read_text(), "America/Chicago\n")
        self.assertIsNone(clock.adopt("Asia/Tokyo"))  # a guest's phone later: ignored
        self.assertEqual(self.run_.call_count, 1)
        self.assertEqual(clock.set_zone("Asia/Tokyo"), "Asia/Tokyo")  # on purpose still works
        self.run_.reset_mock()
        clock.set_zone("Europe/London")  # already the box's zone: nothing to run
        self.run_.assert_not_called()

    def test_failed_set_doesnt_count(self):
        self.run_.side_effect = subprocess.CalledProcessError(1, "timedatectl")
        self.assertIsNone(clock.adopt("America/Chicago"))
        self.assertFalse(clock.mark().exists())
        self.run_.side_effect = None
        self.assertEqual(clock.adopt("America/Chicago"), "America/Chicago")

    def test_remote_and_setup_page_pass_it_on(self):
        self.assertEqual(make_controls().handle({"a": "timezone", "tz": "America/Chicago"}), "America/Chicago")
        clock.mark().unlink()
        srv = ThreadingHTTPServer(("127.0.0.1", 0), setup.handler(WifiSetup.box(self)))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        body = json.dumps({"ssid": "Home", "password": "x", "timezone": "Asia/Kolkata"}).encode()
        with self.assertRaises(urllib.error.HTTPError):  # the Wi-Fi part fails (not in setup), the zone still lands
            urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/join", data=body, method="POST"), timeout=5)
        self.assertEqual(clock.mark().read_text(), "Asia/Kolkata\n")


class Health(unittest.TestCase):
    OK = dict(bits=0, temp_c=45, free=20 << 30, readonly=False, net="ok", weak=False)

    def titles(self, **change):
        return [p["title"] for p in health.problems(**{**self.OK, **change})]

    def test_all_good(self):
        self.assertEqual(self.titles(), [])
        self.assertEqual(health.throttle_bits("throttled=0x50005\n"), 0x50005)
        self.assertEqual(health.throttle_bits("error"), 0)

    def test_each_problem(self):
        self.assertEqual(self.titles(bits=0x50000), ["The power supply is too weak"])  # it happened earlier: still worth fixing
        self.assertEqual(self.titles(bits=0x1), ["The power supply is too weak"])
        self.assertEqual(self.titles(bits=0x5), ["The power supply is too weak"])  # throttled for power, not heat
        self.assertEqual(self.titles(bits=0x8), ["Tenfoot is too hot"])
        self.assertEqual(self.titles(temp_c=81), ["Tenfoot is too hot"])
        self.assertEqual(self.titles(free=900 << 20), ["Storage is almost full"])
        self.assertEqual(self.titles(readonly=True)[0], "The storage card is failing")
        self.assertEqual(self.titles(net="down"), ["Connected, but no internet"])
        self.assertEqual(self.titles(net="dns"), ["Websites won't load on this network"])
        self.assertEqual(self.titles(weak=True), ["Weak Wi-Fi signal"])

    def run_loop(self, net, devices, signal, rounds):
        """The real health loop on a fake clock: net(round) -> internet()'s answer; returns what it showed each round."""
        t, shown, self.checks = [0.0], [], []

        def sleep(sec):
            shown.append([p["title"] for p in health.status()])
            t[0] += sec
            if len(shown) >= rounds:
                raise StopIteration

        def run(*args):
            return {"dev": devices(len(shown)), "list": f"*:{signal}\n", "get_throttled": "throttled=0x0\n"}.get(
                next((a for a in args if a in ("dev", "list", "get_throttled") and (a != "dev" or "wifi" not in args)), ""), "")
        fs = mock.Mock(f_bavail=10 << 20, f_frsize=1024, f_flag=0)
        with mock.patch.object(health.time, "sleep", sleep), mock.patch.object(health.time, "monotonic", lambda: t[0] + 5), \
                mock.patch.object(health, "run", run), mock.patch.object(health, "internet", lambda: (self.checks.append(1), net(len(shown)))[1]), \
                mock.patch.object(health.os, "statvfs", lambda p: fs), mock.patch.object(health, "_now", []):
            with self.assertRaises(StopIteration):
                health.loop()
        return shown

    WIFI = "wifi:connected:Home\n"

    def test_loop_internet_needs_two_misses(self):
        shown = self.run_loop(lambda r: "dns" if 0 <= r < 3 else "ok", lambda r: self.WIFI, 70, rounds=6)
        self.assertEqual(shown, [[], ["Websites won't load on this network"], ["Websites won't load on this network"], [], [], []])
        # checked at once (round 0), again a minute after a miss, then every 5 minutes once fine
        self.assertEqual(len(self.checks), 4)  # rounds 0, 1, 2 (a minute apart while failing), 3 (fine), then not till 8

    def test_loop_weak_wifi_but_not_on_ethernet(self):
        self.assertEqual(self.run_loop(lambda r: "ok", lambda r: self.WIFI, 12, rounds=4)[-1], ["Weak Wi-Fi signal"])  # 3 in a row
        self.assertEqual(self.run_loop(lambda r: "ok", lambda r: "ethernet:connected:Wired\n" + self.WIFI, 12, rounds=4)[-1], [])
        self.assertEqual(self.run_loop(lambda r: "ok", lambda r: "wifi:connected:tenfoot-setup\n", 0, rounds=4)[-1], [])  # setup hotspot

    def test_internet_kinds(self):
        with mock.patch.object(health, "reaches", lambda url: True):
            self.assertEqual(health.internet(), "ok")
        with mock.patch.object(health, "reaches", lambda url: url != health.DOH), \
                mock.patch.object(health.socket, "getaddrinfo", lambda *a: [()]):
            self.assertEqual(health.internet(), "dns")  # the internet works, the browser's secure DNS doesn't
        with mock.patch.object(health, "reaches", lambda url: False), \
                mock.patch.object(health.socket, "getaddrinfo", mock.Mock(side_effect=OSError)):
            self.assertEqual(health.internet(), "down")


class PhoneSettings(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / "config.toml").write_text((config.ROOT / "config.example.toml").read_text())
        for p in (mock.patch.object(config, "CONFIG_DIR", self.d), mock.patch.object(clock, "CONFIG_DIR", self.d),
                  mock.patch.object(config, "RUN", self.d / "run"), mock.patch.object(clock, "set_zone", lambda z: z),
                  mock.patch.object(phone_settings, "rename_services", mock.Mock()), mock.patch.object(controls.threading, "Timer", mock.Mock())):
            p.start()
            self.addCleanup(p.stop)

    def test_edit_keeps_the_rest(self):
        text = 'name = "Tenfoot"    # what it is called\n# latitude = 51.5\nspotify = true\n'
        out = phone_settings.edit(text, {"name": 'Den "TV"', "latitude": 44.45, "place": "Lisbon"})
        self.assertEqual(out, 'name = "Den \\"TV\\""\nlatitude = 44.45\nspotify = true\nplace = "Lisbon"\n')

    def test_change_from_the_phone(self):
        c = make_controls()
        out = c.handle({"a": "settings", "k": "set", "by": "house", "name": "Den",
                        "weather": {"latitude": 38.7223, "longitude": -9.1393, "timezone": "Europe/Lisbon", "place": "Lisbon, Portugal"},
                        "unit": "fahrenheit", "updates": "notify"})
        s = config.load(self.d / "config.toml")
        self.assertEqual((s.name, s.latitude, s.place, s.temperature_unit, s.updates), ("Den", 38.7223, "Lisbon, Portugal", "fahrenheit", "notify"))
        self.assertIn("# How phones reach the remote", (self.d / "config.toml").read_text())  # the comments stay
        self.assertEqual(clock.mark().read_text(), "Europe/Lisbon\n")  # the place set the clock, for good
        self.assertIn('"temperatureUnit": "fahrenheit"', (self.d / "run" / "config.js").read_text())  # the home screen's, now
        phone_settings.rename_services.assert_called_once_with("Den")
        self.assertEqual(out["name"], "Den")

    def test_refused(self):
        c = make_controls()
        before = (self.d / "config.toml").read_text()
        for cmd in ({"by": "guest", "unit": "celsius"}, {"name": "x" * 31}, {"name": 'a"b'}, {"name": "%h$x"}, {"name": "-TV"}, {"updates": "off"},
                    {"weather": {"latitude": 1, "longitude": 2, "place": "\U0001F600"}},
                    {"unit": "kelvin"}, {"weather": {"latitude": 91, "longitude": 0}}, {"weather": {"latitude": "x", "longitude": 0}}, {}):
            with self.assertRaises((ValueError, KeyError)):
                c.handle({"a": "settings", "k": "set", "by": "house", **cmd})
        self.assertEqual((self.d / "config.toml").read_text(), before)
        self.assertEqual(make_controls().handle({"a": "settings", "by": "guest"}), {"canChange": False})  # not even where it is
        self.assertTrue(make_controls().handle({"a": "settings", "by": "house"})["canChange"])

    def test_hand_edited_keys_are_found(self):
        out = phone_settings.edit('  latitude = 1.0\n"name" = "x"\n', {"latitude": 2.5, "name": "Den"})
        self.assertEqual(out, 'latitude = 2.5\nname = "Den"\n')


class Idle(unittest.TestCase):
    S = config.Settings(screensaver_minutes=10, standby_hours=4)
    APP = "https://www.netflix.com/browse"

    def setUp(self):
        mock.patch.object(idle, "dimmed", False).start()
        mock.patch.object(idle, "browser_audio", lambda: False).start()
        self.addCleanup(mock.patch.stopall)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_overlay_scripts_compile(self):
        from tenfoot import overlay
        for js in (overlay.dim_js(True), overlay.dim_js(False), overlay.toast_js("x", 1000), overlay.volume_js(50, False), idle.PROBE):
            subprocess.run(["node", "-e", "new Function(process.argv[1])", js], check=True, capture_output=True)

    def test_decide(self):
        d = lambda idle_s, quiet_s=10 ** 6, music=False, url=self.APP, warned=None: idle.decide(idle_s, quiet_s, music, url, self.S, warned)
        self.assertIsNone(d(599))
        self.assertEqual(d(600), "dim")
        self.assertIsNone(d(600, quiet_s=0))  # a show playing: never dimmed
        self.assertIsNone(d(3000, quiet_s=20))  # the gap between two episodes of a binge isn't quiet
        self.assertIsNone(d(600, url=apps.page_url("home.html")))  # the home screen has its own
        self.assertEqual(d(4 * 3600, quiet_s=0), "warn")  # hours of autoplay with nobody there
        self.assertEqual(d(4 * 3600, quiet_s=0, warned=True), "standby")
        self.assertNotIn(d(4 * 3600, music=True), ("warn", "standby"))  # music on: someone's listening
        self.assertIsNone(idle.decide(10 ** 6, 10 ** 6, False, self.APP, config.Settings(screensaver_minutes=0, standby_hours=0), None))
        idle.dimmed = True
        self.assertEqual(d(5), "undim")

    def test_only_presses_count(self):
        c = make_controls()
        idle.last = 0
        c.handle({"a": "state"})
        c.handle({"a": "settings"})
        self.assertEqual(idle.last, 0)  # the phone checking in
        c.handle({"a": "key", "k": "down"})
        self.assertGreater(idle.last, 0)

    def test_the_waking_press_only_wakes(self):
        inp, b = FakeInput(), FakeBrowser()
        c = make_controls(inp=inp, browser=b)
        idle.dimmed = True
        with mock.patch.object(b, "evaluate", lambda js: {"result": {"value": True}}):
            c.handle({"a": "key", "k": "down"})  # the page was dim: this press only wakes it
        self.assertEqual((idle.dimmed, inp.log), (False, []))
        c.handle({"a": "key", "k": "down"})
        self.assertEqual(len(inp.log), 1)
        idle.dimmed = True
        with mock.patch.object(b, "evaluate", lambda js: {"result": {"value": False}}):
            c.handle({"a": "key", "k": "down"})  # we thought so, but the page had moved on and wasn't: not swallowed
        self.assertEqual(len(inp.log), 2)

    def run_loop(self, pages, tv, rounds_end):
        """The loop on a fake clock; pages(t) -> what the page says; returns the scripts it ran."""
        t, calls, dim = [0.0], [], [False]

        class Page:
            def evaluate(self, js):
                calls.append(js)
                if js != idle.PROBE and "tenfoot-dim" in js:
                    dim[0] = "!true" in js  # it goes dark when told to
                if js == idle.PROBE:
                    p = pages(t[0])
                    return {"result": {"value": json.dumps({**p, "dimmed": dim[0] if p["dimmed"] is None else p["dimmed"]})}}
                return {"result": {"value": True}}

        def sleep(sec):
            t[0] += sec
            if t[0] > rounds_end:
                raise StopIteration
        with mock.patch.object(idle.time, "sleep", sleep), mock.patch.object(idle.time, "monotonic", lambda: t[0]), \
                mock.patch.object(idle, "last", 0.0):
            with self.assertRaises(StopIteration):
                idle.loop(Page(), tv, None, self.S)
        return calls

    def page(self, playing=False, dimmed=None, url=None):  # dimmed None: as the page was last told
        return {"playing": playing, "since": 1e9, "url": url or self.APP, "dimmed": dimmed}

    def test_loop_warns_then_turns_off(self):
        tv = mock.Mock(power="on", showing=True)
        calls = self.run_loop(lambda t: self.page(playing=True), tv, 4 * 3600 + 200)
        tv.set_power.assert_called_once_with("off")
        tv.on_off.assert_called_once()
        self.assertTrue(any("turns off in a minute" in js for js in calls))
        self.assertEqual(len([js for js in calls if "tenfoot-dim" in js and js != idle.PROBE]), 1)  # dimmed only at the end

    def test_not_while_on_another_input(self):
        tv = mock.Mock(power="on", showing=False)
        self.run_loop(lambda t: self.page(playing=True), tv, 4 * 3600 + 200)
        tv.set_power.assert_not_called()

    def test_a_new_page_while_dim_is_dimmed_again(self):
        # dimmed at 10 minutes; at 15 the page reloads by itself (its overlay gone): dimmed again, not left bright
        state, dims = {"dim": False, "t": 0}, []

        def page(t):
            if state["t"] < 900 <= t:
                state["dim"] = False  # the reload
            state["t"] = t
            return self.page(dimmed=state["dim"])
        real = idle.set_dim

        def set_dim(browser, on):
            state["dim"] = on
            dims.append((state["t"], on))
            return real(browser, on)
        with mock.patch.object(idle, "set_dim", set_dim):
            self.run_loop(page, mock.Mock(power="on", showing=True), 1000)
        self.assertEqual(dims, [(600, True), (900, True)])

    def test_sound_from_a_frame_counts_as_playing(self):
        with mock.patch.object(idle, "browser_audio", lambda: True):
            calls = self.run_loop(lambda t: self.page(), mock.Mock(power="on", showing=True), 1200)
        self.assertFalse([js for js in calls if js != idle.PROBE and "tenfoot-dim" in js])


class Report(unittest.TestCase):
    def test_nothing_secret_survives(self):
        house, guest = "Abc123def456ghi789jkl012", links.guest_token("Abc123def456ghi789jkl012")
        log = (f"http: GET /{house}/api link=house from=192.168.1.20 ua=Mozilla\n"
               f"opened https://www.youtube.com/results?search_query=private+stuff and http://10.0.0.5:8096/web/#/x\n"
               f"qr: http://{guest[:10]}x/ {guest} hotspot pw hunter22pw tailnet box.tail1234.ts.net mac b8:27:eb:12:34:56\n"
               "sam opened Spotify for spotifyuser42; same thing; Den TV in Lisbon, fe80::1:2:3:4 2a10:50c0:0:0:0:0:ad1:ff\n"
               "2026-11-03T04:12:33-06:00 tenfoot python3[837]: kiosk: page not answering\n")
        out = report.redact(log, [house, guest, "hunter22pw", "spotifyuser42"], ["sam", "Den TV", "Lisbon"])
        for secret in (house, guest, "hunter22pw", "spotifyuser42", "private", "192.168.1.20", "10.0.0.5", "tail1234",
                       "b8:27:eb", "Den TV", "Lisbon", "fe80"):
            self.assertNotIn(secret, out)
        self.assertIn("<url www.youtube.com>", out)  # the host stays: which site
        self.assertIn("same thing", out)  # a name is replaced as a word, not inside others
        self.assertIn("2026-11-03T04:12:33-06:00", out)  # times aren't addresses
        self.assertNotIn("2a10", out)
        self.assertNotIn("sam opened", out)

    def test_listening_and_other_personal_things(self):
        log = ('go-librespot[1]: level=info msg="loaded track \\"Bohemian Rhapsody\\" uri=spotify:track:4u7EnebtmKWzUH433cf5Qv"\n'
               "opened https://www.youtube.com/results?search_query=sam+cooke+live\n"
               "LISBON lisbon; azzam-tv kernel; mail me@example.com; nmcli ['dev', 'wifi', 'connect', 'Home', 'password', 'hunter2']\n")
        out = report.redact(log, [], ["sam", "Lisbon", "azzam-tv"])
        for gone in ("Bohemian", "Rhapsody", "cooke", "LISBON", "lisbon", "azzam-tv", "me@example.com", "hunter2"):
            self.assertNotIn(gone, out)
        self.assertIn("(a track: left out)", out)
        out = report.redact("'password', \"it's-secret\" https://bob:pw123@nas:8096/web", [], [])
        for gone in ("it's-secret", "bob", "pw123"):
            self.assertNotIn(gone, out)

    def test_the_hostname_is_personal_unless_its_the_default(self):
        c = make_controls()
        with mock.patch.object(report.links, "load_token", lambda: "Abc123def456ghi789jkl012"), \
                mock.patch.object(report.links, "people", lambda: {}):
            for host, personal in (("raspberrypi", False), ("tenfoot", False), ("azzam-tv", True)):
                with mock.patch.object(report.socket, "gethostname", lambda h=host: h):
                    self.assertEqual(host in report.known_secrets(c)[1], personal, host)

    def test_a_failing_part_doesnt_sink_the_report(self):
        c = make_controls()
        with mock.patch.object(report.cec, "connected_device", mock.Mock(side_effect=subprocess.TimeoutExpired("cec-ctl", 10))), \
                mock.patch.object(report.health, "run", mock.Mock(side_effect=OSError("no nmcli"))), \
                mock.patch.object(report, "known_secrets", lambda c: (["Abc123def456ghi789jkl012"], [])):
            text = report.build(c)
        self.assertIn("== TV over HDMI-CEC ==\n(couldn't: TimeoutExpired", text)
        self.assertIn("== Settings ==", text)
        with mock.patch.object(report, "known_secrets", mock.Mock(side_effect=OSError)):
            with self.assertRaises(OSError):  # no secrets to take out: no report at all
                report.build(c)

    def test_route_and_who(self):
        self.assertEqual(links.route("/tok/report.txt", lambda t: "house"), ("report", "house"))


class Wipe(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.conf = self.home / ".config/tenfoot"
        self.conf.mkdir(parents=True)
        (self.conf / "config.toml").write_text('name = "Den"\nlatitude = 1.5\nplace = "Lisbon"\nupdates = "notify"\n'
                                                'display_mode = "1280x720@60"\njellyfin_url = "http://192.168.1.20:8096"\n')
        for f in ("token", "people", "setup-password", "timezone-set"):
            (self.conf / f).write_text("x")
        (self.home / ".config/go-librespot/profiles").mkdir(parents=True)
        (self.home / ".config/go-librespot/state.json").write_text("{}")
        (self.home / ".config/go-librespot/profiles/a").write_text("")
        self.calls = []

        def run(*args):
            self.calls.append(args)
            out = "u1:802-11-wireless\nu2:loopback\nu3:802-11-wireless\n" if args[:2] == ("nmcli", "-t") else ""
            return mock.Mock(stdout=out, returncode=0)
        for p in (mock.patch.object(config, "CONFIG_DIR", self.conf), mock.patch.object(wipe, "CONFIG_DIR", self.conf),
                  mock.patch.object(wipe.Path, "home", lambda: self.home), mock.patch.object(wipe, "run", run),
                  mock.patch.object(wipe.kiosk, "restart_chromium", lambda p: self.calls.append(("restart chromium",))),
                  mock.patch.object(wipe, "_asked", {}), mock.patch.object(wipe.getpass, "getuser", lambda: "tenfoot"),
                  mock.patch.object(wipe.phone_settings, "rename_services", lambda n: self.calls.append(("rename", n))),
                  mock.patch.object(config, "RUN", self.home / "run"), mock.patch.object(wipe.time, "sleep", lambda s: None),
                  mock.patch.object(wipe, "_asked_at", [-1e9])):
            p.start()
            self.addCleanup(p.stop)

    def tv(self, own_page=True):
        """A browser whose page is the TV's own (file://) or a website's: SHOW only works on the first."""
        b = FakeBrowser()
        b.shown = []

        def evaluate(js):
            if "location.protocol" in js:
                if own_page:
                    b.shown.append(js)
                return {"result": {"value": own_page}}
            return {}
        b.evaluate = evaluate
        return b

    def ask(self, kind="reset", b=None):
        wipe._asked_at[0] = -1e9  # (no 20 s wait between asks in a test)
        b = b or self.tv()
        wipe.ask(kind, b)
        return wipe._asked.get("code"), b

    def test_code_rules(self):
        code, b = self.ask()
        self.assertIn(code, b.shown[-1])  # shown on the TV
        self.assertIn('location.protocol !== "file:"', b.shown[-1])  # and only on its own page
        with self.assertRaises(ValueError):
            wipe.confirm("signout", code)  # asked for a reset, not this
        code, _ = self.ask()
        for _ in range(2):
            with self.assertRaises(ValueError):
                wipe.confirm("reset", "nope")
        self.assertTrue(wipe.confirm("reset", code))
        with self.assertRaises(ValueError):
            wipe.confirm("reset", code)  # used up
        code, _ = self.ask("signout")
        wipe._asked["until"] = 0
        with self.assertRaises(ValueError):
            wipe.confirm("signout", code)  # ran out

    def test_no_guessing_by_asking_again(self):
        self.ask()
        for _ in range(3):
            with self.assertRaises(ValueError):
                wipe.confirm("reset", "nope")
        with self.assertRaises(ValueError) as e:
            self.ask()  # three wrong: locked for a while, not a fresh three
        self.assertIn("Too many", str(e.exception))
        g = wipe.guard()
        wipe.save_guard({**g, "locked_until": 0})
        self.ask()
        for _ in range(3):
            with self.assertRaises(ValueError):
                wipe.confirm("reset", "nope")
        self.assertGreater(wipe.guard()["locked_until"] - wipe.time.time(), 100)  # and longer each round
        wipe.save_guard({**wipe.guard(), "locked_until": 0})
        wipe._asked_at[0] = wipe.time.monotonic()
        with self.assertRaises(ValueError):
            wipe.ask("reset", self.tv())  # a code already up: not another one straight away

    def test_a_restart_doesnt_forget_the_lock(self):
        self.ask()
        for _ in range(3):
            with self.assertRaises(ValueError):
                wipe.confirm("reset", "nope")
        wipe._asked.clear()  # the service started again: nothing in memory
        with self.assertRaises(ValueError) as e:
            self.ask()
        self.assertIn("Too many", str(e.exception))

    def test_no_guessing_when_the_disk_is_full(self):
        self.ask()
        with mock.patch.object(config, "write_private", mock.Mock(side_effect=OSError(28, "No space left"))):
            with self.assertRaises(ValueError):
                wipe.confirm("reset", "nope")
            self.assertEqual(wipe._asked, {})  # that code is gone
            with self.assertRaises(ValueError):
                self.ask()  # and no new one while nothing can be counted

    def test_a_right_code_clears_the_count(self):
        code, _ = self.ask()
        with self.assertRaises(ValueError):
            wipe.confirm("reset", "nope")
        wipe.confirm("reset", code)
        self.assertEqual(wipe.guard()["wrong"], 0)

    def test_no_guessing_two_at_a_time(self):
        self.ask()
        for _ in range(2):
            with self.assertRaises(ValueError):
                wipe.confirm("reset", "nope")
        self.ask()  # a fresh code, but the wrong ones still count
        with self.assertRaises(ValueError):
            wipe.confirm("reset", "nope")
        with self.assertRaises(ValueError) as e:
            self.ask()
        self.assertIn("Too many", str(e.exception))

    def test_never_shown_on_a_website(self):
        with self.assertRaises(ValueError):
            self.ask(b=self.tv(own_page=False))
        self.assertEqual(wipe._asked, {})

    def test_reset(self):
        wipe.reset()
        for f in ("token", "people", "setup-password", "timezone-set", "reset-pending"):
            self.assertFalse((self.conf / f).exists(), f)
        self.assertTrue((self.conf / "wipe-browser").exists())  # the browser's profile goes as it starts again
        self.assertFalse((self.home / ".config/go-librespot/state.json").exists())
        self.assertFalse(list((self.home / ".config/go-librespot/profiles").iterdir()))
        s = config.load(self.conf / "config.toml")
        self.assertEqual((s.name, s.latitude, s.place, s.updates), ("Tenfoot", None, "", "auto"))
        self.assertEqual((s.display_mode, s.jellyfin_url), ("1280x720@60", "http://192.168.1.20:8096"))  # the admin's stay
        self.assertIn(("nmcli", "connection", "delete", "uuid", "u1"), self.calls)
        self.assertIn(("nmcli", "connection", "delete", "uuid", "u3"), self.calls)
        self.assertNotIn(("nmcli", "connection", "delete", "uuid", "u2"), self.calls)
        self.assertIn(("rename", "Tenfoot"), self.calls)  # Spotify and AirPlay go back to the plain name

    def test_only_on_the_tv_box(self):
        with mock.patch.object(wipe.getpass, "getuser", lambda: "bb"):
            with self.assertRaises(SystemExit):
                wipe.reset()  # a developer's laptop keeps its Wi-Fi
        self.assertTrue((self.conf / "token").exists())

    def test_keep_wifi_and_a_developers_off(self):
        (self.conf / "config.toml").write_text('updates = "off"\n')
        wipe.reset(keep_wifi=True)
        self.assertFalse([c for c in self.calls if c[:3] == ("nmcli", "connection", "delete")])
        self.assertEqual(config.load(self.conf / "config.toml").updates, "off")

    def test_reset_mends_a_broken_config(self):
        (self.conf / "config.toml").write_text('name = "a"\nname = "b"\n')  # not TOML
        wipe.reset(keep_wifi=True)
        self.assertEqual(config.load(self.conf / "config.toml").name, "Tenfoot")

    def test_a_reset_cut_short_finishes(self):
        (self.conf / "reset-pending-keep-wifi").write_text("")
        wipe.finish_pending()
        self.assertFalse([c for c in self.calls if c[:3] == ("nmcli", "connection", "delete")])  # its choice kept
        self.assertFalse((self.conf / "token").exists())
        self.assertFalse((self.conf / "reset-pending-keep-wifi").exists())

    def test_a_guest_who_can_see_the_tv_gets_a_remote_of_their_own(self):
        with mock.patch.object(links, "PEOPLE_FILE", self.conf / "people"), mock.patch.object(links, "TOKEN_FILE", self.conf / "token"), \
                mock.patch.object(links, "link_url", lambda settings, tok: f"https://tv.example/{tok}/"):
            (self.conf / "people").write_text("")
            (self.conf / "token").write_text("Abc123def456ghi789jkl012")
            c = make_controls(browser=self.tv())
            self.assertEqual(c.handle({"a": "own", "by": "guest"}), {"asked": True})
            code = wipe._asked["code"]
            with self.assertRaises(ValueError):
                c.handle({"a": "own", "by": "guest", "code": "nope"})
            link = c.handle({"a": "own", "by": "guest", "code": code})["link"]
            token = link.split("/")[3]
            ppl = links.people(self.conf / "people")
            self.assertEqual(ppl, {"phone-1": token})
            self.assertEqual(links.who(token, links.load_token(self.conf / "token"), ppl), "phone-1")  # not a guest any more
            self.assertEqual(links.new_phone_name(), "phone-2")

    def test_not_for_guests(self):
        with self.assertRaises(ValueError):
            make_controls().handle({"a": "wipe", "k": "reset", "by": "guest"})


class Apps(unittest.TestCase):
    def test_list_follows_settings(self):
        self.assertEqual(APPS[1]["id"], "jellyfin")
        ids = {a["id"] for a in apps.load_apps(config.Settings(spotify=False))}
        self.assertNotIn("spotify", ids)
        self.assertNotIn("jellyfin", ids)

    def test_pages_resolve_next_to_the_home_screen(self):
        self.assertEqual(URLS["spotify"], (config.WEB_HOME / "spotify.html").as_uri())

    def test_to_url(self):
        self.assertEqual(to_url("youtube.com"), "https://youtube.com")
        self.assertEqual(to_url("http://1.1.1.1/"), "http://1.1.1.1/")
        self.assertEqual(to_url("HTTPS://x.y"), "HTTPS://x.y")
        self.assertEqual(to_url("couch setup"), SEARCH + "couch%20setup")

    def test_inside_the_house_is_a_search(self):
        for inside in ("http://127.0.0.1:9222/json", "http://localhost:3678/status", "127.0.0.1:8765", "http://10.44.0.1/",
                       "http://100.100.100.100/", "http://[::1]:8766/bands", "http://169.254.1.1/", "http://192.168.1.1/",
                       "https://x.localhost/", "http://0.0.0.0:9222/"):
            self.assertTrue(to_url(inside).startswith(SEARCH), inside)
        self.assertEqual(to_url(JF + "/web/#/home", JF), JF + "/web/#/home")
        self.assertTrue(to_url(JF + "/web/#/home").startswith(SEARCH))  # not configured: not allowed

    def test_jellyfin_lookalikes_are_still_inside_the_house(self):
        for trick in (JF + "@127.0.0.1:9222/json", "http://192.168.1.20:8097/", "https://192.168.1.20:8096/", "http://192.168.1.20:8096.nip.io/"):
            self.assertNotEqual(to_url(trick, JF), trick, trick)
        self.assertEqual(app_of(JF + "@127.0.0.1/", JF)[0], "web")

    def test_other_schemes_are_a_search(self):
        for bad in ("file:///etc/passwd", "chrome://settings", "javascript://%0aalert(1)", "data:text/html,<b>x</b>",
                    "view-source:https://x.y", "devtools://devtools/x"):
            self.assertTrue(to_url(bad).startswith(SEARCH), bad)

    def test_youtube_links_open_in_the_tv_app(self):
        tv = "https://www.youtube.com/tv#/watch?v=dQw4w9WgXcQ"
        for link in ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s", "https://youtu.be/dQw4w9WgXcQ?si=abc", "youtu.be/dQw4w9WgXcQ",
                     "https://m.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtube.com/shorts/dQw4w9WgXcQ",
                     "https://www.youtube.com/live/dQw4w9WgXcQ?feature=share"):
            self.assertEqual(to_url(link), tv, link)
        for other in ("https://www.youtube.com/", "https://www.youtube.com/@x", "https://www.youtube.com/watch?v=bad",
                      "https://evil.example/watch?v=dQw4w9WgXcQ", "https://notyoutube.com/watch?v=dQw4w9WgXcQ"):
            self.assertEqual(to_url(other), other, other)

    def test_app_of(self):
        self.assertEqual(app_of(apps.page_url("home.html")), ("home", None))
        self.assertEqual(app_of(apps.page_url("sleep.html")), ("asleep", None))
        self.assertEqual(app_of(URLS["spotify"]), ("spotify", None))
        self.assertEqual(app_of("https://www.youtube.com/tv#/watch?v=x"), ("youtube", None))
        self.assertEqual(app_of("https://www.youtube.com/watch?v=x"), ("web", "youtube.com"))
        self.assertEqual(app_of(JF + "/web/", JF), ("jellyfin", None))
        self.assertEqual(app_of("https://netflix.com/watch/81"), ("netflix", None))
        self.assertEqual(app_of("https://auth.hbomax.com/login"), ("hbomax", None))
        self.assertEqual(app_of("https://notnetflix.com/"), ("web", "notnetflix.com"))
        for a in ("disney", "hbomax", "crunchyroll", "paramount", "shahid"):
            self.assertEqual(app_of(URLS[a]), (a, None))


class Sites(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(sites.identity("https://www.youtube.com/tv#/browse", UA), (sites.TV_UA, {"userAgent": sites.TV_UA}))
        self.assertEqual(sites.identity("https://www.netflix.com/", UA), (UA, {"userAgent": ""}))
        ua, params = sites.identity("https://shahid.mbc.net/", UA)
        self.assertIn("Windows NT 10.0", ua)
        self.assertEqual(params["userAgentMetadata"]["platform"], "Windows")

    def test_only_real_youtube_gets_the_tv_identity(self):
        self.assertTrue(sites.wants_tv("https://youtube.com/tv"))
        for u in ("https://www.youtube.com/watch?v=x", "https://open.spotify.com/", "https://evil.example/www.youtube.com/tv"):
            self.assertFalse(sites.wants_tv(u), u)

    def test_rules(self):
        self.assertIs(sites.rules_for(URLS["shahid"]), sites.SHAHID_BLOCK)
        self.assertEqual(sites.rules_for("https://play.hbomax.com/movie/x"), sites.SITE_BLOCK["hbomax.com"])
        self.assertEqual(sites.rules_for(URLS["netflix"]), [])
        self.assertEqual(sites.rules_for("about:blank"), [])

    def test_watching(self):
        for u in ("https://play.hbomax.com/video/watch/31ed7e52", "https://www.disneyplus.com/play/822d988b"):
            self.assertTrue(sites.WATCHING.match(u), u)
        for u in ("https://play.hbomax.com/show/x", "https://www.disneyplus.com/browse/x", "https://evil.example/https://play.hbomax.com/video/watch/x"):
            self.assertFalse(sites.WATCHING.match(u), u)


class Links(unittest.TestCase):
    TOKEN = "s3cret-Tok_en"
    PEOPLE = {"sam": "Sam-tok_123456789"}

    def route(self, path, people=None):
        return links.route(path, lambda t: links.who(t, self.TOKEN, self.PEOPLE if people is None else people))

    def test_routes(self):
        self.assertEqual(self.route("/s3cret-Tok_en/"), ("page", "house"))
        self.assertEqual(self.route("/s3cret-Tok_en/api"), ("api", "house"))
        self.assertEqual(self.route("/s3cret-Tok_en/ws"), ("ws", "house"))
        self.assertEqual(self.route("/s3cret-Tok_en"), ("redirect", "house"))
        self.assertEqual(self.route("/Sam-tok_123456789/api"), ("api", "sam"))

    def test_wrong_paths_get_nothing(self):
        for p in ("/", "/api", "/index.html", "/wrong/", "/wrong/api", "/s3cret-Tok_e/api", "/Sam-tok_12345678/api",
                  "/s3cret-Tok_enX/api", "//s3cret-Tok_en/api", "/s3cret-Tok_en/etc/passwd", "/é/api", "/sw.js"):
            self.assertIsNone(self.route(p)[0], p)

    def test_guest_link_dies_with_the_house_secret(self):
        g = links.guest_token(self.TOKEN)
        self.assertGreaterEqual(len(g), 24)
        self.assertEqual(links.who(g, self.TOKEN, {}), "guest")
        self.assertIsNone(links.who(g, "other", {}))

    def test_revoked_person(self):
        self.assertIsNone(self.route("/Sam-tok_123456789/api", people={})[0])

    def test_token_file_is_private_and_stable(self):
        p = Path(tempfile.mkdtemp()) / "sub" / "token"
        t = links.load_token(p)
        self.assertGreaterEqual(len(t), 16)
        self.assertEqual(links.load_token(p), t)
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_base_url(self):
        self.assertEqual(links.base_url(config.Settings(remote_mode="url", remote_url="https://tv.example/")), "https://tv.example")
        with mock.patch.object(links, "lan_ip", return_value="192.168.1.9"):
            self.assertEqual(links.link_url(config.Settings(), "t"), "http://192.168.1.9:8765/t/")

    def test_tailscale_with_no_name_yet_never_makes_a_hostless_link(self):
        out = mock.Mock(stdout=json.dumps({"Self": {"DNSName": ""}}))
        with mock.patch("subprocess.run", return_value=out), self.assertRaises(RuntimeError):
            links.base_url(config.Settings(remote_mode="tailscale"))

    def test_qr_file_is_private(self):
        p = Path(tempfile.mkdtemp()) / "qr.svg"
        links.write_qr(config.Settings(remote_mode="url", remote_url="https://tv.example"), self.TOKEN, p)
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertIn(b"<svg", p.read_bytes())


class FakeInput:
    def __init__(self):
        self.log = []

    def press(self, k): self.log.append(("press", k))
    def point(self, x, y): self.log.append(("point", round(x), round(y)))
    def move(self, dx, dy): self.log.append(("move", dx, dy))
    def click(self, b="left"): self.log.append(("click", b))
    def scroll(self, n): self.log.append(("scroll", n))


class FakeBrowser:
    def __init__(self, url="https://www.google.com/"):
        self.url, self.calls = url, []

    def current_url(self): return self.url
    def one_tab(self): self.calls.append("one_tab")
    def navigate(self, url): self.calls.append(("navigate", url))
    def call(self, method, params=None): self.calls.append((method, params))
    def evaluate(self, js): return {"result": {"value": False}}


def make_controls(browser=None, inp=None, **kw):
    return controls.Controls(inp or FakeInput(), browser or FakeBrowser(), SETTINGS, APPS, **kw)


class Commands(unittest.TestCase):
    def test_keys(self):
        c = make_controls()
        c.handle({"a": "key", "k": "ok"})
        self.assertEqual(c.inp.log, [("press", ["KEY_ENTER"])])
        c.handle({"a": "key", "k": "backspace", "n": 3})
        c.handle({"a": "key", "k": "backspace", "n": 999})
        self.assertEqual(c.inp.log[1:], [("press", ["KEY_BACKSPACE"])] * 53)  # 3, then capped at 50

    def test_refuses_anything_else(self):
        c = make_controls()
        for bad in ({"a": "key", "k": "KEY_POWER"}, {"a": "nope"}, {"a": "open", "url": " "}, {"a": "app", "k": "file:///etc/passwd"},
                    {"a": "tv", "k": "selfdestruct"}, {"a": "tv", "k": "on"}, {"a": "spotify", "k": "list"}):
            with self.assertRaises(ValueError, msg=bad):
                c.handle(bad)

    def test_back_depends_on_the_page(self):
        c = make_controls(FakeBrowser("https://www.youtube.com/tv#/browse"))
        c.handle({"a": "back"})
        self.assertEqual(c.inp.log, [("press", ["KEY_ESC"])])
        self.assertEqual(controls.back_keys("https://www.google.com/"), ["KEY_LEFTALT", "KEY_LEFT"])

    def test_opening_leaves_one_tab(self):
        c = make_controls()
        c.handle({"a": "app", "k": "netflix"})
        c.handle({"a": "home"})
        self.assertEqual(c.browser.calls, ["one_tab", ("navigate", URLS["netflix"]), "one_tab", ("navigate", apps.page_url("home.html"))])

    def test_phone_gets_names_and_colours_never_urls(self):
        listed = make_controls().handle({"a": "apps"})
        self.assertNotIn("url", listed[0])
        self.assertEqual({a["id"] for a in listed if a["mouse"]}, {"web", "jellyfin"})

    def test_state(self):
        s = make_controls(FakeBrowser("https://www.netflix.com/browse")).handle({"a": "state"})
        self.assertEqual(s, {"app": "netflix", "host": None, "power": None, "music": None})

    def test_volume_level(self):
        self.assertEqual(controls.volume_level("Volume: 0.45 [MUTED]\n"), (45, True))
        self.assertEqual(controls.volume_level("Volume: 1.00\n"), (100, False))


class Cursor(unittest.TestCase):
    def setUp(self):
        self.c = make_controls()
        self.c.toast = lambda *a: None
        self.c.cursor.toast = lambda *a: None
        self.addCleanup(lambda: self.c.cursor.timer and self.c.cursor.timer.cancel())

    def test_glide_speed(self):
        self.assertEqual([cursor.glide_speed(t) for t in (0.1, 0.15, 3)], [0, 300, 2000])
        self.assertAlmostEqual(cursor.glide_speed(0.4), 900)

    def test_arrows_nudge_ok_clicks_back_puts_it_away(self):
        c, log = self.c, self.c.inp.log
        c.handle({"a": "cursor"})
        c.handle({"a": "key", "k": "right"})
        c.handle({"a": "key", "k": "ok"})
        self.assertEqual(log, [("point", 960, 540), ("point", 980, 540), ("click", "left")])
        c.handle({"a": "back"})
        self.assertEqual(log[-1], ("point", 1919, 1079))
        self.assertFalse(c.cursor.on)
        c.handle({"a": "key", "k": "right"})
        self.assertEqual(log[-1], ("press", ["KEY_RIGHT"]))  # off again: the arrows are keys

    def test_held_arrow_glides_smoothly(self):
        c = self.c.cursor
        self.c.handle({"a": "cursor"})
        c.glide("down", True)
        time.sleep(0.5)
        c.glide("down", False)
        ys = [e[2] for e in self.c.inp.log[1:] if e[0] == "point"]
        self.assertTrue(10 < len(ys) < 40 and ys[0] == 560 and 600 < ys[-1] < 1000 and ys == sorted(ys), ys)
        time.sleep(0.1)
        self.assertFalse(c.glider.is_alive())

    def test_past_the_top_scrolls(self):
        self.c.handle({"a": "cursor"})
        self.c.cursor.y = 5
        self.c.cursor.to(0, -20)
        self.assertEqual(self.c.inp.log[-2:], [("scroll", 1), ("point", 960, 0)])

    def test_enter_and_touchpad_get_through(self):
        self.c.handle({"a": "cursor"})
        self.c.handle({"a": "key", "k": "enter"})
        self.assertEqual(self.c.inp.log[-1], ("press", ["KEY_ENTER"]))  # the phone's typing still works
        self.c.handle({"a": "move", "dx": 1, "dy": 0})
        self.assertFalse(self.c.cursor.on)
        self.assertEqual(self.c.inp.log[-1], ("move", 1.0, 0.0))  # took over quietly, no trip to the corner


class RemoteServer(unittest.TestCase):
    TOKEN = "s3cret-Tok_en"

    def setUp(self):
        self.c = make_controls()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.remote_handler(self.c, self.TOKEN))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.host = f"127.0.0.1:{self.srv.server_address[1]}"

    def post(self, path, body):
        req = urllib.request.Request(f"http://{self.host}{path}", data=body, method="POST")
        return urllib.request.urlopen(req, timeout=5)

    def test_page_works_on_plain_http(self):
        """A page on a LAN address isn't a secure context: browsers hide these from it."""
        page = (config.WEB_REMOTE / "index.html").read_text()
        for api in ("crypto.subtle", "navigator.clipboard", "serviceWorker", "navigator.wakeLock"):
            self.assertNotIn(api, page)

    def test_page_headers_protect_the_link(self):
        r = urllib.request.urlopen(f"http://{self.host}/{self.TOKEN}/", timeout=5)
        self.assertEqual(r.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors", r.headers["Content-Security-Policy"])
        self.assertIn(b"Tenfoot", r.read())

    def test_redirect_adds_the_slash(self):
        r = urllib.request.urlopen(f"http://{self.host}/{self.TOKEN}", timeout=5)
        self.assertEqual(r.url, f"http://{self.host}/{self.TOKEN}/")

    def test_wrong_token_404s_everywhere(self):
        for req in (f"http://{self.host}/", f"http://{self.host}/wrong/", f"http://{self.host}/wrong/api"):
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(e.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.post("/wrong/api", b'{"a":"home"}')
        self.assertEqual(e.exception.code, 404)
        self.assertEqual(self.c.browser.calls, [])

    def test_api(self):
        self.assertEqual(self.post(f"/{self.TOKEN}/api", b'{"a":"key","k":"ok"}').read(), b"ok")
        self.assertEqual(self.c.inp.log, [("press", ["KEY_ENTER"])])
        self.assertEqual(json.load(self.post(f"/{self.TOKEN}/api", b'{"a":"state"}'))["app"], "web")

    def test_api_reports_bad_input_and_survives(self):
        for body in (b"junk", b"[1]", b'{"a":"nope"}'):
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.post(f"/{self.TOKEN}/api", body)
            self.assertEqual(e.exception.code, 400, body)
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.post(f"/{self.TOKEN}/api", b"x" * 10001)
        self.assertEqual(e.exception.code, 400)

    def test_pointer_stream_carries_only_pointer_commands(self):
        ws = websocket.create_connection(f"ws://{self.host}/{self.TOKEN}/ws", timeout=5)
        for m in ({"a": "move", "dx": 3, "dy": -2}, {}, {"a": "key", "k": "ok"}, {"a": "home"}, {"a": "scroll", "n": -1}, {"a": "click"}):
            ws.send(json.dumps(m))
        ws.send("x" * 300)  # not JSON: the stream ends, nothing else happens
        time.sleep(0.4)
        self.assertEqual(self.c.inp.log, [("move", 3.0, -2.0), ("scroll", -1), ("click", "left")])
        self.assertEqual(self.c.browser.calls, [])

    def test_pointer_stream_needs_a_token_and_an_upgrade(self):
        with self.assertRaises(websocket.WebSocketBadStatusException):
            websocket.create_connection(f"ws://{self.host}/wrong/ws", timeout=5)
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"http://{self.host}/{self.TOKEN}/ws", timeout=5)
        self.assertEqual(e.exception.code, 404)


class CEC(unittest.TestCase):
    def feed(self, st, lines):
        return [cec.route_event(st, l) for l in lines]

    def test_parsers(self):
        self.assertEqual(cec.phys_addr("\tPhysical Address           : 1.0.0.0\n"), "1.0.0.0")
        self.assertIsNone(cec.phys_addr("\tPhysical Address           : f.f.f.f\n"))
        self.assertIsNone(cec.phys_addr("nothing here"))
        self.assertEqual(cec.parse_power("\tpwr-state: standby (0x01)\n"), "standby")
        self.assertEqual(cec.parse_power("\tpwr-state: on (0x00)\n"), "on")
        self.assertIsNone(cec.parse_power("Tx, Not Acknowledged"))

    def test_remote_keys(self):
        rc = cec.remote_command
        self.assertEqual(rc("KEY_OK", 1), {"a": "key", "k": "ok"})
        self.assertEqual(rc("KEY_EXIT", 1), {"a": "back"})
        self.assertEqual(rc("KEY_ESC", 1), {"a": "back"})
        self.assertEqual(rc("KEY_ROOT_MENU", 1), {"a": "home"})
        self.assertEqual(rc("KEY_UP", 2), {"a": "key", "k": "up"})  # held arrow repeats
        self.assertIsNone(rc("KEY_ROOT_MENU", 2))  # held Home does not
        self.assertIsNone(rc("KEY_OK", 0))  # releases ignored
        self.assertIsNone(rc("KEY_POWER", 1))  # the TV's own buttons ignored
        self.assertEqual(rc("KEY_KPPLUS", 2), {"a": "tv", "k": "volup"})
        self.assertEqual(rc("KEY_F8", 1), {"a": "cursor"})
        self.assertIsNone(rc("KEY_F8", 2))
        self.assertEqual(rc(("KEY_MIN_INTERESTING", "KEY_MUTE"), 1), {"a": "tv", "k": "mute"})  # evdev's real name for 113
        self.assertEqual(rc(["KEY_X", "KEY_HOME"], 1), {"a": "home"})

    def test_the_mute_key_as_evdev_really_names_it(self):
        from evdev import ecodes
        self.assertEqual(cec.remote_command(ecodes.KEY[ecodes.KEY_MUTE], 1), {"a": "tv", "k": "mute"})

    def test_newest_repeats(self):
        k = lambda code, value: type("Ev", (), {"code": code, "value": value})
        held = [k(115, 1), k(115, 2), k(115, 2), k(103, 2), k(115, 2), k(115, 0)]
        self.assertEqual([(e.code, e.value) for e in cec.newest_repeats(held)], [(115, 1), (103, 2), (115, 2), (115, 0)])

    def test_replay_input_switch_while_reregistering(self):
        """A real capture: switch to our input while we re-register."""
        st = {"pa": "2.0.0.0", "claimed": True}
        self.assertFalse(any(self.feed(st, ["Received from TV to all (0 to 15): ROUTING_CHANGE (0x80):", "\torig-phys-addr: 2.0.0.0",
                                            "\tnew-phys-addr: 0.0.0.0", "Received from TV to all (0 to 15): ACTIVE_SOURCE (0x82):",
                                            "\tphys-addr: 0.0.0.0"])))
        self.assertIs(st["want"], False)
        self.assertFalse(any(self.feed(st, ["Wed Sep 30 00:07:35.389800: Event: State Change: PA: f.f.f.f, LA mask: 0x0000",
                                            "Received from TV to all (0 to 15): ROUTING_CHANGE (0x80):", "\torig-phys-addr: 0.0.0.0",
                                            "\tnew-phys-addr: 2.0.0.0", "Received from TV to all (0 to 15): SET_STREAM_PATH (0x86):",
                                            "\tphys-addr: 2.0.0.0", "Wed Sep 30 00:07:35.905072: Event: State Change: PA: 2.0.0.0, LA mask: 0x0000"])))
        self.assertEqual(self.feed(st, ["Wed Sep 30 00:07:36.038735: Event: State Change: PA: 2.0.0.0, LA mask: 0x0100"]), [True])
        # TV picks another input: no more announcing, even if we re-register.
        self.feed(st, ["Received from TV to all (0 to 15): ACTIVE_SOURCE (0x82):", "\tphys-addr: 1.0.0.0"])
        self.assertEqual(self.feed(st, ["Event: State Change: PA: 2.0.0.0, LA mask: 0x0100"]), [False])
        self.assertFalse(cec.route_event(st, "Transmitted by Playback Device 2 to all (8 to 15): ACTIVE_SOURCE (0x82):"))

    def test_replay_follower_format(self):
        st = {"pa": "1.0.0.0", "claimed": True, "want": True}
        self.feed(st, ["    TV to all (0 to 15): ROUTING_CHANGE (0x80):", "\torig-phys-addr: 1.0.0.0", "\tnew-phys-addr: 2.0.0.0",
                       "    TV to all (0 to 15): SET_STREAM_PATH (0x86):", "\tphys-addr: 2.0.0.0"])
        self.assertIs(st["want"], False)
        self.assertEqual(self.feed(st, ["    TV to all (0 to 15): SET_STREAM_PATH (0x86):", "\tphys-addr: 1.0.0.0"]), [False, True])

    def test_hotplug_blip_wants_but_doesnt_grab(self):
        st = {"pa": "1.0.0.0", "claimed": True, "want": False}
        self.assertFalse(any(self.feed(st, ["Event: State Change: PA: f.f.f.f, LA mask: 0x0000", "Event: State Change: PA: 1.0.0.0, LA mask: 0x0000",
                                            "Event: State Change: PA: 1.0.0.0, LA mask: 0x0100"])))
        self.assertIs(st["want"], True)

    def test_long_unplug_comes_back_on_its_own_home(self):
        st = {"pa": "1.0.0.0", "claimed": True, "want": False}
        self.feed(st, ["Event: State Change: PA: f.f.f.f, LA mask: 0x0000"])
        st["hpd"] -= 60
        self.feed(st, ["Event: State Change: PA: 1.0.0.0, LA mask: 0x0000"])
        self.assertIs(st["want"], False)


class Kiosk(unittest.TestCase):
    def run_watchdog(self, answers, outcomes=None, rounds=30):
        """The real watchdog loop, on a fake clock: answers(round) says if the page answered; returns [(t, step)]."""
        clock_, taken = [0.0], []
        outcomes = outcomes or {}

        def sleep(sec):
            clock_[0] += sec
            if clock_[0] > rounds * kiosk.CHECK_EVERY:
                raise StopIteration

        class Page:
            def evaluate(self, js):
                if not answers(int(clock_[0] // kiosk.CHECK_EVERY)):
                    raise TimeoutError

        def step(name):
            def act(*a):
                taken.append((int(clock_[0]), name))
                o = outcomes.get(name)
                if isinstance(o, Exception):
                    raise o
                return o(len([n for _, n in taken if n == name])) if callable(o) else o
            return act
        with mock.patch.object(kiosk.time, "sleep", sleep), mock.patch.object(kiosk.time, "monotonic", lambda: clock_[0]), \
                mock.patch.object(kiosk, "pin_display", lambda m: None), mock.patch.object(kiosk, "restart_chromium", step("chromium")), \
                mock.patch.object(kiosk, "restart_cage", step("cage")), mock.patch.object(kiosk, "request_reboot", step("reboot")):
            with self.assertRaises(StopIteration):
                kiosk.watchdog(Page(), SETTINGS)
        return taken

    def test_escalation_in_order(self):
        self.assertEqual(self.run_watchdog(lambda r: r < 2, {"reboot": True}, rounds=19),
                         [(120, "chromium"), (180, "cage"), (360, "reboot"), (540, "reboot")])  # dead from 60 s; then
        # each step after its wait, the reboot asked for again in case it didn't happen

    def test_page_back_starts_over(self):
        self.assertEqual(self.run_watchdog(lambda r: r < 2 or 5 <= r < 8, rounds=14),
                         [(120, "chromium"), (300, "chromium"), (360, "cage")])  # answered again after the restart, so
        # the second death (240 s) starts over from Chromium

    def test_declined_reboot_is_asked_again(self):
        self.assertEqual([t for t, n in self.run_watchdog(lambda r: r < 2, {"reboot": lambda n: n >= 3}) if n == "reboot"],
                         [360, 540, 720, 900])  # declined twice (too soon after boot, say), then it happens; it keeps asking

    def test_a_failing_step_doesnt_reset_it(self):
        taken = self.run_watchdog(lambda r: r < 2, {"chromium": ProcessLookupError(), "cage": subprocess.TimeoutExpired("pkill", 10),
                                                    "reboot": OSError("read-only")})
        self.assertEqual([n for _, n in taken][:4], ["chromium", "cage", "reboot", "reboot"])

    def test_reboot_only_with_a_tv_on_the_tv_box(self):
        with mock.patch.object(kiosk.subprocess, "run") as run, mock.patch.object(kiosk, "hdmi_connected", lambda: True):
            with mock.patch.object(kiosk.getpass, "getuser", lambda: "bb"):
                self.assertFalse(kiosk.request_reboot())  # a developer's machine: never
            with mock.patch.object(kiosk.getpass, "getuser", lambda: "tenfoot"):
                with mock.patch.object(kiosk, "hdmi_connected", lambda: False):
                    self.assertFalse(kiosk.request_reboot())  # no TV: nothing a reboot would bring back
                run.assert_not_called()
                run.return_value.returncode = 1
                self.assertFalse(kiosk.request_reboot())  # root declined
                run.return_value.returncode = 0
                self.assertTrue(kiosk.request_reboot())
                self.assertEqual(run.call_args[0][0], ["systemctl", "start", "tenfoot-reboot-stuck.service"])

    def test_systemd_hears_alive(self):
        from tenfoot.__main__ import notify
        d = tempfile.mkdtemp()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.bind(d + "/notify")
        self.addCleanup(sock.close)
        with mock.patch.dict(os.environ, NOTIFY_SOCKET=d + "/notify"):
            self.assertTrue(notify("WATCHDOG=1"))
        self.assertEqual(sock.recv(100), b"WATCHDOG=1")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(notify("WATCHDOG=1"))  # run by hand, not by systemd

    def test_display_modes(self):
        from tenfoot import display
        out = lambda *modes: "HDMI-A-1 \"TV\"\n  Modes:\n" + "".join(f"    {m}\n" for m in modes) + "  Position: 0,0\n"
        k4 = out("3840x2160 px, 30.000000 Hz (preferred, current)", "1920x1080 px, 60.000000 Hz", "1920x1080 px, 59.939999 Hz",
                 "1920x1080 px, 50.000000 Hz", "1280x720 px, 60.000000 Hz")
        self.assertEqual(display.choose(k4), "1920x1080@60.000")  # not the 4K TV's 30 Hz favourite
        self.assertEqual(display.current(k4), "3840x2160@30.000")
        tv720 = out("1366x768 px, 60.000000 Hz (preferred)", "1280x720 px, 60.000000 Hz", "1024x768 px, 60.000000 Hz")
        self.assertEqual(display.choose(tv720), "1366x768@60.000")  # no 1080p at all: its own
        panel = out("1920x1080 px, 59.939999 Hz (preferred)", "1280x720 px, 59.939999 Hz")
        self.assertEqual(display.choose(panel), "1920x1080@59.940")  # spelled so wlr-randr matches it
        eu = out("1920x1080 px, 50.000000 Hz (preferred)", "1280x720 px, 50.000000 Hz")
        self.assertEqual(display.choose(eu), "1920x1080@50.000")
        slow = out("3840x2160 px, 30.000000 Hz (preferred)", "1920x1080 px, 30.000000 Hz", "1280x720 px, 60.000000 Hz")
        self.assertEqual(display.choose(slow), "1920x1080@30.000")  # 1080p still beats 720p
        self.assertEqual(display.choose(k4, "1280x720@60"), "1280x720@60.000")  # asked for, and listed
        self.assertEqual(display.choose(panel, "1920x1080@60"), "1920x1080@59.940")  # 59.94 counts as 60
        self.assertEqual(display.choose(eu, "1920x1080@60"), "1920x1080@50.000")  # not listed: the best there is
        self.assertIsNone(display.choose(""))
        two = k4 + "HDMI-A-2 \"Other\"\n  Modes:\n    1280x720 px, 60.000000 Hz (preferred)\n"
        self.assertEqual(display.choose(two), "1920x1080@60.000")  # the first output only
        self.assertEqual(config.Settings().screen, (1920, 1080))  # "auto": the pointer's space
        both = out("1920x1080 px, 60.000000 Hz", "1920x1080 px, 59.939999 Hz")
        self.assertEqual(display.choose(both, "1920x1080@59.94"), "1920x1080@59.940")  # the closest, not the first
        self.assertEqual(display.choose(k4, "1280x720"), "1280x720@60.000")  # a size alone: its best refresh

    def test_pin_display_only_switches_when_its_wrong(self):
        sample = lambda current: ("HDMI-A-1 \"TV\"\n  Modes:\n"
                                  f"    3840x2160 px, 30.000000 Hz (preferred{', current' if current == '4k' else ''})\n"
                                  f"    1920x1080 px, 60.000000 Hz{' (current)' if current == 'hd' else ''}\n")
        for current, switches in (("hd", []), ("4k", [["wlr-randr", "--output", "HDMI-A-1", "--mode", "1920x1080@60.000"]])):
            calls = []

            def run(args, **kw):
                calls.append(args)
                return mock.Mock(stdout=sample(current), returncode=0)
            with mock.patch.object(kiosk.subprocess, "run", run):
                kiosk.pin_display("auto")
            self.assertEqual([c for c in calls if "--mode" in c], switches, current)

    def test_bad_display_mode_stops_the_service(self):
        for bad in ("1920x1080@60Hz", "1920x1080@", "big"):
            d = Path(tempfile.mkdtemp())
            (d / "config.toml").write_text(f'display_mode = "{bad}"\n')
            with self.assertRaises(SystemExit):
                config.load(d / "config.toml")


class FakePlayer(BaseHTTPRequestHandler):
    """go-librespot: logged out, /status hangs while /auth/code holds a pair code; logged in, 204."""
    paired = False

    def do_GET(self):
        if self.path == "/auth/code" and not FakePlayer.paired:
            body = b'{"code":"ABC123"}'
        elif self.path == "/status" and FakePlayer.paired:
            body = b'{"username":"u","track":{"name":"x","artist_names":["a","b"],"position":1,"duration":2}}'
        elif self.path == "/status":
            return time.sleep(5)
        else:
            self.send_response(204)
            return self.end_headers()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class SpotifyAccounts(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.s = spotify.Spotify(FakeBrowser(), config_dir=d / "cfg", run_dir=d / "run")
        self.s.profiles_dir.mkdir(parents=True)

    def test_sealed_accounts(self):
        k1, k2 = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        blob = spotify.seal(k1, {"username": "u", "data": "secret"})
        self.assertNotIn("secret", blob)
        self.assertEqual(spotify.unseal(k1, blob), {"username": "u", "data": "secret"})
        with self.assertRaises(ValueError):
            spotify.unseal(k2, blob)
        self.assertNotEqual(spotify.keyid(k1), spotify.keyid(k2))
        self.assertEqual(len(spotify.keyid(k1)), 16)

    def test_valid_id(self):
        self.assertTrue(spotify.valid_id("f5mi68yf7vorm4b23rsroc2r0"))
        for bad in ("../state", "a/b", "", "x" * 65, None, 5):
            self.assertFalse(spotify.valid_id(bad), bad)

    def test_profile_name(self):
        self.assertEqual(spotify.profile_name("<title>A &amp; B on Spotify</title>"), "A & B")
        self.assertIsNone(spotify.profile_name("<title>Spotify</title>"))

    def test_second_phone_cant_take_over_an_account_being_added(self):
        self.s.pending.update(key="k", at=time.time(), by="sam")
        with self.assertRaises(ValueError):
            self.s.command({"k": "add", "by": "guest"})

    def test_path_traversal(self):
        with self.assertRaises(ValueError):
            self.s.command({"k": "use", "id": "../../.ssh/id_rsa"})

    def test_only_the_owners_phone_unlocks(self):
        key = Fernet.generate_key().decode()
        self.s.profile_path("u").write_text(json.dumps({"name": "U", "keyid": spotify.keyid(key), "blob": spotify.seal(key, {"username": "u"})}))
        with self.assertRaises(ValueError):
            self.s.command({"k": "use", "id": "u", "key": Fernet.generate_key().decode()})
        self.assertEqual(self.s.saved_profiles(), [{"id": "u", "name": "U", "keyid": spotify.keyid(key)}])

    def test_tv_page_gets_names_not_keys(self):
        key = Fernet.generate_key().decode()
        self.s.profile_path("u").write_text(json.dumps({"name": "U", "keyid": spotify.keyid(key), "blob": "BLOB"}))
        self.s.publish_profiles()
        text = (self.s.run_dir / "spotify-profiles.js").read_text()
        self.assertIn('"name": "U"', text)
        self.assertNotIn("BLOB", text)
        self.assertNotIn("keyid", text)

    def test_status_never_hangs_on_a_pair_code(self):
        fake = ThreadingHTTPServer(("127.0.0.1", 0), FakePlayer)
        threading.Thread(target=fake.serve_forever, daemon=True).start()
        self.addCleanup(fake.server_close)
        self.addCleanup(fake.shutdown)
        self.s.player = f"http://127.0.0.1:{fake.server_port}"
        FakePlayer.paired = False
        t0 = time.time()
        self.assertEqual(self.s.status(), {})
        self.assertLess(time.time() - t0, 1)
        FakePlayer.paired = True
        self.assertEqual(self.s.music()["artist"], "a, b")

    def test_pause_with_the_player_down_is_harmless(self):
        self.s.player = "http://127.0.0.1:9"
        self.s.pause()
        self.assertIsNone(self.s.music())


class WifiSetup(unittest.TestCase):
    def test_parse_networks(self):
        out = "Home\\:Net:70:WPA2\nHome\\:Net:40:WPA2\nCafe:90:\nCampus:95:WPA2 802.1X\n:50:WPA2\nTenfoot-Setup:99:WPA2\n"
        self.assertEqual(setup.parse_networks(out), [{"ssid": "Cafe", "signal": 90, "open": True}, {"ssid": "Home:Net", "signal": 70, "open": False}])

    def test_has_network(self):
        self.assertTrue(setup.has_network("wifi:connected:Home\nloopback:connected (externally):lo\n"))
        self.assertTrue(setup.has_network("ethernet:connected:Wired\nwifi:disconnected:\n"))
        self.assertFalse(setup.has_network("wifi:connected:tenfoot-setup\nloopback:connected (externally):lo\n"))
        self.assertFalse(setup.has_network("wifi:connecting (configuring):Home\ntun:connected (externally):tailscale0\n"))

    def test_wifi_qr_escapes(self):
        self.assertEqual(setup.wifi_qr_text('a;b', 'p:w"'), 'WIFI:T:WPA;S:a\\;b;P:p\\:w\\";;')

    def box(self):
        d = Path(tempfile.mkdtemp())
        s = setup.Setup(FakeBrowser(), run_dir=d, password_file=d / "pw")
        s.calls = []
        s.up = False

        def nmcli(*args, timeout=30):
            s.calls.append(args)
            joining = "connect" in args or args[-2:-1] == ("up",)
            ok = not (s.fail_join and joining)
            if joining and ok:
                s.up = True
            out = "wifi:connected:Home\n" if s.up and "TYPE,STATE,CONNECTION" in args else "wifi:disconnected:\n" if "TYPE,STATE,CONNECTION" in args else ""
            return mock.Mock(returncode=0 if ok else 4, stdout=out)
        s.nmcli, s.fail_join = nmcli, False
        return s

    def test_watch_waits_only_when_a_network_is_known(self):
        for saved, secs_until_start in ((["Home"], setup.GRACE), ([], setup.FIRST_BOOT_GRACE)):
            s = self.box()
            s.has_wifi, s.saved_wifi = (lambda: True), (lambda saved=saved: saved)
            clock = [0.0]
            started = []

            def tick(seconds):
                clock[0] += seconds
                if len(started) or clock[0] > 300:
                    raise StopIteration

            s.start = lambda: started.append(clock[0])
            with mock.patch("time.sleep", tick), mock.patch("time.monotonic", lambda: clock[0]), self.assertRaises(StopIteration):
                s.watch()
            self.assertEqual(len(started), 1)
            self.assertLessEqual(started[0] - secs_until_start, 10, saved)
            self.assertGreater(started[0], secs_until_start, saved)

    def test_new_box_says_checking_until_it_finds_a_network(self):
        s = self.box()
        s.has_wifi, s.saved_wifi = (lambda: True), (lambda: [])
        seen = []

        def tick(seconds):
            seen.append(s.state)
            s.up = True  # Ethernet came up during the first wait
            if len(seen) == 2:
                raise StopIteration
        with mock.patch("time.sleep", tick), self.assertRaises(StopIteration):
            s.watch()
        self.assertEqual(seen, ["checking", "off"])

    def test_refuses_bad_forms(self):
        s = self.box()
        with self.assertRaises(ValueError):
            s.submit("Home", "pw12345678")  # not in setup
        s.state = "hotspot"
        for ssid, pw in ((None, ""), ("", ""), ("x" * 33, ""), ("Home", "short"), ("Home", "x" * 64), ("Home", 5)):
            with self.assertRaises(ValueError, msg=(ssid, pw)):
                s.submit(ssid, pw)

    def test_good_password_goes_home(self):
        s = self.box()
        s.state = "hotspot"
        with mock.patch("time.sleep"):
            s.join("Home", "goodpassword")
        self.assertEqual(s.state, "off")
        self.assertIn(("navigate", apps.page_url("home.html")), s.browser.calls)
        self.assertTrue(any("connect" in c and "goodpassword" in c for c in s.calls))
        self.assertIn(("con", "delete", setup.HOTSPOT), s.calls)

    def test_open_network_is_joined_plainly(self):
        """Not "dev wifi connect": it picks an OWE twin, which the Pi's driver refuses."""
        s = self.box()
        s.state = "hotspot"
        with mock.patch("time.sleep"):
            s.join("Cafe", "")
        self.assertEqual(s.state, "off")
        self.assertIn(("con", "add", "type", "wifi", "ifname", "wlan0", "con-name", "Cafe", "ssid", "Cafe"), s.calls)
        self.assertFalse(any("connect" in c for c in s.calls))

    def test_open_network_failure_doesnt_blame_a_password(self):
        s = self.box()
        s.state, s.fail_join = "hotspot", True
        with mock.patch("time.sleep"), mock.patch.object(setup, "ThreadingHTTPServer"), mock.patch.object(s, "scan", return_value=[]):
            s.join("Cafe", "")
        self.assertNotIn("password", s.error)

    def test_bad_password_returns_to_setup_and_forgets_it(self):
        s = self.box()
        s.state, s.fail_join = "hotspot", True
        with mock.patch("time.sleep"), mock.patch.object(setup, "ThreadingHTTPServer"), mock.patch.object(s, "scan", return_value=[]):
            s.join("Home", "wrongpassword")
        self.assertEqual(s.state, "hotspot")
        self.assertIn("Couldn't join Home", s.error)
        self.assertIn(("con", "delete", "Home"), s.calls)
        self.assertNotIn("wrongpassword", json.dumps(s.status()))

    def test_setup_password_is_private_and_stable(self):
        p = Path(tempfile.mkdtemp()) / "sub" / "pw"
        first = setup.load_password(p)
        self.assertEqual(setup.load_password(p), first)
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_page_never_shows_the_password_after_setup(self):
        s = self.box()
        s.password = "abcd1234"
        self.assertEqual(s.status()["password"], "")

    def test_phone_page_and_form(self):
        s = self.box()
        s.state = "hotspot"
        s.networks = [{"ssid": "<b>Home", "signal": 70, "open": False}]
        srv = ThreadingHTTPServer(("127.0.0.1", 0), setup.handler(s))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        for path in ("/", "/hotspot-detect.html", "/generate_204"):
            self.assertIn(b"Pick your Wi-Fi", urllib.request.urlopen(base + path, timeout=5).read())  # any address: captive portal
        self.assertEqual(json.load(urllib.request.urlopen(base + "/networks", timeout=5))[0]["ssid"], "<b>Home")
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(urllib.request.Request(base + "/join", data=b'{"ssid":"Home","password":"x"}', method="POST"), timeout=5)
        self.assertEqual(e.exception.code, 400)
        page = (config.WEB_HOME / "setup-phone.html").read_text()
        self.assertNotIn("innerHTML", page)

    def test_local_api_reports_setup(self):
        self.assertEqual(apps.app_of(apps.page_url("setup.html")), ("setup", None))
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Local)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        url = f"http://127.0.0.1:{srv.server_address[1]}/setup"
        self.assertEqual(json.load(urllib.request.urlopen(url, timeout=5))["state"], "off")
        s = self.box()
        s.state, s.password = "hotspot", "abcd1234"
        with mock.patch.object(server.Local, "wifi_setup", s):
            self.assertEqual(json.load(urllib.request.urlopen(url, timeout=5))["password"], "abcd1234")


class Lyrics(unittest.TestCase):
    def test_parse_lrc(self):
        self.assertEqual(lyrics.parse_lrc("[00:12.50] Hello ♪\n[01:02.00]\nnot a line\n"),
                         [{"t": 12.5, "text": "Hello"}, {"t": 62.0, "text": ""}])
        self.assertEqual(lyrics.parse_lrc(None), [])

    def test_lookup_404_is_no_lyrics(self):
        lyrics.lookup.cache_clear()
        err = urllib.error.HTTPError("u", 404, "no", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            self.assertEqual(lyrics.lookup("t", "a", "b", 1), [])


class Visualizer(unittest.TestCase):
    def test_bands(self):
        e = visualizer.band_edges()
        self.assertEqual(len(e), visualizer.BANDS + 1)
        self.assertTrue(all(b > a for a, b in zip(e[:-1], e[1:])))
        self.assertLessEqual(e[-1], visualizer.WINDOW // 2 + 1)
        mag = np.random.rand(visualizer.WINDOW // 2 + 1)
        self.assertTrue(np.allclose(visualizer.band_levels(mag, e), [mag[a:b].mean() for a, b in zip(e[:-1], e[1:])]))


class Watcher(unittest.TestCase):
    """The browser's events in, DevTools commands out, with no browser."""

    def setUp(self):
        self.sent, self.opened = [], []
        self.w = watcher.Watcher(lambda m, p=None, s=None: self.sent.append((m, p, s)), UA, "SCRIPT", JF, lambda: self.opened.append(1))

    def attach(self, sid, url, kind="page", waiting=True, opener=None, target=None):
        info = {"type": kind, "url": url, "targetId": target or sid + "-t"}
        if opener:
            info["openerId"] = opener
        self.w.handle({"method": "Target.attachedToTarget", "params": {"sessionId": sid, "targetInfo": info, "waitingForDebugger": waiting}})

    def methods(self, sid=None):
        return [m for m, _, s in self.sent if sid is None or s == sid]

    def pause(self, sid, url, frame=None):
        self.sent.clear()
        self.w.handle({"method": "Fetch.requestPaused", "sessionId": sid, "params": {
            "requestId": "r1", "frameId": frame or sid + "-t", "request": {"url": url, "headers": {"User-Agent": UA, "sec-ch-ua": "x", "Accept": "*"}}}})

    def test_new_page_gets_the_layer_and_runs(self):
        self.attach("p", "about:blank")
        self.assertEqual(self.methods("p")[-1], "Runtime.runIfWaitingForDebugger")
        self.assertIn(("Page.addScriptToEvaluateOnNewDocument", {"source": "SCRIPT"}, "p"), self.sent)
        self.assertIn(("Network.setBypassServiceWorker", {"bypass": True}, "p"), self.sent)

    def test_youtube_load_gets_the_tv_identity(self):
        self.attach("p", "about:blank")
        self.pause("p", "https://www.youtube.com/tv")
        self.assertIn(("Emulation.setUserAgentOverride", {"userAgent": sites.TV_UA}, "p"), self.sent)
        headers = next(p for m, p, _ in self.sent if m == "Fetch.continueRequest")["headers"]
        self.assertIn({"name": "User-Agent", "value": sites.TV_UA}, headers)
        self.assertFalse([h for h in headers if h["name"].lower().startswith("sec-ch-ua")])
        self.assertIn({"name": "Accept", "value": "*"}, headers)
        time.sleep(0.05)
        self.assertEqual(self.opened, [1])  # Spotify paused

    def test_ordinary_site_gets_stock_chrome_and_its_blocking(self):
        self.attach("p", "about:blank")
        self.pause("p", "https://www.disneyplus.com/")
        self.assertIn(("Emulation.setUserAgentOverride", {"userAgent": ""}, "p"), self.sent)
        self.assertIn(("Network.setBlockedURLs", {"urlPatterns": sites.SITE_BLOCK["disneyplus.com"]}, "p"), self.sent)

    def ended(self, sid, url, reason=None, frame=None):
        self.sent.clear()
        params = {"requestId": "r2", "frameId": frame or sid + "-t", "request": {"url": url, "headers": {}}}
        params.update({"responseErrorReason": reason} if reason else {"responseStatusCode": 200})
        self.w.handle({"method": "Fetch.requestPaused", "sessionId": sid, "params": params})

    def test_a_page_that_cant_load_gets_the_tvs_own(self):
        self.attach("p", "about:blank")
        self.ended("p", "https://nope.invalid/x", "NameNotResolved")
        (m, p, s), = self.sent
        self.assertEqual((m, p["responseCode"], s), ("Fetch.fulfillRequest", 200, "p"))
        page = base64.b64decode(p["body"]).decode()
        self.assertIn("Can't find nope.invalid", page)
        self.assertNotIn("__TITLE__", page)

    def test_other_ends_pass(self):
        self.attach("p", "about:blank")
        for reason, frame in ((None, None), ("Aborted", None), ("Failed", None), ("BlockedByClient", None), ("TimedOut", "an-iframe")):
            # (None: a normal end, a redirect included)
            self.ended("p", "https://example.com/", reason, frame)
            self.assertEqual(self.sent, [("Fetch.continueRequest", {"requestId": "r2"}, "p")], reason)
        self.assertEqual(self.opened, [])  # the end of a load isn't another app opening

    def test_offline_page_escapes_the_address(self):
        page = base64.b64decode(watcher.offline_page("<b>x</b>", "TimedOut")).decode()  # no hostname: the whole address
        self.assertIn("&lt;b&gt;x&lt;/b&gt; isn't answering", page)
        self.assertNotIn("<b>x", page)

    def test_loads_are_watched_at_both_ends(self):
        self.attach("p", "about:blank")
        patterns = next(p for m, p, _ in self.sent if m == "Fetch.enable")["patterns"]
        self.assertIn({"resourceType": "Document", "requestStage": "Response"}, patterns)

    def test_a_failed_form_keeps_the_browsers_page(self):
        self.attach("p", "about:blank")
        self.sent.clear()
        self.w.handle({"method": "Fetch.requestPaused", "sessionId": "p", "params": {
            "requestId": "r3", "frameId": "p-t", "responseErrorReason": "TimedOut",
            "request": {"url": "https://example.com/login", "method": "POST", "headers": {}}}})
        self.assertEqual(self.methods(), ["Fetch.continueRequest"])

    def test_offline_pages_way_home(self):
        self.attach("p", "about:blank")
        self.pause("p", watcher.HOME_URL)
        self.assertEqual(self.methods(), ["Fetch.failRequest", "Page.navigate"])
        self.assertEqual(self.sent[1][1], {"url": apps.page_url("home.html")})

    def test_frames_pass_untouched(self):
        self.attach("p", "about:blank")
        self.pause("p", "https://ads.example/", frame="some-iframe")
        self.assertEqual(self.sent, [("Fetch.continueRequest", {"requestId": "r1"}, "p")])

    def test_ad_popup_closed_after_it_runs(self):
        self.attach("p", "https://site.example/")
        self.sent.clear()
        self.attach("ad", "https://ad.example/", opener="p-t", target="ad-t")
        self.assertEqual(self.sent, [("Runtime.runIfWaitingForDebugger", None, "ad"), ("Target.closeTarget", {"targetId": "ad-t"}, None)])

    def test_apps_keep_their_popups(self):
        self.attach("p", "https://www.netflix.com/browse")
        self.sent.clear()
        self.attach("win", "https://accounts.google.com/", opener="p-t")
        self.assertNotIn("Target.closeTarget", self.methods())

    def test_network_quiet_during_a_show(self):
        url = "https://play.hbomax.com/video/watch/x"
        self.attach("p", "about:blank")
        self.w.handle({"method": "Page.navigatedWithinDocument", "sessionId": "p", "params": {"frameId": "p-t", "url": url}})
        self.assertIn(("Network.disable", None, "p"), self.sent)
        self.assertEqual(self.w.urls["p"], url)
        self.sent.clear()
        self.w.handle({"method": "Page.navigatedWithinDocument", "sessionId": "p", "params": {"frameId": "p-t", "url": "https://play.hbomax.com/show/x"}})
        self.assertEqual(self.methods("p")[0], "Network.enable")

    def test_network_on_before_navigating_away(self):
        self.attach("p", "https://play.hbomax.com/video/watch/x", waiting=False)
        self.assertIn("p", self.w.quiet)
        self.assertTrue(self.w.network_on())
        self.assertFalse(self.w.quiet)
        self.assertFalse(self.w.network_on())

    def test_reconnecting_reapplies_an_open_pages_identity(self):
        self.attach("p", "https://shahid.mbc.net/ar/", waiting=False)
        self.assertIn("Emulation.setUserAgentOverride", self.methods("p"))
        self.assertIn(("Network.setBlockedURLs", {"urlPatterns": sites.SHAHID_BLOCK}, "p"), self.sent)

    def test_detach_forgets(self):
        self.attach("p", "https://x.example/")
        self.w.handle({"method": "Target.detachedFromTarget", "params": {"sessionId": "p"}})
        self.assertFalse(self.w.pages or self.w.urls)

    def test_injected_script(self):
        js = watcher.injected_script(JF)
        self.assertLess(js.index('"tvKeyboard"'), js.index('"tvHighlight"'))  # the keyboard gets keys first
        self.assertIn('"192.168.1.20": {', js)
        self.assertNotIn("__JELLYFIN_HOST__", js)
        for domain in apps.SITE_APPS:
            if domain != "shahid.mbc.net":
                self.assertIn(f'"{domain}": {{', js)


if __name__ == "__main__":
    unittest.main()

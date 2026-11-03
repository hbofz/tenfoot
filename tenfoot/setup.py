"""First-time Wi-Fi. With no network, this box makes its own: the TV shows a QR code, a phone joins, and a page
opens where they pick their Wi-Fi. Every address on that network answers with the page, which is what makes phones
open it by themselves. The network's password on the TV is the guard: you have to be in the room."""
import json
import os
import re
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import qrcode
import qrcode.image.svg

from .apps import page_url
from .config import CONFIG_DIR, RUN, WEB_HOME, write_private

HOTSPOT = "tenfoot-setup"
SSID = "Tenfoot-Setup"
ADDRESS = "10.42.0.1"
PORT = 80  # phones check for a captive portal here (install.sh lets this user bind it)
GRACE = 90  # seconds without a known network before taking over the Wi-Fi: a blip mustn't
FIRST_BOOT_GRACE = 20  # with no saved Wi-Fi there's nothing to wait for, beyond Ethernet getting an address
RETRY_SAVED = 600  # with a saved network, stop and try it this often, or an outage would leave the box stuck here
JOIN_WAIT = 45


def split_terse(line):
    """nmcli -t fields: split on ':', which values escape as '\\:'."""
    return [f.replace("\\:", ":").replace("\\\\", "\\") for f in re.split(r"(?<!\\):", line)]


def parse_networks(out):
    """`nmcli -t -f SSID,SIGNAL,SECURITY dev wifi list` -> [{ssid, signal, open}], strongest first, one per name.
    Not enterprise networks (802.1X): they need more than a password, and this page doesn't ask for it."""
    best = {}
    for line in out.splitlines():
        parts = split_terse(line)
        if len(parts) < 3 or not parts[0] or parts[0] == SSID or "802.1X" in parts[2]:
            continue
        signal = int(parts[1]) if parts[1].isdigit() else 0
        if parts[0] not in best or signal > best[parts[0]]["signal"]:
            best[parts[0]] = {"ssid": parts[0], "signal": signal, "open": not parts[2].strip()}
    return sorted(best.values(), key=lambda n: -n["signal"])


def has_network(out):
    """`nmcli -t -f TYPE,STATE,CONNECTION dev`: is Wi-Fi or Ethernet connected, other than our own hotspot?"""
    for line in out.splitlines():
        parts = split_terse(line)
        if len(parts) >= 3 and parts[0] in ("wifi", "ethernet") and parts[1] == "connected" and parts[2] != HOTSPOT:
            return True
    return False


def load_password(path):
    """The setup network's password: made once and kept, so a phone that joined before can rejoin after a failed try."""
    try:
        return path.read_text().strip()
    except OSError:
        password = secrets.token_hex(4)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_private(path, password)
        return password


def wifi_qr_text(ssid, password):
    """What a phone's camera reads as "join this Wi-Fi"."""
    escape = lambda s: re.sub(r'([\;,":])', r"\\\1", s)
    return f"WIFI:T:WPA;S:{escape(ssid)};P:{escape(password)};;"


class Setup:
    def __init__(self, browser, run_dir=RUN, password_file=CONFIG_DIR / "setup-password"):
        self.browser, self.run_dir, self.password_file = browser, run_dir, password_file
        self.started = 0
        self.state = "off"  # off | checking (a new box, looking for a network) | hotspot | joining
        self.error = ""
        self.ssid = SSID
        self.password = ""
        self.networks = []
        self.server = None
        self.lock = threading.Lock()

    def nmcli(self, *args, timeout=30):
        return subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)

    def online(self):
        return has_network(self.nmcli("-t", "-f", "TYPE,STATE,CONNECTION", "dev").stdout)

    def has_wifi(self):
        return "wifi" in self.nmcli("-t", "-f", "TYPE", "dev").stdout.split()

    def saved_wifi(self):
        return [n for t, n in (split_terse(l)[:2] for l in self.nmcli("-t", "-f", "TYPE,NAME", "con", "show").stdout.splitlines())
                if t == "802-11-wireless" and n != HOTSPOT]

    def scan(self):
        return parse_networks(self.nmcli("-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "yes").stdout)

    def start(self, error=""):
        """Take over the Wi-Fi: scan first, since it can't look around well once it's the access point."""
        with self.lock:
            self.networks = self.scan() or self.networks
            self.password = load_password(self.password_file)
            self.nmcli("dev", "wifi", "hotspot", "ifname", "wlan0", "con-name", HOTSPOT, "ssid", SSID, "band", "bg", "password", self.password)
            self.run_dir.mkdir(parents=True, exist_ok=True)
            qrcode.make(wifi_qr_text(SSID, self.password), image_factory=qrcode.image.svg.SvgPathFillImage, border=2).save(str(self.run_dir / "setup-wifi.svg"))
            self.state, self.error, self.started = "hotspot", error, time.monotonic()
            if not self.server:
                self.server = ThreadingHTTPServer(("0.0.0.0", PORT), handler(self))
                threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.show(page_url("setup.html"))
        print("setup: no network, hotspot on", flush=True)

    def stop(self):
        """Back to normal: drop the hotspot so saved networks can connect."""
        self.nmcli("con", "down", HOTSPOT)
        self.nmcli("con", "delete", HOTSPOT)
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        self.state = "off"

    def show(self, url):
        try:
            self.browser.navigate(url)
        except Exception:
            pass  # the browser is still starting; the page's own poll or the next round puts it right

    def join(self, ssid, password):
        """Try the network they picked. It ends the hotspot, so the phone drops off; the TV says how it went."""
        self.state = "joining"
        self.show(page_url("setup.html"))
        time.sleep(1.5)  # let the phone's answer get out first
        self.nmcli("con", "down", HOTSPOT)
        if password:
            # ponytail: the password is briefly on nmcli's command line; only someone already on this box could see it
            result = self.nmcli("-w", str(JOIN_WAIT), "dev", "wifi", "connect", ssid, "password", password, "ifname", "wlan0", timeout=JOIN_WAIT + 15)
        else:
            # An open network, plainly: "connect" would pick its encrypted twin if it has one (OWE transition), which
            # the Pi 4's Wi-Fi driver refuses ("invalid akm suite").
            self.nmcli("con", "delete", ssid)
            self.nmcli("con", "add", "type", "wifi", "ifname", "wlan0", "con-name", ssid, "ssid", ssid)
            result = self.nmcli("-w", str(JOIN_WAIT), "con", "up", ssid, timeout=JOIN_WAIT + 15)
        if result.returncode == 0 and self.online():
            self.nmcli("con", "delete", HOTSPOT)
            if self.server:
                self.server.shutdown()
                self.server.server_close()
                self.server = None
            self.state, self.error = "off", ""
            self.show(page_url("home.html"))
            print("setup: joined a network", flush=True)
            return
        self.nmcli("con", "delete", ssid)  # don't keep a wrong password around
        self.start(error=f"Couldn't join {ssid}." + (" Check the password and try again." if password else " Try again, or pick another network."))

    def submit(self, ssid, password):
        """From the phone. Checks what it can before the hotspot goes away."""
        if self.state != "hotspot":
            raise ValueError("not in setup")
        if not isinstance(ssid, str) or not ssid or len(ssid.encode()) > 32:
            raise ValueError("pick a network")
        if not isinstance(password, str) or (password and not 8 <= len(password) <= 63):
            raise ValueError("Wi-Fi passwords are 8 to 63 characters")
        threading.Thread(target=self.join, args=(ssid, password), daemon=True).start()

    def status(self):
        return {"state": self.state, "ssid": self.ssid, "password": self.password if self.state == "hotspot" else "", "error": self.error}

    def watch(self):
        """Run for good. No network for GRACE seconds (or at once if none is saved) starts setup; while in setup, a box with saved
        networks tries them again every RETRY_SAVED seconds, so an outage can't leave it stuck here."""
        if not self.has_wifi():
            return  # Ethernet only: nothing this can do
        missing_since = time.monotonic()
        if not self.online() and not self.saved_wifi():
            self.state = "checking"  # the home screen sees this and steps aside at once
        while True:
            time.sleep(10)
            if self.state == "joining":
                continue
            if self.state == "hotspot":
                if self.saved_wifi() and time.monotonic() - self.started > RETRY_SAVED:
                    self.stop()
                    self.show(page_url("home.html"))
                    missing_since = time.monotonic() - GRACE + 60  # a minute to reconnect, then back to setup
                continue
            if self.online():
                missing_since = time.monotonic()
                if self.state == "checking":
                    self.state = "off"
            elif time.monotonic() - missing_since > (GRACE if self.saved_wifi() else FIRST_BOOT_GRACE):
                self.start()


def handler(setup):
    page = (WEB_HOME / "setup-phone.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        timeout = 20

        def reply(self, code, body, ctype="text/html; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/networks":
                return self.reply(200, json.dumps(setup.networks).encode(), "application/json")
            self.reply(200, page)  # anything else: this page, so phones see a captive portal and open it

        def do_POST(self):
            try:
                n = int(self.headers.get("Content-Length", 0))
                if not 0 <= n <= 2000:
                    raise ValueError("too big")
                data = json.loads(self.rfile.read(n))
                if not isinstance(data, dict):
                    raise ValueError("not a form")
                setup.submit(data.get("ssid"), data.get("password", ""))
                self.reply(200, b"ok", "text/plain")
            except Exception as ex:
                self.reply(400, str(ex).encode(), "text/plain")

        def log_message(self, *args):
            pass  # never log what people send here

    return Handler

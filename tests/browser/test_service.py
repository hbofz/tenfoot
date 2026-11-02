"""The real service against a real Chromium: the phone's API, the watcher, popups, identities, the pages.
Only the virtual keyboard and mouse are faked. Opens youtube.com/tv and shahid.mbc.net (nothing plays, no account).
Run: python3 tests/browser/test_service.py [screenshot dir]"""
import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

import websocket
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tenfoot import apps, browser, config, links, server, sites, watcher  # noqa: E402
from tenfoot.__main__ import render  # noqa: E402
from tenfoot.controls import Controls  # noqa: E402

CDP = 9377
TOKEN = "e2e-test-token-123456"
WWW = os.path.join(os.path.dirname(__file__), "popups", "www")
SHOTS = sys.argv[1] if len(sys.argv) > 1 else None


class FakeInput:
    def __init__(self):
        self.log = []

    def __getattr__(self, name):
        return lambda *a: self.log.append((name, *a))


def wait(check, what, secs=20):
    end = time.time() + secs
    while time.time() < end:
        try:
            v = check()
            if v:
                return v
        except Exception:
            pass
        time.sleep(0.2)
    raise AssertionError("timed out waiting for " + what)


def main():
    settings = config.Settings(remote_mode="url", remote_url="http://127.0.0.1", latitude=51.5, longitude=-0.12)
    render(settings)
    links.write_qr(settings, TOKEN)
    profile = tempfile.mkdtemp()
    with sync_playwright() as p:
        exe = p.chromium.executable_path
        chrome = subprocess.Popen([exe, "--headless=new", f"--remote-debugging-port={CDP}", f"--user-data-dir={profile}",
                                   "--no-first-run", "--no-sandbox", "--window-size=1920,1080", "--disable-features=BackForwardCache,Translate",
                                   apps.page_url("home.html")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        site = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory=WWW))
        site.RequestHandlerClass.log_message = lambda *a: None
        threading.Thread(target=site.serve_forever, daemon=True).start()
        try:
            cdp = browser.Browser(CDP)
            wait(lambda: cdp.current_url(), "the browser")
            script = watcher.injected_script()
            opened = []
            def watch():
                try:
                    watcher.run(cdp, script, "", lambda: opened.append(1))
                except websocket.WebSocketException:
                    pass  # the browser closed at the end of the test
            threading.Thread(target=watch, daemon=True).start()
            time.sleep(1)
            inp = FakeInput()
            controls = Controls(inp, cdp, settings, apps.load_apps(settings))
            remote = http.server.ThreadingHTTPServer(("127.0.0.1", 0), server.remote_handler(controls, TOKEN))
            threading.Thread(target=remote.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{remote.server_address[1]}/{TOKEN}"

            def api(**cmd):
                r = urllib.request.urlopen(urllib.request.Request(base + "/api", data=json.dumps(cmd).encode(), method="POST"), timeout=20).read()
                return r if r == b"ok" else json.loads(r)
            js = lambda e: cdp.evaluate(e)["result"].get("value")

            # Home, through the phone's API
            api(a="home")
            wait(lambda: api(a="state")["app"] == "home", "home")
            wait(lambda: js("document.querySelectorAll('.tile').length") == len(controls.apps), "the tiles")
            assert js("document.title") == "Tenfoot"
            assert "YouTube" in js("[...document.querySelectorAll('.icon')].map((e) => e.textContent).join()")
            wait(lambda: js("document.getElementById('rq').hidden === false"), "the QR code")
            wait(lambda: js("document.getElementById('temp').textContent.endsWith('°')"), "the weather")
            print("ok home: tiles, QR, weather")

            assert "url" not in api(a="apps")[0]

            # A web page: the TV layer is injected, the phone can type and toast
            controls.go(f"http://127.0.0.1:{site.server_address[1]}/app.html")
            wait(lambda: cdp.current_url().endswith("/app.html"), "the test page")
            wait(lambda: js("!!window.tvHighlight || document.readyState === 'complete'"), "the page")
            assert js("window.__tenfoot === undefined")  # youtube.js only acts on YouTube
            controls.toast("hello", 3000)
            assert js("document.getElementById('tenfoot-toast').textContent") == "hello"
            print("ok web page: layer injected, toast")

            # Ad popups: opened by a site, closed at once, and the opener still works
            controls.go(f"http://127.0.0.1:{site.server_address[1]}/index.html")
            wait(lambda: cdp.current_url().endswith("/index.html"), "the popup page")
            cdp.call("Runtime.evaluate", {"expression": "window.open('http://127.0.0.1:%d/ad.html')" % site.server_address[1], "userGesture": True})
            time.sleep(2)
            tabs = [t for t in json.load(urllib.request.urlopen(cdp.base + "/json/list", timeout=3)) if browser.on_screen(t)]
            assert len(tabs) == 1 and tabs[0]["url"].endswith("/index.html"), tabs
            assert js("1 + 1") == 2  # not frozen
            print("ok ad popup closed, opener alive")

            # Identities on the real sites
            before = len(opened)
            api(a="app", k="youtube")
            wait(lambda: api(a="state")["app"] == "youtube", "YouTube")
            wait(lambda: js("navigator.userAgent") == sites.TV_UA, "the TV identity")
            wait(lambda: js("document.title").startswith("YouTube"), "YouTube's TV app", 30)
            assert len(opened) > before  # Spotify would be paused
            time.sleep(1)
            assert js("JSON.stringify(window.__tenfoot)") is not None  # youtube.js is on
            if SHOTS:
                time.sleep(4)
            print("ok YouTube TV: TV identity, layer on")

            api(a="app", k="shahid")
            wait(lambda: api(a="state")["app"] == "shahid", "Shahid")
            wait(lambda: "Windows NT" in js("navigator.userAgent"), "the Windows identity")
            print("ok Shahid: Windows identity")

            api(a="home")
            wait(lambda: api(a="state")["app"] == "home", "home again")
            assert js("navigator.userAgent") not in (sites.TV_UA,)  # identity cleared
            print("ok back home, identity cleared")

            # The touchpad stream reaches the input device
            ws = websocket.create_connection(base.replace("http", "ws") + "/ws", timeout=5)
            ws.send(json.dumps({"a": "move", "dx": 5, "dy": 6}))
            wait(lambda: ("move", 5.0, 6.0) in inp.log, "the pointer stream")
            ws.close()
            print("ok pointer stream")

            # The phone's Spotify settings: an account this phone added shows as its own, another's as locked
            class FakeSpotify:
                def command(self, cmd):
                    return {"active": None, "lyricsMs": 0, "accounts": [{"id": "me", "name": "Mine", "keyid": "abc"}, {"id": "them", "name": "Theirs", "keyid": "def"}]}
                def music(self):
                    return None
            controls.spotify = FakeSpotify()
            phone = p.chromium.launch().new_page(viewport={"width": 390, "height": 844})
            phone.add_init_script("""localStorage.setItem("tenfootSpotifyKeys", JSON.stringify({ abc: "k" }));
                                     Object.defineProperty(crypto, "subtle", { value: undefined });""")  # as on plain HTTP
            phone.goto(base + "/")
            phone.click("#gear")
            phone.wait_for_selector(".acct")
            assert phone.locator(".acct .x").count() == 1 and phone.locator(".acct .locked").count() == 1
            if SHOTS:
                phone.screenshot(path=os.path.join(SHOTS, "n-remote-settings.png"))
            controls.spotify = None
            print("ok phone settings work without crypto.subtle")

            # Restarting the watcher while a page is open re-applies its identity (service restart)
            # covered in test_core: Watcher.test_reconnecting_reapplies_an_open_pages_identity
            print("service e2e ok")
        finally:
            chrome.kill()
            chrome.wait()
            shutil.rmtree(profile, ignore_errors=True)


main()

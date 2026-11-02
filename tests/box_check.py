"""Run on an installed box: python3 tests/box_check.py   Checks the running service, browser and input for real,
through the same API the phone uses. Opens sites but plays nothing and signs in to nothing. Prints no secrets."""
import grp
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tenfoot import browser, config, links, sites  # noqa: E402

settings = config.load()
token = links.load_token()
base = f"http://127.0.0.1:{settings.remote_port}/{token}"
cdp = browser.Browser(config.CDP_PORT)
failures = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)
    if not ok:
        failures.append(name)


def api(**cmd):
    req = urllib.request.Request(base + "/api", data=json.dumps(cmd).encode(), method="POST")
    body = urllib.request.urlopen(req, timeout=30).read()
    return body if body == b"ok" else json.loads(body)


def js(expression):
    return cdp.evaluate(expression)["result"].get("value")


def js_await(expression):
    return cdp.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True})[0]["result"].get("value")


def wait(fn, secs=30):
    end = time.time() + secs
    while time.time() < end:
        try:
            value = fn()
            if value:
                return value
        except Exception:
            pass
        time.sleep(0.3)
    return None


def status(url, method="GET"):
    try:
        return urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=5).status
    except urllib.error.HTTPError as e:
        return e.code


check("the TV's user has no sudo", subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode != 0
      and not {"sudo", "adm"} & {grp.getgrgid(g).gr_name for g in os.getgroups()})
check("browser answers", wait(cdp.current_url, 60))
check("wrong token gets 404", status(f"http://127.0.0.1:{settings.remote_port}/wrong/") == 404)
check("phone page loads", b"Tenfoot" in urllib.request.urlopen(base + "/", timeout=5).read())

api(a="home")
check("home screen", wait(lambda: api(a="state")["app"] == "home"))
check("tiles", wait(lambda: js("document.querySelectorAll('.tile').length") == len(api(a="apps"))))
check("QR code", wait(lambda: js("document.getElementById('rq').hidden === false"), 70))
have = [f for f in os.listdir(config.WEB_HOME / "wallpapers") if f.endswith(".jpg") and "-blur" not in f] if (config.WEB_HOME / "wallpapers").is_dir() else []
if have:
    check(f"a photo is showing ({len(have)} downloaded)", wait(lambda: js("document.querySelectorAll('#photos img.on').length"), 40))

first = js("[...document.querySelectorAll('.tile')].indexOf(document.activeElement)")
api(a="key", k="right")
moved = wait(lambda: js("[...document.querySelectorAll('.tile')].indexOf(document.activeElement)") != first, 5)
check("real key press through the virtual keyboard moves the focus", moved)
api(a="key", k="left")

for n, bad in enumerate(("http://127.0.0.1:9222/json", "file:///etc/passwd")):
    marker = ("9222", "passwd")[n]
    api(a="open", url=bad)
    url = wait(lambda: marker in cdp.current_url() and cdp.current_url(), 20) or cdp.current_url()
    check(f"phone can't open {bad}", url.startswith("https://www.google.com/search"), url[:60])

api(a="open", url="https://example.com/")
check("a site opens", wait(lambda: "example.com" in cdp.current_url()))
wait(lambda: js("document.readyState") == "complete")
check("TV layer is on the page", wait(lambda: js("'tvHighlight' in window"), 15))
api(a="key", k="down")
check("a real key press moves the highlight on a website", wait(lambda: js("!!window.tvHighlight"), 8))
for name, url in (("local API", f"http://127.0.0.1:{config.LOCAL_PORT}/lyrics?track=x"), ("DevTools", f"http://127.0.0.1:{config.CDP_PORT}/json"),
                  ("Spotify", "http://127.0.0.1:3678/status")):
    got = js_await(f"fetch({json.dumps(url)}, {{mode: 'no-cors'}}).then(() => 'reached', () => 'blocked')")
    check(f"a website can't reach {name}", got == "blocked", got)
widevine = js_await("""navigator.requestMediaKeySystemAccess('com.widevine.alpha', [{initDataTypes: ['cenc'],
  videoCapabilities: [{contentType: 'video/mp4; codecs="avc1.42E01E"', robustness: 'SW_SECURE_DECODE'}]}]).then(() => 'yes', (e) => String(e))""")
check("Widevine", widevine == "yes", widevine)

api(a="app", k="youtube")
check("YouTube opens as the TV app", wait(lambda: js("navigator.userAgent") == sites.TV_UA, 40))
check("YouTube layer loaded", wait(lambda: js("!!window.__tenfoot"), 30))
api(a="app", k="netflix")
check("Netflix gets stock Chrome", wait(lambda: api(a="state")["app"] == "netflix" and js("navigator.userAgent") != sites.TV_UA, 40))
api(a="tv", k="mute")
api(a="tv", k="mute")
check("service still answers after mute", api(a="state")["app"] == "netflix")

if settings.spotify:
    state = status("http://127.0.0.1:3678/auth/code")
    check("Spotify player answers", state in (200, 204), str(state))
    api(a="app", k="spotify")
    panel = wait(lambda: js("[...document.querySelectorAll('section.panel, main')].filter((e) => !e.hidden).map((e) => e.id).join()"), 20)
    check("Spotify screen", panel in ("pair", "idle", "now"), str(panel))

api(a="home")
check("home again", wait(lambda: api(a="state")["app"] == "home"))
check("QR code again", wait(lambda: js("document.getElementById('rq').hidden === false"), 70))
print("\n" + (f"{len(failures)} FAILED: {failures}" if failures else "ALL OK"))
sys.exit(1 if failures else 0)

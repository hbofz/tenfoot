"""Sign out of everything, or reset the TV to how it came, from the phone. Either one first shows a code on the TV that
has to be typed on the phone: proof that whoever asks can see the screen (a link that leaked can't wipe a box from
afar). Not from the guest link.

Sign out: every site's login (the browser's whole profile but Widevine, cleared by system/kiosk.sh just before the
browser starts, since it holds those files open) and Spotify's accounts.
Reset: that, and new links (every phone's stops working), the setup hotspot's password, the TV's own settings from the
phone (name, place, units, updates), the timezone, AirPlay's key, and saved Wi-Fi (so the setup screen comes up; last:
the phone asking loses the TV there). A reset that a power cut cuts short finishes as the service next starts.
Kept: Tenfoot itself and its updates, the photos, Widevine, the hostname, and an admin's settings (display, remote mode,
Jellyfin, idle times)."""
import getpass
import json
import secrets
import subprocess
import threading
import time
from pathlib import Path

from . import config, kiosk, settings as phone_settings
from .apps import page_url
from .config import CONFIG_DIR, CHROMIUM_PROFILE
from .overlay import toast_js

CODE_FOR, TRIES, ASK_GAP = 120, 3, 20  # TRIES: wrong codes, in all, before each (longer) lock
PHONE_KEYS = ("name", "place", "latitude", "longitude", "temperature_unit", "updates")
_lock = threading.Lock()
_asked = {}  # sign-out and reset: what's waiting for its code: {"kind", "code", "until", "tries"}
_asked_at = [-1e9]  # the last ask (time.monotonic)
# "Make this my remote" (any guest can ask) has codes, timing and wrong-code count of its own: a guest locking that out
# mustn't lock the owner out of signing out or resetting.
_own_asked, _own_asked_at = {}, [-1e9]


def state(kind):
    """(the code waiting, the last ask, the wrong-code file) for kind's group."""
    return (_own_asked, _own_asked_at, "own-guard") if kind == "own" else (_asked, _asked_at, "wipe-guard")


def guard(name="wipe-guard"):
    """Wrong codes so far and the lock they earned, kept on disk: a service restart (a rename from the phone does one)
    mustn't give a guesser a fresh start. locked_until is wall-clock time, which a restart doesn't reset."""
    try:
        g = json.loads(marker(name).read_text())
        return {"wrong": int(g["wrong"]), "rounds": int(g["rounds"]), "locked_until": float(g["locked_until"])}
    except (OSError, ValueError, KeyError, TypeError):
        return {"wrong": 0, "rounds": 0, "locked_until": 0.0}


def save_guard(g, name="wipe-guard"):
    config.write_private(marker(name), json.dumps(g))
SHOW = """(() => {
  if (location.protocol !== "file:") return false;  // only on the TV's own page: no website can read it there
  TOAST;
  return true;
})()"""


def marker(name):
    return CONFIG_DIR / name


WHAT = {"signout": "sign this TV out of everything", "reset": "reset this TV to how it came",
        "own": "make your phone a full remote for this TV"}


def ask(kind, browser):
    """Show a fresh code for a sign-out, a reset, or making a phone a full remote ("own"), on the TV's own home screen
    (a website on screen could read it)."""
    if kind not in WHAT:
        raise ValueError("Sign out, reset, or make this phone a remote")
    now = time.monotonic()
    asked, asked_at, name = state(kind)
    with _lock:
        locked = guard(name)["locked_until"] - time.time()
        if locked > 0:
            raise ValueError(f"Too many wrong codes: try again in {int(locked) // 60 + 1} min")
        if now - asked_at[0] < ASK_GAP:
            raise ValueError("A code is already on the TV")
        try:
            save_guard(guard(name), name)  # no code unless wrong ones can be counted (a full disk: none at all)
        except OSError:
            raise ValueError("Couldn't get ready (is the storage full?): try again later") from None
        asked_at[0] = now
        code = f"{secrets.randbelow(10000):04d}"
        asked.clear()
    what = WHAT[kind]
    browser.one_tab()
    browser.navigate(page_url("home.html"))
    js = SHOW.replace("TOAST", toast_js(f"To {what}, type {code} on your phone", CODE_FOR * 1000))
    for _ in range(20):  # navigate returns before the home screen is there: an evaluate could land on the old page
        time.sleep(0.5)
        try:
            if browser.evaluate(js).get("result", {}).get("value") is True:
                break
        except Exception:
            pass
    else:
        raise ValueError("The TV didn't show the code: try again")
    with _lock:
        asked.update(kind=kind, code=code, until=time.monotonic() + CODE_FOR, tries=0)


def confirm(kind, code):
    """True if code is the one the TV is showing for kind. Every try is counted on disk before it's checked (so no guess
    is ever compared unless it's on record), and every third wrong one, however many asks they were spread over, locks
    it for longer: 1, 2, 4... minutes. Guessing a 4-digit code is hopeless that way."""
    _asked, _, name = state(kind)
    with _lock:
        if not _asked or _asked["kind"] != kind or time.monotonic() > _asked["until"]:
            _asked.clear()
            raise ValueError("That code has run out: ask again")
        g = guard(name)
        g["wrong"] += 1  # until shown otherwise
        if g["wrong"] % TRIES == 0:
            g["rounds"] += 1
            g["locked_until"] = time.time() + 60 * 2 ** min(g["rounds"] - 1, 10)
        try:
            save_guard(g, name)
        except OSError:  # can't count it: no more guesses at this code
            _asked.clear()
            raise ValueError("Couldn't record that: try again later") from None
        if secrets.compare_digest(str(code), _asked["code"]):
            _asked.clear()
            marker(name).unlink(missing_ok=True)  # right: the count starts again
            return True
        if g["wrong"] % TRIES == 0:
            _asked.clear()
            raise ValueError("Too many wrong codes: wait a while, then ask again")
        raise ValueError("That's not the code on the TV")


def run(*args):
    """A step's command; one that hangs or is missing doesn't stop the rest."""
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError) as ex:
        print(f"wipe: {args[0]}: {ex}", flush=True)
        return subprocess.CompletedProcess(args, 1, "", "")


def sign_out():
    """Every login: the browser's (on its next start, see system/kiosk.sh) and Spotify's."""
    marker("wipe-browser").write_text("")
    run("systemctl", "--user", "stop", "tenfoot-spotify")
    spotify = Path.home() / ".config/go-librespot"
    (spotify / "state.json").unlink(missing_ok=True)
    for f in (spotify / "profiles").glob("*") if (spotify / "profiles").is_dir() else ():
        f.unlink()
    (config.RUN / "spotify-profiles.js").unlink(missing_ok=True)  # the TV's list of accounts (made again when one logs in)
    run("systemctl", "--user", "start", "tenfoot-spotify")  # (a box without Spotify has no such unit: nothing happens)
    kiosk.restart_chromium(str(Path(CHROMIUM_PROFILE).expanduser()))


def wifi_connections():
    out = run("nmcli", "-t", "-f", "UUID,TYPE", "connection", "show").stdout
    return [ln.split(":")[0] for ln in out.splitlines() if ln.endswith(":802-11-wireless")]


def reset(keep_wifi=False):
    """Back to how it came (see the top). Every step can run again: a marker makes the next start finish it (its name
    says whether to keep Wi-Fi: a file's content could be lost in a power cut, its name can't)."""
    if getpass.getuser() != "tenfoot":
        raise SystemExit("A reset is for the TV box's own user (tenfoot reset): not this machine's Wi-Fi")
    pending = marker("reset-pending-keep-wifi" if keep_wifi else "reset-pending")
    pending.write_text("")
    sign_out()
    for name in ("token", "people", "setup-password", "timezone-set"):
        (CONFIG_DIR / name).unlink(missing_ok=True)
    (Path.home() / ".config/uxplay/key.pem").unlink(missing_ok=True)
    path = CONFIG_DIR / "config.toml"
    if path.exists():
        try:
            values = config.load(path)
        except (SystemExit, ValueError):  # unreadable (maybe why it's being reset): start again from the example
            config.write_private(path, (config.ROOT / "config.example.toml").read_text())
        else:
            keys = [k for k in PHONE_KEYS if not (k == "updates" and values.updates == "off")]  # a developer's "off" stays
            phone_settings.unset(keys)
    try:
        phone_settings.rename_services(config.Settings.name)  # Spotify and AirPlay too, AirPlay with a new key
    except Exception as ex:  # a hung restart mustn't stop the reset short of forgetting Wi-Fi
        print("wipe: renaming Spotify and AirPlay:", ex, flush=True)
    if not keep_wifi:
        for uuid in wifi_connections():
            run("nmcli", "connection", "delete", "uuid", uuid)
    marker("reset-pending").unlink(missing_ok=True)
    marker("reset-pending-keep-wifi").unlink(missing_ok=True)
    print(f"wipe: reset{' (Wi-Fi kept)' if keep_wifi else ''}", flush=True)


def finish_pending():
    """A reset a power cut cut short: finish it (called as the service starts, before it reads the links)."""
    for name, keep in (("reset-pending", False), ("reset-pending-keep-wifi", True)):
        if marker(name).exists():
            print("wipe: finishing a reset that was cut short", flush=True)
            return reset(keep_wifi=keep)

"""Nobody at the remote: after screensaver_minutes, dim an app that isn't playing anything (a paused show or a menu
burns into an OLED; the home screen has its own screensaver); after standby_hours, warn, then pause, dim and turn the
TV off over HDMI-CEC (YouTube autoplaying all night counts as nobody there; some TVs ignore "off" from a device, and
then it's at least dark), unless music is on or the TV is showing another input. Remote presses (controls.handle) and keys or a mouse straight on the page count as someone there; the
phone checking in every few seconds doesn't."""
import json
import subprocess
import time

from .overlay import dim_js, toast_js

CHECK_EVERY, WARN_FOR = 30, 60
OWN_PAGES = ("/home.html", "/sleep.html", "/setup.html", "/spotify.html")  # the TV's own: they look after themselves
last = time.monotonic()  # the last remote press
dimmed = False

# Asked of the page each round: is something playing, and how long since a key or the mouse on the page itself (a
# keyboard plugged into the Pi goes straight to the browser, past the service).
PROBE = """(() => {
  if (window.__tenfootInput === undefined) {
    window.__tenfootInput = 0;  // none seen yet: a page loading by itself (autoplay's next show) isn't someone there
    for (const t of ["keydown", "pointermove", "pointerdown", "wheel"]) addEventListener(t, (e) => e.isTrusted && (window.__tenfootInput = Date.now()), true);
  }
  const playing = [...document.querySelectorAll("video")].some((v) => !v.paused && !v.ended && v.readyState >= 2) ||
    navigator.mediaSession?.playbackState === "playing";
  return JSON.stringify({ playing, since: window.__tenfootInput ? (Date.now() - window.__tenfootInput) / 1000 : 1e9, url: location.href,
                          dimmed: !!document.getElementById("tenfoot-dim") || !!window.__tenfootDimmed });
})()"""


def poke():
    global last
    last = time.monotonic()


def browser_audio():
    """Is the browser sending sound right now? PipeWire hears players the page can't show us: in a frame from another
    site (Crunchyroll's), inside a shadow root, behind DRM."""
    try:
        out = subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"], capture_output=True, text=True, timeout=10).stdout
        return any(not s.get("corked") and "chrom" in json.dumps(s.get("properties", {})).lower() for s in json.loads(out or "[]"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def decide(idle_s, quiet_s, music, url, settings, warned):
    """What to do now: "standby" (after a warning), "warn", "dim", "undim", or None. idle_s: since the last press;
    quiet_s: since anything last played (a gap between episodes isn't quiet for long)."""
    if settings.standby_hours and idle_s >= settings.standby_hours * 3600 and not music:
        return "standby" if warned else "warn"
    t = settings.screensaver_minutes * 60
    if t and idle_s >= t and quiet_s >= t and not url.endswith(OWN_PAGES):
        return None if dimmed else "dim"
    return "undim" if dimmed else None


def set_dim(browser, on):
    """Dim or undim; True if the page changed (undimming a page that wasn't dim: False)."""
    global dimmed
    if on:
        dimmed = True  # first: a press landing mid-way should wake it (the next probe corrects this if it failed)
    r = browser.evaluate(dim_js(on))
    if "exceptionDetails" in r:  # the page refused it: don't believe it happened
        raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", "dim failed"))
    dimmed = on
    return on or bool(r.get("result", {}).get("value"))


def wake(browser):
    """Someone's at the remote. True if that press woke a dimmed picture (and so should do nothing else)."""
    poke()
    if not dimmed:
        return False
    try:
        return set_dim(browser, False)
    except Exception:
        return False


def loop(browser, tv, spotify, settings):
    global dimmed
    warned, slept = None, False  # slept: done already, stay dark and quiet until someone's back
    played = time.monotonic()
    while True:
        time.sleep(CHECK_EVERY)
        try:
            page = json.loads(browser.evaluate(PROBE)["result"]["value"])
        except Exception:
            continue  # browser restarting
        dimmed = page["dimmed"]  # the page knows: a new page (the TV woke to the home screen) isn't dim
        now = time.monotonic()
        if page["playing"] or browser_audio():
            played = now
        idle_s = min(now - last, page["since"])
        music = bool(spotify and (spotify.music() or {}).get("paused") is False)
        step = decide(idle_s, now - played, music, page["url"], settings, warned and now - warned >= WARN_FOR)
        if step not in ("warn", "standby"):
            if warned:
                try:
                    browser.evaluate('document.getElementById("tenfoot-toast")?.remove()')  # someone's back: no warning
                except Exception:
                    pass
            warned, slept = None, False
        elif slept:
            if not dimmed and not page["url"].endswith(OWN_PAGES):
                try:
                    set_dim(browser, True)  # the page moved on by itself while the TV (ignoring "off") stays on: dark again
                except Exception:
                    pass
            continue
        if step == "dim" and time.monotonic() - last < settings.screensaver_minutes * 60:
            continue  # a press came in meanwhile
        try:
            if step == "dim":
                set_dim(browser, True)
            elif step == "undim":
                set_dim(browser, False)
            elif step == "warn" and not warned:
                warned = time.monotonic()
                browser.evaluate(toast_js("No one's pressed a button for a while: the TV turns off in a minute. Press any to keep watching.", WARN_FOR * 1000))
            elif step == "standby":
                warned, slept = None, True
                if tv is None or tv.showing is not False:  # not while the TV is showing another input
                    print(f"idle: nobody for {idle_s / 3600:.1f} h, pausing and turning the TV off", flush=True)
                    browser.evaluate('document.querySelectorAll("video").forEach((v) => v.pause())')
                    if not page["url"].endswith(OWN_PAGES):
                        set_dim(browser, True)  # some TVs ignore "off" over CEC: then at least it's dark and still
                    if tv:
                        tv.on_off()  # the music too
                        if tv.power == "on":
                            tv.set_power("off")
        except Exception as ex:
            print("idle:", ex, flush=True)

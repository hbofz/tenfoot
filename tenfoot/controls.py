"""What the remotes can do. Every command, from the phone or a physical remote, comes through handle()."""
import subprocess

from .apps import app_of, app_urls, page_url, to_url
from .cursor import Cursor
from .inputs import KEYS
from .overlay import toast_js, volume_js

SINK = "@DEFAULT_AUDIO_SINK@"


def back_keys(url):
    """YouTube's TV app handles Escape itself; everywhere else use browser back."""
    return ["KEY_ESC"] if "youtube.com/tv" in url else ["KEY_LEFTALT", "KEY_LEFT"]


def volume_level(wpctl_out):
    """'Volume: 0.45 [MUTED]' -> (45, True)."""
    return round(float(wpctl_out.split()[1]) * 100), "MUTED" in wpctl_out


class Controls:
    def __init__(self, inp, browser, settings, apps, tv=None, spotify=None):
        self.inp, self.browser, self.settings, self.apps = inp, browser, settings, apps
        self.urls = app_urls(apps)
        self.tv, self.spotify = tv, spotify  # None: not on this box
        self.cursor = Cursor(inp, *settings.screen, toast=self.toast, keyboard_open=self._keyboard_open)

    def _keyboard_open(self):
        return self.browser.evaluate("!!window.tvKeyboard")["result"]["value"]

    def toast(self, text, ms):
        try:
            self.browser.evaluate(toast_js(text, ms))
        except Exception:
            pass  # a nicety

    def volume(self, k):
        """Volume and mute on this box's own sound, with a bar on screen. TVs ignore CEC volume from a
        playback device, so this tops out at the TV's own level."""
        if k == "mute":
            subprocess.run(["wpctl", "set-mute", SINK, "toggle"], timeout=5)
        else:
            subprocess.run(["wpctl", "set-volume", "-l", "1", SINK, "5%+" if k == "volup" else "5%-"], timeout=5)
        out = subprocess.run(["wpctl", "get-volume", SINK], capture_output=True, text=True, timeout=5).stdout
        try:
            self.browser.evaluate(volume_js(*volume_level(out)))
        except Exception:
            pass  # the bar is a nicety; the volume already changed

    def state(self):
        """Everything the phone shows about the TV, polled every couple of seconds."""
        s = {"app": None, "host": None, "power": self.tv.power if self.tv else None,
             "music": self.spotify.music() if self.spotify else None}
        try:
            s["app"], s["host"] = app_of(self.browser.current_url(), self.settings.jellyfin_url)
        except Exception:
            pass  # browser restarting
        return s

    def go(self, url):
        self.browser.one_tab()
        self.browser.navigate(url)

    def handle(self, cmd):
        a, k = cmd.get("a"), cmd.get("k")
        if self.cursor.on and a in ("move", "click", "scroll"):
            self.cursor.set(False, quiet=True)  # the phone's touchpad has the pointer now
        if a == "cursor":
            return self.cursor.set(not self.cursor.on)
        if self.cursor.on and self.cursor.key(cmd):
            return None
        if a == "key" and k == "playpause" and self.spotify and self.browser.current_url().endswith("/spotify.html"):
            self.spotify.api("/player/playpause")
        elif a == "key" and k in KEYS:
            for _ in range(max(1, min(50, int(cmd.get("n", 1))))):  # n: the phone's keyboard deleting several
                self.inp.press([KEYS[k]])
        elif a == "back":
            self.inp.press(back_keys(self.browser.current_url()))
        elif a == "move":
            self.inp.move(float(cmd.get("dx", 0)), float(cmd.get("dy", 0)))
        elif a == "click":
            self.inp.click(cmd.get("button", "left"))
        elif a == "scroll":
            self.inp.scroll(cmd.get("n", 0))
        elif a == "home":
            self.go(page_url("home.html"))
        elif a == "app" and k in self.urls:
            self.go(self.urls[k])
        elif a == "state":
            return self.state()
        elif a == "apps":  # names and colours, never URLs
            return [{f: x[f] for f in ("id", "name", "color", "mouse")} for x in self.apps]
        elif a == "open" and cmd.get("url", "").strip():
            self.go(to_url(cmd["url"], self.settings.jellyfin_url))
        elif a == "type" and cmd.get("text"):
            self.browser.call("Input.insertText", {"text": cmd["text"]})
        elif a == "tv" and k in ("volup", "voldown", "mute"):
            self.volume(k)
        elif a == "tv" and k in ("on", "off") and self.tv:
            self.tv.set_power(k)
        elif a == "spotify" and self.spotify:
            return self.spotify.command(cmd)
        else:
            raise ValueError("unknown command")
        return None

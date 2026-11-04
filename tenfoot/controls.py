"""What the remotes can do. Every command, from the phone or a physical remote, comes through handle()."""
import subprocess
import threading

from .apps import app_of, app_urls, page_url, to_url
from .cursor import Cursor
from .inputs import KEYS
from .overlay import toast_js, volume_js
from . import clock, health, idle, links, settings as phone_settings, updates, wipe

SINK = "@DEFAULT_AUDIO_SINK@"
PASSIVE = {"state", "apps", "health", "settings", "update", "timezone"}  # the phone checking in: not someone at the remote
WAKE = {"key", "back", "move", "click", "scroll"}  # on a dimmed screen these only wake it


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

    def change_settings(self, cmd):
        """From the phone's Settings (tenfoot/settings.py): save, then make it show. Not from the guest link."""
        if cmd.get("by") == "guest":
            raise ValueError("Guests can't change the TV's settings")
        new, zone = phone_settings.checked(cmd)
        with phone_settings.lock:
            renamed = "name" in new and new["name"] != self.settings.name
            self.settings = phone_settings.save(new)
            phone_settings.render(self.settings)
        try:
            if self.browser.current_url().endswith("/home.html"):
                self.go(page_url("home.html"))  # the new weather or name, now
        except Exception:
            pass
        if renamed:
            # the TV's own name over HDMI is set as the service starts: start again, once this reply is out
            threading.Timer(1.5, subprocess.run, (["systemctl", "--user", "restart", "tenfoot"],)).start()
            phone_settings.rename_services(self.settings.name)
        if zone:
            try:
                clock.mark().write_text(clock.set_zone(zone) + "\n")  # chosen on purpose: phones stop guessing
            except Exception as ex:
                raise ValueError(f"Saved, but couldn't set the clock: {ex}") from None
        return phone_settings.current(self.settings)

    def wipe(self, kind, cmd):
        """Sign out of everything, or reset (tenfoot/wipe.py): first a code on the TV, then that code from the phone."""
        if cmd.get("by") == "guest":
            raise ValueError("Guests can't do that")
        if "code" not in cmd:
            wipe.ask(kind, self.browser)
            return {"asked": True}
        wipe.confirm(kind, cmd["code"])
        if kind == "signout":
            threading.Thread(target=wipe.sign_out, daemon=True).start()
        else:  # after this reply: the phone loses the TV (new links, Wi-Fi forgotten), and the service starts again
            threading.Timer(1.5, self.reset_then_restart).start()
        return {"done": kind}

    def own(self, cmd):
        """The TV's QR code gives a guest remote. A guest who can see the TV (the code shows only there) gets a link of
        their own: Settings and all, revoked with tenfoot revoke phone-N."""
        if cmd.get("by") != "guest":
            raise ValueError("This phone is a full remote already")
        if "code" not in cmd:
            wipe.ask("own", self.browser)
            return {"asked": True}
        wipe.confirm("own", cmd["code"])
        return {"link": links.add_person(self.settings, links.new_phone_name())}

    @staticmethod
    def reset_then_restart():
        try:
            wipe.reset()
        finally:  # always: until it starts again, the old links still work
            subprocess.run(["systemctl", "--user", "restart", "tenfoot"])

    def go(self, url):
        self.browser.one_tab()
        self.browser.navigate(url)

    def handle(self, cmd):
        a, k = cmd.get("a"), cmd.get("k")
        if (a not in PASSIVE or k in ("set", "now")) and idle.wake(self.browser) and a in WAKE:
            return None  # the press that wakes the picture does nothing else
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
        elif a == "settings":
            if k == "set":
                return self.change_settings(cmd)
            return {"canChange": False} if cmd.get("by") == "guest" else {**phone_settings.current(self.settings), "canChange": True}
        elif a == "wipe":
            return self.wipe(k, cmd)
        elif a == "own":
            return self.own(cmd)
        elif a == "health":
            return health.status()
        elif a == "timezone":
            return clock.adopt(cmd.get("tz"))
        elif a == "update":
            return updates.start() if k == "now" else updates.status()
        elif a == "spotify" and self.spotify:
            return self.spotify.command(cmd)
        else:
            raise ValueError("unknown command")
        return None

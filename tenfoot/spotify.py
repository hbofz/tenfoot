"""Spotify Connect, through go-librespot on localhost, with accounts only their owner can switch to.
Saved logins are encrypted with a key that only the owner's phone keeps. This box never writes a
key to disk: stealing the drive gets only ciphertext. A key is in memory only while its account is on."""
import hashlib
import html
import json
import os
import re
import secrets
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .apps import page_url
from .config import RUN, write_private

CONFIG = Path(os.path.expanduser("~/.config/go-librespot"))
IDLE_LOGOUT = 2 * 3600  # log the TV out after this long without music
ADD_WINDOW = 600  # how long one phone's "+ Add account" holds off another's


def keyid(key):
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def seal(key, obj):
    return Fernet(key.encode()).encrypt(json.dumps(obj).encode()).decode()


def unseal(key, blob):
    try:
        return json.loads(Fernet(key.encode()).decrypt(blob.encode()))
    except (InvalidToken, ValueError, TypeError):
        raise ValueError("that key doesn't unlock this account")


def valid_id(uid):
    return isinstance(uid, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", uid) is not None


def profile_name(page):
    """'<title>Sam on Spotify</title>' from a public profile page -> 'Sam'."""
    m = re.search(r"<title>(.*?) on Spotify</title>", page)
    return html.unescape(m.group(1)).strip()[:40] if m else None


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


class Spotify:
    def __init__(self, browser, player="http://127.0.0.1:3678", config_dir=CONFIG, run_dir=RUN):
        self.browser, self.player = browser, player
        self.state_file = Path(config_dir) / "state.json"
        self.profiles_dir = Path(config_dir) / "profiles"
        self.sync_file = Path(config_dir) / "lyrics-offset"
        self.run_dir = Path(run_dir)
        self.pending = {}  # key waiting for the next new login, from a phone that tapped "+ Add account"
        self.active = {}  # {"id", "key"} of the account playing now, if it was unlocked with its key
        self.saved = {}  # uid -> what was last written, so an unchanged login isn't rewritten
        self.lock = threading.Lock()  # the phone and the idle logout could otherwise switch at once

    # ---- the player ----
    def api(self, path):
        urllib.request.urlopen(urllib.request.Request(self.player + path, method="POST"), timeout=5).read()

    def status(self, timeout=2):
        """The player's /status ({} while logged out). While it waits for a spotify.com/pair code,
        /status hangs until the code is used, so ask /auth/code first (it answers at once)."""
        with urllib.request.urlopen(self.player + "/auth/code", timeout=timeout) as r:
            if b'"code"' in r.read():
                return {}
        return json.load(urllib.request.urlopen(self.player + "/status", timeout=timeout))

    def music(self):
        """What's playing, for the phone, or None (logged out, stopped, or the player restarting)."""
        try:
            st = self.status()
        except (OSError, ValueError):
            return None
        t = not st.get("stopped") and st.get("track")
        if not t:
            return None
        return {"name": t.get("name"), "artist": ", ".join(t.get("artist_names") or []), "art": t.get("album_cover_url"),
                "pos": t.get("position"), "dur": t.get("duration"), "uri": t.get("uri", ""), "paused": bool(st.get("paused"))}

    def pause(self):
        """Pause if playing (no-op otherwise, or if the player is down)."""
        try:
            st = self.status(3)
            if st.get("track") and not st.get("paused") and not st.get("stopped"):
                self.api("/player/pause")
        except (OSError, ValueError):
            pass

    # ---- saved accounts ----
    def logged_in(self):
        return read_json(self.state_file, {}).get("credentials", {}).get("username")

    def profile_path(self, uid):
        return self.profiles_dir / (uid + ".json")

    def saved_profiles(self):
        """[{id, name, keyid}] of every saved (encrypted) account, alphabetical."""
        out = []
        for f in sorted(os.listdir(self.profiles_dir)) if self.profiles_dir.is_dir() else []:
            uid, p = f[:-5], read_json(self.profiles_dir / f, {})
            if f.endswith(".json") and valid_id(uid) and p.get("blob"):
                out.append({"id": uid, "name": p.get("name") or "Spotify user", "keyid": p.get("keyid")})
        return sorted(out, key=lambda p: p["name"].lower())

    def publish_profiles(self):
        """Hand names (never keys or logins) to the TV's Spotify screen as a script file."""
        data = {"active": self.logged_in(), "accounts": [{"id": p["id"], "name": p["name"]} for p in self.saved_profiles()]}
        self.run_dir.mkdir(parents=True, exist_ok=True)
        write_private(self.run_dir / "spotify-profiles.js", f"window.spotifyProfiles = {json.dumps(data)};\n")

    def save_profile(self, uid, name, key):
        creds = read_json(self.state_file, {}).get("credentials") or {}
        if creds.get("username") != uid or not creds.get("data") or self.saved.get(uid) == (creds, name, key):
            return
        self.profiles_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_private(self.profile_path(uid), json.dumps({"name": name, "keyid": keyid(key), "blob": seal(key, creds)}))
        self.saved[uid] = (creds, name, key)

    def restart(self, credentials, show=True):
        """Restart the player as another account (credentials) or logged out, waiting for a
        spotify.com/pair code (None). The device ID stays, so phones keep seeing one speaker."""
        with self.lock:
            st = read_json(self.state_file, {})
            subprocess.run(["systemctl", "--user", "stop", "tenfoot-spotify"], check=True, timeout=20)
            try:
                new = {k: st[k] for k in ("device_id", "last_volume") if k in st}
                if credentials:
                    new["credentials"] = credentials
                write_private(self.state_file, json.dumps(new))
            finally:  # whatever happened, never leave the player stopped (Restart=always skips a manual stop)
                subprocess.run(["systemctl", "--user", "start", "tenfoot-spotify"], check=True, timeout=20)
        self.publish_profiles()
        if show:
            self.browser.navigate(page_url("spotify.html"))

    def watch_logins(self):
        """Watch who is logged in. A new login right after a phone tapped "+ Add account" is saved under
        that phone's key; the name comes from the public profile page (Spotify only reports a random ID).
        Renewed logins of the unlocked account are re-saved every minute, and the TV is logged out
        after IDLE_LOGOUT without music."""
        known, names, last_save, last_music = None, {}, 0, time.time()
        while True:
            try:
                st = self.status(3)
                user = st.get("username")
                if st.get("track") and not st.get("paused") and not st.get("stopped"):
                    last_music = time.time()
                if user and valid_id(user) and user not in names:
                    req = urllib.request.Request(f"https://open.spotify.com/user/{user}", headers={"User-Agent": "Mozilla/5.0"})
                    try:
                        names[user] = profile_name(urllib.request.urlopen(req, timeout=10).read(200000).decode("utf-8", "replace"))
                    except OSError:
                        names[user] = None
                if user and user != known:
                    if self.pending.get("key") and time.time() - self.pending.get("at", 0) < 1800:
                        self.active.update(id=user, key=self.pending.pop("key"))
                        self.save_profile(user, names.get(user), self.active["key"])
                    elif self.active.get("id") != user:
                        self.active.clear()  # logged in some other way (a code entered without a phone key)
                    last_music = time.time()
                if user and self.active.get("id") == user and time.time() - last_save > 60:
                    self.save_profile(user, names.get(user) or read_json(self.profile_path(user), {}).get("name"), self.active["key"])
                    last_save = time.time()
                if user != known or not (self.run_dir / "spotify-profiles.js").exists():
                    self.publish_profiles()
                    known = user
                if user and time.time() - last_music > IDLE_LOGOUT:
                    self.active.clear()  # the phone's key leaves memory with the account
                    self.restart(None, show=False)
                    known = None
            except (OSError, ValueError):
                pass  # player restarting or offline; try again
            except Exception as ex:
                print("spotify:", ex, flush=True)
            time.sleep(5)

    def lyrics_offset(self, delta=0):
        """Milliseconds the lyrics are shown later (+) or earlier (-) than the player's position, to
        match this TV's sound delay. Tuned by ear from the phone; kept across restarts."""
        try:
            ms = int(self.sync_file.read_text())
        except (OSError, ValueError):
            ms = 250  # TVs play sound a bit after the player reports it
        ms = max(-2000, min(2000, ms + int(delta)))
        if delta:
            self.sync_file.parent.mkdir(parents=True, exist_ok=True)
            write_private(self.sync_file, str(ms))
        self.run_dir.mkdir(parents=True, exist_ok=True)
        write_private(self.run_dir / "spotify-sync.js", f"window.spotifySync = {json.dumps({'lyricsMs': ms})};\n")
        return ms

    def command(self, cmd):
        """From the phone: next | prev | playpause | list | sync | logout | add | use/forget <id> + key."""
        k, uid, key = cmd.get("k"), cmd.get("id"), cmd.get("key")
        if k in ("next", "prev", "playpause"):
            return self.api("/player/" + k)
        if k == "list":
            return {"active": self.logged_in(), "accounts": self.saved_profiles(), "lyricsMs": self.lyrics_offset()}
        if k == "sync":
            return {"lyricsMs": self.lyrics_offset(max(-500, min(500, int(cmd.get("ms", 0)))))}
        if k == "logout":
            self.active.clear()
            return self.restart(None)
        if k == "add":
            if self.pending.get("key") and time.time() - self.pending["at"] < ADD_WINDOW and self.pending.get("by") != cmd.get("by"):
                # Another link is mid-way through adding an account; taking over would save their login under this phone's key.
                raise ValueError("someone else is adding a Spotify account; try again in a few minutes")
            new_key = Fernet.generate_key().decode()
            self.pending.update(key=new_key, at=time.time(), by=cmd.get("by"))
            self.active.clear()
            self.restart(None)
            return {"key": new_key, "keyid": keyid(new_key)}
        if not valid_id(uid) or not self.profile_path(uid).exists():
            raise ValueError("no saved Spotify account with that id")
        p = read_json(self.profile_path(uid), {})
        if not isinstance(key, str) or not secrets.compare_digest(keyid(key), p.get("keyid") or ""):
            raise ValueError("only the phone that added this account can use it")
        if k == "use":
            creds = unseal(key, p["blob"])
            self.active.update(id=uid, key=key)
            return self.restart(creds)
        if k == "forget":
            os.remove(self.profile_path(uid))
            if self.logged_in() == uid:
                self.active.clear()
                return self.restart(None)
            return self.publish_profiles()
        raise ValueError("unknown spotify command")

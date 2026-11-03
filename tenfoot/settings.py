"""Settings from the phone remote, so nobody edits config.toml over SSH: the TV's name, the weather's place (and with
it the timezone), its unit, and how updates arrive. Any link may change them but the guest one the TV's QR code
shows. Written into config.toml in place, keeping its comments, and checked by config.load before it's replaced."""
import json
import os
import re
import subprocess
import tempfile
import threading
import tomllib
from pathlib import Path

from . import clock, config
from .apps import load_apps

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._'-]{0,29}")  # in YAML, a command line (no leading -) and CEC (ASCII, 14 shown)
UPDATES = ("auto", "notify")  # "off" is for a box someone develops on: config.toml only, so it can't be left off by mistake
lock = threading.RLock()  # one change at a time, from saving to showing it


def render(settings):
    """Write what the file:// home screen reads: the apps and the settings it needs."""
    config.RUN.mkdir(parents=True, exist_ok=True)
    apps = [{k: a[k] for k in ("id", "name", "url", "color")} for a in load_apps(settings)]
    page = {"name": settings.name, "latitude": settings.latitude, "longitude": settings.longitude,
            "temperatureUnit": settings.temperature_unit, "saver": settings.screensaver_minutes * 60}
    (config.RUN / "display-mode").write_text(settings.display_mode)  # for system/kiosk.sh
    (config.RUN / "config.js").write_text(f"window.APPS = {json.dumps(apps)};\nwindow.TENFOOT = {json.dumps(page)};\n")


def toml_value(v):
    return json.dumps(v) if isinstance(v, str) else repr(v)  # a JSON string is a TOML basic string


def edit(text, values):
    """config.toml's text with each key set: its line replaced, else its commented-out example, else added at the end."""
    lines = text.splitlines()
    for key, value in values.items():
        line = f"{key} = {toml_value(value)}"
        for pattern in (rf'\s*"?{key}"?\s*=', rf"#\s*{key}\s*="):
            at = next((n for n, ln in enumerate(lines) if re.match(pattern, ln)), None)
            if at is not None:
                lines[at] = line
                break
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def unset(keys):
    """Take keys out of config.toml (back to their defaults), keeping the rest and its comments."""
    path = config.CONFIG_DIR / "config.toml"
    with lock:
        lines = path.read_text().splitlines()
        keep = [ln for ln in lines if not any(re.match(rf'\s*"?{k}"?\s*=', ln) for k in keys)]
        config.write_private(path, "\n".join(keep) + "\n")


def current(settings):
    return {"name": settings.name, "place": settings.place, "latitude": settings.latitude, "longitude": settings.longitude,
            "unit": settings.temperature_unit, "updates": settings.updates, "timezone": clock.current()}


def checked(cmd):
    """What the phone asked to change, validated: (config values, timezone or None). Raises ValueError for the phone."""
    new, zone = {}, None
    if "name" in cmd:
        name = str(cmd["name"]).strip()
        if not NAME.fullmatch(name):
            raise ValueError("A name of letters, numbers and spaces, up to 30")
        new["name"] = name
    if "weather" in cmd:
        w = cmd["weather"]
        lat, lon = float(w["latitude"]), float(w["longitude"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("That place isn't on Earth")
        new.update(latitude=round(lat, 4), longitude=round(lon, 4), place=str(w.get("place", ""))[:80])
        zone = clock.canonical(w.get("timezone"))  # picking a place sets the clock too, when its zone is a real one
    if "unit" in cmd:
        if cmd["unit"] not in ("celsius", "fahrenheit"):
            raise ValueError("Celsius or Fahrenheit")
        new["temperature_unit"] = cmd["unit"]
    if "updates" in cmd:
        if cmd["updates"] not in UPDATES:
            raise ValueError("Updates are automatic, or ask first")
        new["updates"] = cmd["updates"]
    if not new:
        raise ValueError("Nothing to change")
    return new, zone


def save(new):
    """Write the values into config.toml, after checking the result loads. Returns the new Settings."""
    path = config.CONFIG_DIR / "config.toml"
    with lock:
        text = path.read_text() if path.exists() else (config.ROOT / "config.example.toml").read_text()
        out = edit(text, new)
        fd, tmp = tempfile.mkstemp(dir=config.CONFIG_DIR, suffix=".toml")
        try:
            os.write(fd, out.encode())
            os.close(fd)
            settings = config.load(tmp)
        except (SystemExit, tomllib.TOMLDecodeError) as ex:
            raise ValueError(f"Not saved: {ex}") from None
        finally:
            os.unlink(tmp)
        config.write_private(path, out)
    return settings


def rename_services(name):
    """Spotify Connect and AirPlay show the TV's name too: write their settings again (system/setup-user.sh's way) and
    restart them."""
    def fill(src):
        return (config.ROOT / "system" / src).read_text().replace("@ROOT@", str(config.ROOT)).replace("@NAME@", name)
    spotify = Path.home() / ".config/go-librespot/config.yml"
    airplay = Path.home() / ".config/systemd/user/tenfoot-airplay.service"
    if spotify.exists():
        config.write_private(spotify, fill("go-librespot.yml"))
    if airplay.exists():
        airplay.write_text(fill("tenfoot-airplay.service"))
    subprocess.run(["systemctl", "--user", "daemon-reload"], timeout=30)
    subprocess.run(["systemctl", "--user", "try-restart", "tenfoot-spotify", "tenfoot-airplay"], timeout=60)

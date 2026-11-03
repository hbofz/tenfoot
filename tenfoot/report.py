"""A diagnostic report for the owner to send the developer, from Settings on the phone: versions, health, updates, the
screen, the network type, the TV over HDMI-CEC, and the service's recent log. Only what's listed here is collected, and
the whole text then goes through redact(): link tokens, names, the setup password, Spotify's username, addresses,
URLs (their host is kept) and the tailnet's name come out. Nothing is sent anywhere by the box."""
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time

from . import cec, clock, config, health, links, updates

LIMIT = 1 << 20  # bytes
EVERY = 30  # seconds between two reports
_lock = threading.Lock()
_last = [0.0]


def redact(text, secrets, names=()):
    """text without anything personal: what was listened to, URLs' paths and queries (the host stays), the secrets
    (wherever they appear), the names (as whole words, any case), and anything that looks like an address, an email, a
    password on a command line, a token or a tailnet name."""
    # go-librespot logs each track or episode it plays by name: a household's listening is nobody else's business
    text = re.sub(r'(msg=")(?:loaded |track has narration)[^\n]*', r"\1(a track: left out)", text)
    text = re.sub(r"https?://(?:[^/\s@'\"<>]*@)?([^/\s'\"<>]+)[^\s'\"<>]*", r"<url \1>", text, flags=re.I)  # no user:pass@
    for secret in sorted({x for x in secrets if x and len(x) >= 6}, key=len, reverse=True):
        text = text.replace(secret, "<secret>")
    for name in sorted({n for n in names if n and len(n) >= 3}, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", "<name>", text, flags=re.I)
    for pattern, by in (
            (r"('password',\s*)(['\"])(?:\\.|(?!\2).)*\2", r"\1'<secret>'"),  # a command line in a traceback (nmcli's)
            (r"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b", "<email>"),
            (r"\b[\w.-]+\.ts\.net\b", "<tailnet>"),
            (r"\b(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[\w-]{22,}\b", "<token?>"),  # link tokens are 24 characters
            (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<ip>"),
            (r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", "<mac>")):
        text = re.sub(pattern, by, text, flags=re.I)
    # IPv6: a "::" or at least five colons, so the log's 04:12:33 times stay
    return re.sub(r"(?<![\w:])[0-9a-f:]*:[0-9a-f:]*(?![\w:])",
                  lambda m: "<ip6>" if "::" in m[0] or m[0].count(":") >= 5 else m[0], text, flags=re.I)


def known_secrets(controls):
    """(secrets, names): what redact() must take out, exactly."""
    house = links.load_token()
    people = links.people()
    secrets = [house, links.guest_token(house), *people.values()]
    try:
        secrets.append((config.CONFIG_DIR / "setup-password").read_text().strip())
    except OSError:
        pass
    if controls.spotify:
        try:
            secrets.append(json.loads(controls.spotify.state_file.read_text()).get("credentials", {}).get("username") or "")
        except (OSError, ValueError, AttributeError):
            pass
    s = controls.settings
    names = [*people, *(s.place or "").split(", ")]
    # the TV's own name and the box's host name (on every log line): personal, unless they're the defaults
    names += [n for n in (s.name, socket.gethostname()) if n.lower() not in ("tenfoot", "raspberrypi")]
    return secrets, names


def read(path):
    try:
        return open(path).read().replace("\0", "").strip()
    except OSError as ex:
        return f"({ex.strerror})"


def section(make):
    """One part of the report: whatever goes wrong making it (a hung compositor, a missing file) is said, not fatal."""
    try:
        return make()
    except Exception as ex:
        return f"(couldn't: {ex!r})"


def hardware():
    meminfo = dict(line.split(":", 1) for line in read("/proc/meminfo").splitlines() if ":" in line)
    disk = shutil.disk_usage("/")
    m = lambda k: meminfo.get(k, "?").strip()
    return (f"throttled 0x{health.throttle_bits(health.run('vcgencmd', 'get_throttled')):x}\n"
            f"temperature {section(lambda: f'{int(read_raw('/sys/class/thermal/thermal_zone0/temp')) / 1000:.0f} C')}\n"
            f"disk {disk.free >> 20} MB free of {disk.total >> 20} MB\n"
            f"memory {m('MemAvailable')} available of {m('MemTotal')}, swap {m('SwapFree')} free of {m('SwapTotal')}")


def read_raw(path):
    with open(path) as f:
        return f.read().strip()


def build(controls):
    s = controls.settings
    os_name = lambda: next(ln.split("=", 1)[1].strip('"') for ln in read("/etc/os-release").splitlines() if ln.startswith("PRETTY_NAME="))
    wifi = lambda: "\n".join(f"wifi signal {w.split(':')[1]}%, {w.split(':')[2]}" for w in health.run(
        "nmcli", "-t", "-f", "IN-USE,SIGNAL,FREQ", "dev", "wifi", "list", "--rescan", "no").splitlines() if w.startswith("*:"))
    screen = lambda: "\n".join(ln for ln in subprocess.run(["wlr-randr"], capture_output=True, text=True, timeout=15,
                                                           env=dict(os.environ, WAYLAND_DISPLAY="wayland-0")).stdout.splitlines()
                               if "Serial" not in ln) or "(nothing)"
    journal = lambda *args: health.run("journalctl", "--user", *args, "-o", "short-iso", "--no-pager")
    parts = {
        "Tenfoot": lambda: "\n".join([f"version {(config.ROOT / 'VERSION').read_text().strip()}",
                                      f"browser {section(lambda: controls.browser.version().get('Browser', '?'))}",
                                      read("/proc/device-tree/model"), section(os_name), f"kernel {os.uname().release}",
                                      f"uptime {float(read_raw('/proc/uptime').split()[0]) / 3600:.1f} h"]),
        "Health": lambda: "\n".join(f"{p['title']}: {p['detail']}" for p in health.status()) or "all good",
        "Hardware": hardware,
        "Updates": lambda: json.dumps(updates.status(), indent=1) + "\n" + read("/var/lib/tenfoot-update/status.json"),
        "Settings": lambda: "\n".join([*(f"{k} = {getattr(s, k)!r}" for k in ("remote_mode", "display_mode", "updates", "spotify",
                                                                              "temperature_unit", "screensaver_minutes", "standby_hours")),
                                       f"weather set: {s.latitude is not None}", f"jellyfin set: {bool(s.jellyfin_url)}",
                                       f"personal links: {len(links.people())}", f"timezone {clock.current()}"]),
        "Screen": screen,
        "Network": lambda: health.run("nmcli", "-t", "-f", "TYPE,STATE", "dev") + section(wifi),
        "TV over HDMI-CEC": lambda: f"adapter {cec.connected_device()[0] or 'none'}, TV power {getattr(controls.tv, 'power', None)}, "
                                    f"showing this input {getattr(controls.tv, 'showing', None)}",
        "Log, this boot": lambda: journal("-u", "tenfoot", "-u", "tenfoot-spotify", "-b", "-n", "1500"),
        "Log, the boot before": lambda: journal("-u", "tenfoot", "-b", "-1", "-n", "300"),
        "Boots": lambda: "\n".join(journal("--list-boots").splitlines()[-10:]),
    }
    secrets = known_secrets(controls)  # not in section(): if these can't be read, there's no report (never one unredacted)
    text = f"Tenfoot diagnostic report, {time.strftime('%Y-%m-%d %H:%M %Z')}\n\n" + "".join(
        f"== {name} ==\n{section(make).strip()}\n\n" for name, make in parts.items())
    text = redact(text, *secrets)
    return text if len(text) <= LIMIT else text[:LIMIT] + "\n(cut short)\n"


def get(controls):
    """The report, or None if one is being made or was made less than EVERY seconds ago."""
    if not _lock.acquire(blocking=False):
        return None
    try:
        if time.monotonic() - _last[0] < EVERY:
            return None
        _last[0] = time.monotonic()
        try:
            return build(controls)
        except Exception:
            _last[0] = 0.0  # it failed: trying again straight away is fine
            raise
    finally:
        _lock.release()

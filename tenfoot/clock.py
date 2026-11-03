"""The box's timezone, and whether its clock can be trusted yet.

The timezone comes from the first phone that connects (its browser knows where it is): during Wi-Fi setup, or the
first time the remote opens. Only once, so a guest's phone or one on a trip doesn't move the TV's clock;
`tenfoot timezone ZONE` still changes it on purpose. A Pi has no clock battery: until it syncs over the network, the
time is wherever it was at the last shutdown."""
import os
import re
import subprocess
import time
from pathlib import Path

from .config import CONFIG_DIR

ZONEINFO = Path("/usr/share/zoneinfo")
NAME = re.compile(r"[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+){0,2}")
# What privacy-minded browsers report wherever they are: not worth using up the first phone's say on.
NO_GUESS = re.compile(r"(Etc/.*|UTC|GMT|Atlantic/Reykjavik)")


def mark():
    return CONFIG_DIR / "timezone-set"


def canonical(tz):
    """A browser's zone name as this box knows it, or None. Only names tzdata lists count: a zone ("Z name") or an
    old alias ("L Asia/Kolkata Asia/Calcutta"), never other files in zoneinfo (localtime there links back to
    /etc/localtime: setting it would loop the clock)."""
    if not isinstance(tz, str) or not NAME.fullmatch(tz):
        return None
    try:
        for line in (ZONEINFO / "tzdata.zi").read_text().splitlines():
            p = line.split()
            if len(p) >= 2 and p[0] == "Z" and p[1] == tz:
                zone = tz
                break
            if len(p) == 3 and p[0] == "L" and p[2] == tz:
                zone = p[1]
                break
        else:
            return None
    except OSError:
        return None
    return zone if (ZONEINFO / zone).is_file() else None


def current():
    """The box's zone: /etc/localtime links to it."""
    try:
        return os.readlink("/etc/localtime").split("zoneinfo/", 1)[1]
    except (OSError, IndexError):
        return None


def set_zone(tz):
    """Set the box's zone (polkit lets the TV's user do this one thing). Returns the zone set, or raises."""
    zone = canonical(tz)
    if not zone:
        raise ValueError(f"unknown timezone {tz!r}")
    if zone != current():
        subprocess.run(["timedatectl", "set-timezone", zone], check=True, timeout=30, capture_output=True)
        print(f"clock: timezone {zone}", flush=True)
    time.tzset()  # this process keeps the old zone otherwise (Chromium watches /etc/localtime by itself)
    return zone


def adopt(tz):
    """The first phone's zone; later ones are ignored. Never raises: a phone's guess mustn't break what it came for."""
    if not isinstance(tz, str) or NO_GUESS.fullmatch(tz):
        return None
    try:
        # ponytail: a power cut between claiming and setting leaves an empty claim; `tenfoot timezone` fixes that
        fd = os.open(mark(), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)  # claimed first, so two at once can't both win
    except OSError:
        return None  # already set (or nowhere to remember it: then never guess)
    try:
        zone = set_zone(tz)
        os.write(fd, (zone + "\n").encode())
        return zone
    except Exception as ex:
        mark().unlink(missing_ok=True)  # a bad guess doesn't count
        print(f"clock: not adopting {tz!r}: {ex}", flush=True)
        return None
    finally:
        os.close(fd)


def synced():
    """Has the clock synced over the network? The kernel knows, whichever NTP client set it."""
    try:
        out = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], capture_output=True, text=True,
                             timeout=10).stdout
        return out.strip() == "yes"
    except (OSError, subprocess.SubprocessError):
        return False

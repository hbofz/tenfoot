"""Which mode to run the TV in. 1080p at 60 is what the Pi 4 decodes and draws best, but not every screen lists it
exactly: a 720p TV has no 1080p at all, many panels list 59.94 Hz (wlr-randr prints 59.939999, and wants the refresh
spelled to match), and a 4K TV prefers 4K at 30 Hz, which makes everything choppy. So pick from what the TV lists.

  python3 -m tenfoot.display    prints the mode to use, from wlr-randr in the kiosk (system/kiosk.sh calls it)"""
import os
import re
import subprocess

MODE = re.compile(r"^\s+(\d+)x(\d+) px, ([\d.]+) Hz(?: \(([^)]*)\))?", re.M)


def modes(wlr_randr_output):
    """The first output's modes: [(width, height, millihertz, flags)], as wlr-randr lists them."""
    # ponytail: the first output, as the kiosk only ever drives one; a box with two heads and the first switched off
    # would need "Enabled: yes" picked here and in system/kiosk.sh
    first = re.split(r"\n(?=\S)", wlr_randr_output.strip())[0]
    return [(int(w), int(h), round(float(hz) * 1000), flags or "") for w, h, hz, flags in MODE.findall(first)]


def spell(m):
    return f"{m[0]}x{m[1]}@{m[2] / 1000:.3f}"  # 59.940 matches what wlr-randr lists as 59.939999


def choose(wlr_randr_output, want="auto"):
    """The mode to use ("1920x1080@60.000"), or None if the TV lists nothing usable. want: "auto", or a mode from
    config.toml ("1280x720@60"), used if the TV lists it (59.94 counts as 60, 50 doesn't)."""
    ms = modes(wlr_randr_output)
    ok = [m for m in ms if m[1] <= 1080 and m[2] <= 60100]  # what the Pi draws smoothly
    if want != "auto":
        size, _, hz = want.partition("@")  # "1920x1080" alone: that size, at its best refresh up to 60
        w, h = map(int, size.split("x"))
        listed = [m for m in ms if (m[0], m[1]) == (w, h) and (abs(m[2] - float(hz) * 1000) <= 100 if hz else m[2] <= 60100)]
        if listed:
            return spell(min(listed, key=lambda m: abs(m[2] - float(hz) * 1000)) if hz else max(listed, key=lambda m: m[2]))
    full_hd = [m for m in ok if m[:2] == (1920, 1080)]
    pick = (max(full_hd, key=lambda m: m[2]) if full_hd else next((m for m in ok if "preferred" in m[3]), None)
            or max(ok, key=lambda m: (m[0] * m[1], m[2]), default=None))
    return pick and spell(pick)


def current(wlr_randr_output):
    m = next((m for m in modes(wlr_randr_output) if "current" in m[3]), None)
    return m and spell(m)


def wlr_randr():
    env = dict(os.environ, WAYLAND_DISPLAY=os.environ.get("WAYLAND_DISPLAY", "wayland-0"))
    return subprocess.run(["wlr-randr"], capture_output=True, text=True, env=env, timeout=10).stdout


if __name__ == "__main__":
    from . import config
    print(choose(wlr_randr(), config.load().display_mode) or "")

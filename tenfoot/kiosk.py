"""Keeps the kiosk healthy: the right display mode, and a browser that answers."""
import getpass
import glob
import os
import re
import signal
import subprocess
import time
from pathlib import Path

from . import display
from .config import CHROMIUM_PROFILE

CHECK_EVERY, MISSES = 30, 3
# What to do about a page that doesn't answer, in order, each a number of seconds after the one before (the first:
# after the page stopped answering). A declined reboot is asked for again after the same wait.
STEPS = (("chromium", (MISSES - 1) * CHECK_EVERY), ("cage", 60), ("reboot", 180))
last_beat = time.monotonic()  # each round of the watchdog: the service's own liveness check reads it


def pin_display(want):
    """TVs advertise 4K, and after every HDMI replug (TV off and on, input switches) the compositor
    picks it again: 4x the pixels at 30 Hz, and everything on screen turns choppy. Put it back, to the
    best mode the TV lists (tenfoot/display.py): want is display_mode, "auto" or one asked for."""
    env = dict(os.environ, WAYLAND_DISPLAY="wayland-0")  # the kiosk's cage on tty1
    out = subprocess.run(["wlr-randr"], capture_output=True, text=True, env=env, timeout=10).stdout
    name = re.search(r"^(\S+) ", out, re.M)
    mode = display.choose(out, want)
    if name and mode and display.current(out) != mode:
        if subprocess.run(["wlr-randr", "--output", name.group(1), "--mode", mode], env=env, timeout=10).returncode == 0:
            print(f"display: back to {mode}", flush=True)


class Escalation:
    """Where a dead page's recovery has got to: restart Chromium; if that didn't bring it back, the compositor (cage)
    too, which the kiosk loop restarts; and as a last resort, the whole box."""

    def __init__(self):
        self.answered()

    def answered(self):
        self.dead_since = self.last = None
        self.done = 0

    def due(self, now):
        """The step to take now about a page that didn't answer, or None."""
        if self.dead_since is None:
            self.dead_since = now
        name, wait = STEPS[min(self.done, len(STEPS) - 1)]
        return name if now - (self.last or self.dead_since) >= wait else None

    def did(self, now):
        self.done, self.last = self.done + 1, now  # past the last step, it repeats (a reboot that didn't happen)

    def declined(self, now):
        self.last = now  # the same step, after the same wait again


def restart_chromium(profile):
    pid = subprocess.run(["pgrep", "-o", "-f", "--", f"--user-data-dir={profile}"], capture_output=True, text=True,
                         timeout=10).stdout.strip()
    if not pid:
        return  # not running at all: the kiosk loop is already starting one
    print("kiosk: page not answering, restarting Chromium", flush=True)
    pid = int(pid)
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):  # a hung browser may ignore TERM
            time.sleep(0.5)
            os.kill(pid, 0)
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # gone


def restart_cage():
    print("kiosk: still nothing after restarting Chromium, restarting the compositor", flush=True)
    subprocess.run(["pkill", "-KILL", "-x", "cage"], timeout=10)


def hdmi_connected():
    return any(Path(f).read_text().strip() == "connected" for f in glob.glob("/sys/class/drm/card*-HDMI-A-*/status"))


def request_reboot():
    """The last resort, asked of root's tenfoot-update reboot-stuck, which decides (not within an hour of starting,
    not during an update, not while someone's logged in). Only on the TV box, and only with a TV plugged in: with none,
    there's no picture to bring back. True if the box is rebooting."""
    if getpass.getuser() != "tenfoot" or not hdmi_connected():
        print("kiosk: still nothing, but no TV is connected: not rebooting", flush=True)
        return False
    print("kiosk: still nothing after restarting the compositor, asking to reboot", flush=True)
    return subprocess.run(["systemctl", "start", "tenfoot-reboot-stuck.service"], timeout=120).returncode == 0


def watchdog(browser, settings):
    """Chromium can freeze, or lose its page to a crash, while its process lives on, and the kiosk
    loop only starts a new one when it exits. So ask the page for a trivial answer every CHECK_EVERY
    seconds, and when it stops answering, escalate (Escalation). A page busy playing video still answers."""
    # ponytail: checks the page's main thread only. A frozen GPU with a live page needs a
    # requestAnimationFrame probe, which also stalls while the TV is off; add it with that guard.
    global last_beat
    profile = os.path.expanduser(CHROMIUM_PROFILE)
    esc = Escalation()
    while True:
        time.sleep(CHECK_EVERY)
        last_beat = time.monotonic()
        try:
            pin_display(settings.display_mode)
        except Exception as ex:
            print("display:", ex, flush=True)
        try:
            browser.evaluate("1")
            esc.answered()
            continue
        except Exception:
            pass
        now = time.monotonic()
        step = esc.due(now)
        if not step:
            continue
        try:
            ok = request_reboot() if step == "reboot" else restart_chromium(profile) if step == "chromium" else restart_cage()
        except Exception as ex:  # a step that went wrong still counts as tried; a reboot is asked for again
            print(f"kiosk: {step} failed: {ex!r}", flush=True)
            ok = step != "reboot"
        if ok is False:
            esc.declined(now)
        else:
            esc.did(now)

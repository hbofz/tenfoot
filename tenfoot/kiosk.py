"""Keeps the kiosk healthy: the right display mode, and a browser that answers."""
import os
import re
import signal
import subprocess
import time

from .config import CHROMIUM_PROFILE

CHECK_EVERY, MISSES = 30, 3


def current_mode_ok(wlr_randr_output, mode):
    """Is the screen on mode ('1920x1080@60')? wlr-randr marks it "(current)" or "(preferred, current)"."""
    size, hz = mode.split("@")
    return bool(re.search(rf"{size} px, {hz}\.0+ Hz \([^)]*current", wlr_randr_output))


def pin_display(mode):
    """TVs advertise 4K, and after every HDMI replug (TV off and on, input switches) the compositor
    picks it again: 4x the pixels at 30 Hz, and everything on screen turns choppy. Put it back."""
    env = dict(os.environ, WAYLAND_DISPLAY="wayland-0")  # the kiosk's cage on tty1
    out = subprocess.run(["wlr-randr"], capture_output=True, text=True, env=env, timeout=10).stdout
    name = re.search(r"^(\S+) ", out, re.M)
    if name and not current_mode_ok(out, mode):
        if subprocess.run(["wlr-randr", "--output", name.group(1), "--mode", mode], env=env, timeout=10).returncode == 0:
            print(f"display: back to {mode}", flush=True)


def watchdog(browser, settings):
    """Chromium can freeze, or lose its page to a crash, while its process lives on, and the kiosk
    loop only starts a new one when it exits. So ask the page for a trivial answer every CHECK_EVERY
    seconds; after MISSES in a row, stop Chromium and the loop brings up a fresh one on the home
    screen. A page busy playing video still answers."""
    # ponytail: checks the page's main thread only. A frozen GPU with a live page needs a
    # requestAnimationFrame probe, which also stalls while the TV is off; add it with that guard.
    misses = 0
    profile = os.path.expanduser(CHROMIUM_PROFILE)
    while True:
        time.sleep(CHECK_EVERY)
        try:
            pin_display(settings.display_mode)
        except Exception as ex:
            print("display:", ex, flush=True)
        try:
            browser.evaluate("1")
            misses = 0
            continue
        except Exception:
            misses += 1
        if misses < MISSES:
            continue
        misses = 0
        pid = subprocess.run(["pgrep", "-o", "-f", "--", f"--user-data-dir={profile}"], capture_output=True, text=True).stdout.strip()
        if not pid:
            continue  # not running at all: the kiosk loop is already starting one
        print(f"kiosk: page not answering for {CHECK_EVERY * MISSES}s, restarting Chromium", flush=True)
        pid = int(pid)
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):  # a hung browser may ignore TERM
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
        else:
            os.kill(pid, signal.SIGKILL)

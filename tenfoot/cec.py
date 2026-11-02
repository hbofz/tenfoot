"""The TV, over HDMI-CEC: power, knowing when it's on our input, and its remote's keys."""
import glob
import os
import re
import select
import subprocess
import time

from evdev import InputDevice, ecodes, list_devices

from .apps import page_url
from .kiosk import pin_display

# Keys from a physical remote: over CEC the kernel turns them into keys on the vc4-hdmi-N input
# devices; a Bluetooth or USB remote is listed in settings.remote_devices.
REMOTE_KEYS = {
    "KEY_UP": {"a": "key", "k": "up"}, "KEY_DOWN": {"a": "key", "k": "down"},
    "KEY_LEFT": {"a": "key", "k": "left"}, "KEY_RIGHT": {"a": "key", "k": "right"},
    "KEY_OK": {"a": "key", "k": "ok"}, "KEY_SELECT": {"a": "key", "k": "ok"}, "KEY_ENTER": {"a": "key", "k": "ok"},
    "KEY_EXIT": {"a": "back"}, "KEY_ESC": {"a": "back"}, "KEY_BACK": {"a": "back"},
    "KEY_ROOT_MENU": {"a": "home"}, "KEY_MENU": {"a": "home"}, "KEY_HOME": {"a": "home"}, "KEY_HOMEPAGE": {"a": "home"},
    "KEY_PLAYCD": {"a": "key", "k": "playpause"}, "KEY_PAUSECD": {"a": "key", "k": "playpause"},
    "KEY_PLAYPAUSE": {"a": "key", "k": "playpause"},
    "KEY_KPPLUS": {"a": "tv", "k": "volup"}, "KEY_KPMINUS": {"a": "tv", "k": "voldown"}, "KEY_KPASTERISK": {"a": "tv", "k": "mute"},
    "KEY_VOLUMEUP": {"a": "tv", "k": "volup"}, "KEY_VOLUMEDOWN": {"a": "tv", "k": "voldown"}, "KEY_MUTE": {"a": "tv", "k": "mute"},
    "KEY_F8": {"a": "cursor"},
}
REPEATS = {"KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT", "KEY_KPPLUS", "KEY_KPMINUS", "KEY_VOLUMEUP", "KEY_VOLUMEDOWN"}
ARROWS = {"KEY_LEFT": "left", "KEY_RIGHT": "right", "KEY_UP": "up", "KEY_DOWN": "down"}


def phys_addr(cec_ctl_output):
    """'Physical Address : 1.0.0.0' from `cec-ctl -d /dev/cecN`, or None when unplugged."""
    for line in cec_ctl_output.splitlines():
        if line.strip().startswith("Physical Address"):
            pa = line.split(":", 1)[1].strip()
            return None if pa == "f.f.f.f" else pa
    return None


def parse_power(out):
    """'pwr-state: standby (0x01)' from `cec-ctl --give-device-power-status` -> 'standby'."""
    for line in out.splitlines():
        if "pwr-state:" in line:
            return line.split(":", 1)[1].split()[0]
    return None


def route_event(st, line):
    """One line of `cec-follower -v` -> updated state, and True when this box should announce itself
    as the active source. The TV only sends remote buttons to the active source, and it asks for
    our input (SET_STREAM_PATH) while switching inputs has us briefly unregistered, so the answer
    has to wait until we have our logical address back."""
    line = line.strip()
    # "TV to all (0 to 15): ..." (cec-ctl -M prefixes "Received from"); our own sends say "Transmitted"
    if not line.startswith("Transmitted") and re.search(r"\(\d+ to \d+\): ", line):
        st["msg"] = next((m for m in ("SET_STREAM_PATH", "ROUTING_CHANGE", "ACTIVE_SOURCE") if m in line), None)
        return False
    if "Event: State Change: PA:" in line:
        pa = line.split("PA:")[1].split(",")[0].strip()
        st["claimed"] = not line.rstrip().endswith("0x0000")
        if pa == "f.f.f.f":
            st["hpd"] = time.monotonic()
        else:
            st["pa"] = pa
            # Switching to this input the TV drops hotplug for about a second and says nothing else:
            # too weak a sign to grab the screen on. A long drop is the TV unplugged or rebooting,
            # which comes back on its own home screen.
            if isinstance(st.get("hpd"), float) and time.monotonic() - st["hpd"] < 5:
                st["hpd"], st["want"] = "switched", True
        return st["claimed"] and st.get("want", False) and st.get("hpd") != "switched"
    key = {"SET_STREAM_PATH": "phys-addr:", "ROUTING_CHANGE": "new-phys-addr:", "ACTIVE_SOURCE": "phys-addr:"}.get(st.get("msg"))
    if key and line.startswith(key):
        target, msg = line.split(":", 1)[1].strip(), st.pop("msg")
        ours = target == st.get("pa")
        st.pop("hpd", None)
        if msg == "ACTIVE_SOURCE":
            if not ours:
                st["want"] = False  # someone else (the TV's own apps, another input) is showing
            return False
        st["want"] = ours
        return ours and st.get("claimed", False)
    return False


def _ctl(dev, *args):
    return subprocess.run(["cec-ctl", "-d", dev, *args], capture_output=True, text=True, timeout=10)


def connected_device():
    """(/dev/cecN, physical address) of the port the TV is on, or (None, None)."""
    for dev in sorted(glob.glob("/dev/cec*")):
        pa = phys_addr(_ctl(dev).stdout)
        if pa:
            return dev, pa
    return None, None


class TV:
    def __init__(self, settings, browser, on_off=lambda: None):
        self.settings, self.browser, self.on_off = settings, browser, on_off
        self.power = None  # "on", "standby"... as power_loop last heard it

    def set_power(self, k):
        dev, pa = connected_device()
        if not dev:
            raise ValueError("the TV isn't connected over HDMI (or its CEC setting is off)")
        # "on" wakes the TV and switches it to our input.
        args = ["--to", "0", "--image-view-on", "--active-source", f"phys-addr={pa}"] if k == "on" else ["--to", "0", "--standby"]
        subprocess.run(["cec-ctl", "-d", dev, *args], capture_output=True, timeout=10, check=True)

    def power_loop(self):
        """TV off -> pause the music and park the browser on a black page, so nothing plays to a dark
        screen and the GPU idles. TV back on -> home screen. Asks every 20 s; two "standby" answers in a
        row count as off (one can be a hiccup). Only flips once the page really changed, so a failed
        switch is retried next round (a missed wake would leave the TV on the black page)."""
        asleep, offs = False, 0
        while True:
            time.sleep(20)
            try:
                dev, _ = connected_device()
                if not dev:
                    continue  # TV unplugged: change nothing
                self.power = parse_power(_ctl(dev, "--to", "0", "--give-device-power-status").stdout)
                offs = offs + 1 if self.power in ("standby", "to-standby") else 0
                if offs >= 2 and not asleep:
                    self.on_off()
                    self.browser.navigate(page_url("sleep.html"))
                    asleep = True
                    print("tv: off, parked", flush=True)
                elif self.power == "on" and asleep:
                    pin_display(self.settings.display_mode)  # the TV coming back on was an HDMI replug
                    self.browser.navigate(page_url("home.html"))
                    asleep = False
                    print("tv: on, home", flush=True)
            except subprocess.TimeoutExpired:
                pass  # TV not answering: change nothing
            except Exception as ex:
                print("tv:", ex, flush=True)

    def route_loop(self, dev):
        """One HDMI port: register as a playback device, run cec-follower (it answers the TV's questions and,
        with -v, prints what it hears; unlike cec-ctl's monitor mode that needs no root), and claim
        active source when the TV picks this input."""
        while True:
            _ctl(dev, "--playback", "--osd-name", self.settings.name[:14])
            pa = phys_addr(_ctl(dev).stdout)
            st = {"pa": pa, "claimed": bool(pa)}
            # stdbuf: line-buffered, or a pipe gets its output in 4KB lumps long after the fact
            mon = subprocess.Popen(["stdbuf", "-oL", "cec-follower", "-d", dev, "-v"], stdout=subprocess.PIPE, text=True)
            try:
                for line in mon.stdout:
                    if route_event(st, line):
                        time.sleep(0.3)
                        _ctl(dev, "--active-source", f"phys-addr={st['pa']}", "--to", "0", "--menu-status", "menu-state=activated")
                        print(f"cec: {dev} announced active source {st['pa']}", flush=True)
            finally:
                mon.kill()  # never leave a second follower on the adapter when this loop is restarted
                mon.wait()
            time.sleep(3)  # follower exited (adapter hiccup); start over


def key_names(name):
    """evdev names a code one string or, when it has aliases, several: 113 is (KEY_MIN_INTERESTING, KEY_MUTE)."""
    return [name] if isinstance(name, str) else list(name)


def remote_command(names, value):
    """evdev key name(s) + value (1 press, 2 repeat, 0 release) -> remote command or None."""
    for name in key_names(names):
        if name in REMOTE_KEYS and (value == 1 or (value == 2 and name in REPEATS)):
            return REMOTE_KEYS[name]
    return None


def newest_repeats(keys):
    """A held key's repeats pile up while a slow command (volume) runs; keep only the newest
    repeat of each key, or the volume keeps stepping long after the button is let go."""
    return [e for i, e in enumerate(keys)
            if e.value != 2 or not any(f.code == e.code and f.value == 2 for f in keys[i + 1:])]


def remote_keys_loop(controls, patterns):
    """Grab the physical remotes' input devices (so raw keys never reach the browser twice) and
    translate their keys. A Bluetooth remote comes and goes, so look for one 4 times a second:
    until it's grabbed, a freshly reconnected remote's keys reach the browser raw."""
    devices = {}
    wanted = re.compile("|".join(patterns))
    cursor = controls.cursor
    while True:
        for path in set(list_devices()) - set(devices):
            try:
                with open(f"/sys/class/input/{os.path.basename(path)}/device/name") as f:
                    if not wanted.fullmatch(f.read().strip()):
                        continue
                d = InputDevice(path)
                d.grab()
                devices[path] = d
                print("remote: listening on", d.name, flush=True)
            except OSError:
                pass  # vanished while we looked
        for d in select.select(list(devices.values()), [], [], 0.25)[0]:
            try:
                events = list(d.read())  # read() is a generator: it raises while iterating
            except OSError:  # a Bluetooth remote disconnected
                print("remote: lost", d.name, flush=True)
                devices.pop(d.path)
                cursor.held.clear()  # its key releases went with it: no gliding on
                continue
            for ev in newest_repeats([e for e in events if e.type == ecodes.EV_KEY]):
                names = key_names(ecodes.KEY.get(ev.code, ""))
                arrow = next((ARROWS[n] for n in names if n in ARROWS), None)
                if cursor.on and arrow:  # the cursor glides from press to release
                    if ev.value != 2:
                        cursor.glide(arrow, ev.value == 1)
                    continue
                cmd = remote_command(names, ev.value)
                if cmd:
                    try:
                        controls.handle(cmd)
                    except Exception as ex:
                        print("remote:", cmd, "failed:", ex, flush=True)

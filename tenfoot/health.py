"""What's wrong with the box that its owner can fix, or should know: power, heat, storage, internet, Wi-Fi signal.
A worker checks every minute (the internet every five, sooner after a failure); the TV and phone read the result."""
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

from . import setup

DOH = "https://dns.adguard-dns.com/dns-query"  # Chromium's DNS (system/chromium-policy.json): if it's blocked, no site loads
EVERY, NET_EVERY = 60, 300
LOW_DISK = 1 << 30  # system/kiosk.sh clears Chromium's caches below this too
HOT_C, WEAK_SIGNAL, WEAK_TIMES, NET_FAILS = 80, 30, 3, 2

_lock = threading.Lock()
_now = []  # the problems found last time round


def throttle_bits(out):
    """`vcgencmd get_throttled` -> its bits ('throttled=0x50000' -> 0x50000), or 0 when unreadable."""
    try:
        return int(out.strip().split("=")[1], 16)
    except (IndexError, ValueError):
        return 0


def problems(bits, temp_c, free, readonly, net, weak):
    """The problems to show, as {title, detail}, worst first. net: "ok" | "down" | "dns" (only secure DNS fails)."""
    out = []
    if readonly:
        out.append(("The storage card is failing", "Tenfoot can't save anything. Put a fresh image on a new card."))
    if bits & 0x10001:  # under-voltage now, or since it started (it comes and goes while video plays)
        out.append(("The power supply is too weak", "Use the official Raspberry Pi 5.1 V 3 A USB-C power supply."))
    if temp_c >= HOT_C or (bits & 0xC and not bits & 0x1):
        out.append(("Tenfoot is too hot", "It's slowing down to cool off. Give it room to breathe, or use a case with a fan."))
    if free < LOW_DISK:
        out.append(("Storage is almost full", "Restart Tenfoot to clear space. If this keeps happening, use a bigger card."))
    if net == "down":
        out.append(("Connected, but no internet", "Restart your router, or check that the internet works on your phone."))
    elif net == "dns":
        out.append(("Websites won't load on this network", "It blocks Tenfoot's secure DNS. Try a different network."))
    if weak:
        out.append(("Weak Wi-Fi signal", "Videos may stutter. Move Tenfoot closer to the router, or use an Ethernet cable."))
    return [{"title": t, "detail": d} for t, d in out]


def run(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def reaches(url):
    try:
        urllib.request.urlopen(url, timeout=10).close()
    except urllib.error.HTTPError:
        pass  # it answered (a DNS-over-HTTPS endpoint says 400 to a bare GET)
    except Exception:
        return False
    return True


def internet():
    """"ok", "down", or "dns" (the internet works, but the secure DNS the browser needs is blocked)."""
    if reaches(DOH):
        return "ok"
    try:
        socket.getaddrinfo("example.com", 443)
        return "dns" if reaches("https://example.com/") else "down"
    except OSError:
        return "down"


def status():
    with _lock:
        return list(_now)


def loop():
    """Look every EVERY seconds. Brief blips don't count: the internet must fail NET_FAILS times running (rechecked a
    minute after a failure), the signal be weak WEAK_TIMES times running."""
    global _now
    fails = weak = 0
    net, net_at = "ok", -NET_EVERY  # the first check at once
    while True:
        devices = run("nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "dev")
        online = setup.has_network(devices)
        if not online:
            fails, net = 0, "ok"  # no network at all: that's the Wi-Fi setup screen's job
        elif time.monotonic() - net_at >= (EVERY if fails else NET_EVERY):
            net_at = time.monotonic()
            result = internet()
            fails = fails + 1 if result != "ok" else 0
            net = result if fails >= NET_FAILS else "ok" if not fails else net
        signal = [ln.split(":")[1] for ln in run("nmcli", "-t", "-f", "IN-USE,SIGNAL", "dev", "wifi", "list", "--rescan", "no").splitlines()
                  if ln.startswith("*:")]  # --rescan no: a scan makes the Pi's Wi-Fi stutter
        wired = any(ln.startswith("ethernet:connected") for ln in devices.splitlines())  # then Wi-Fi isn't what's used
        weak = weak + 1 if online and not wired and signal and signal[0].isdigit() and int(signal[0]) < WEAK_SIGNAL else 0
        try:
            temp = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
        except (OSError, ValueError):
            temp = 0
        st = os.statvfs("/")
        found = problems(throttle_bits(run("vcgencmd", "get_throttled")), temp, st.f_bavail * st.f_frsize,
                         bool(st.f_flag & os.ST_RDONLY), net, weak >= WEAK_TIMES)
        with _lock:
            if found != _now:
                print("health:", "; ".join(p["title"] for p in found) or "all good", flush=True)
            _now = found
        time.sleep(EVERY)

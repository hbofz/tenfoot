"""python3 -m tenfoot [serve | render | links | link NAME | revoke NAME | timezone [ZONE]]"""
import glob
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

from . import browser, cec, clock, config, health, idle, kiosk, links, server, setup, spotify, watcher
from .apps import load_apps
from .settings import render
from .controls import Controls
from .inputs import Input


def forever(loop, *args):
    """Run a worker for good: if it crashes (say an HDMI replug breaks the CEC devices), log why
    and start it again, instead of that feature silently dying until the next reboot."""
    while True:
        try:
            loop(*args)
        except Exception as ex:
            print(f"{loop.__name__} crashed: {ex!r}; restarting it", flush=True)
        time.sleep(5)


def qr_loop(settings, house):
    """Keep the TV's QR code right: phones find this box by its address, which can change."""
    last = None
    while True:
        try:
            url = links.link_url(settings, links.guest_token(house))
            if url != last or not (config.RUN / "remote-qr.svg").exists():
                links.write_qr(settings, house)
                last = url
        except OSError:
            pass  # no network right now: the QR code waits for one
        time.sleep(5)


def notify(msg):
    """Tell systemd something (sd_notify, without the library): the service's unit sets NOTIFY_SOCKET."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
        s.connect("\0" + addr[1:] if addr[0] == "@" else addr)
        s.sendall(msg.encode())
    return True


def alive_loop():
    """systemd restarts this service when it stops hearing "alive" for WatchdogSec (tenfoot.service): said only
    while the home screen's local API answers and the kiosk watchdog keeps going round, so a deadlock or a stuck
    thread restarts the service instead of leaving the TV without a remote."""
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{config.LOCAL_PORT}/setup", timeout=10):
                pass
            if time.monotonic() - kiosk.last_beat < 4 * kiosk.CHECK_EVERY:
                notify("WATCHDOG=1")
        except Exception as ex:
            print("alive: not answering:", ex, flush=True)
        time.sleep(20)


def serve(settings):
    render(settings)
    house = links.load_token()
    cdp = browser.Browser(config.CDP_PORT)
    music = spotify.Spotify(cdp) if settings.spotify else None
    pause = music.pause if music else lambda: None
    tv = cec.TV(settings, cdp, on_off=pause)
    controls = Controls(Input(*settings.screen), cdp, settings, load_apps(settings), tv=tv, spotify=music)
    script = watcher.injected_script(settings.jellyfin_url)
    workers = [(cec.remote_keys_loop, controls, settings.remote_devices),
               (watcher.run, cdp, script, settings.jellyfin_url, pause),
               (tv.power_loop,), (kiosk.watchdog, cdp, settings), (qr_loop, settings, house),
               *[(tv.route_loop, dev) for dev in sorted(glob.glob("/dev/cec*"))]]
    wifi_setup = setup.Setup(cdp)
    server.Local.wifi_setup = wifi_setup
    workers.append((wifi_setup.watch,))
    if music:
        music.lyrics_offset()  # (re)write the TV screen's copy of the lyrics timing
        workers.append((music.watch_logins,))
    workers.append((alive_loop,))
    workers.append((health.loop,))
    workers.append((idle.loop, cdp, tv, music, settings))
    for loop, *args in workers:
        threading.Thread(target=forever, args=(loop, *args), daemon=True).start()
    local = ThreadingHTTPServer(("127.0.0.1", config.LOCAL_PORT), server.Local)
    threading.Thread(target=local.serve_forever, daemon=True).start()
    ThreadingHTTPServer((settings.listen_host, settings.remote_port), server.remote_handler(controls, house)).serve_forever()


def main(args):
    settings = config.load()
    if not args or args == ["serve"]:
        serve(settings)
    elif args == ["render"]:
        render(settings)
    elif args[0] in ("links", "link", "revoke"):
        links.cli(settings, args)
    elif args == ["timezone"]:
        print(clock.current())
    elif len(args) == 2 and args[0] == "timezone":
        try:
            zone = clock.set_zone(args[1])
        except (ValueError, OSError, subprocess.SubprocessError) as ex:
            sys.exit(f"{ex} {getattr(ex, 'stderr', '') or ''}".strip())
        clock.mark().write_text(zone + "\n")  # chosen on purpose: phones no longer guess
        print(zone)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

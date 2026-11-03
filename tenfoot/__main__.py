"""python3 -m tenfoot [serve | render | links | link NAME | revoke NAME | timezone [ZONE]]"""
import glob
import json
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer

from . import browser, cec, clock, config, kiosk, links, server, setup, spotify, watcher
from .apps import load_apps
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


def render(settings):
    """Write what the file:// home screen reads: the apps and the settings it needs."""
    config.RUN.mkdir(parents=True, exist_ok=True)
    apps = [{k: a[k] for k in ("id", "name", "url", "color")} for a in load_apps(settings)]
    page = {"name": settings.name, "latitude": settings.latitude, "longitude": settings.longitude,
            "temperatureUnit": settings.temperature_unit}
    (config.RUN / "display-mode").write_text(settings.display_mode)  # for system/kiosk.sh
    (config.RUN / "config.js").write_text(f"window.APPS = {json.dumps(apps)};\nwindow.TENFOOT = {json.dumps(page)};\n")


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

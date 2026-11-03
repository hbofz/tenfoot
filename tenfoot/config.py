"""Settings, read once from ~/.config/tenfoot/config.toml. Everything has a working default."""
import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_HOME = ROOT / "web" / "home"
WEB_REMOTE = ROOT / "web" / "remote"
INJECT = ROOT / "inject"
# Files the service writes for the file:// home screen to load (QR code, apps). Never committed.
RUN = WEB_HOME / "run"
# Fixed, because the pages and system/kiosk.sh name them too. Both are localhost only, always.
LOCAL_PORT = 8766  # the home screen's local API
CDP_PORT = 9222  # Chromium's DevTools
CHROMIUM_PROFILE = "~/.config/tenfoot/chromium"
CONFIG_DIR = Path(os.environ.get("TENFOOT_CONFIG", "~/.config/tenfoot")).expanduser()


@dataclass(frozen=True)
class Settings:
    name: str = "Tenfoot"  # what the TV, Spotify and AirPlay call this box
    place: str = ""  # the weather's place, as picked on the phone ("Lisbon, Portugal")
    latitude: float | None = None  # for the weather on the home screen; none = no weather
    longitude: float | None = None
    temperature_unit: str = "celsius"  # or "fahrenheit"
    remote_mode: str = "lan"  # "lan", "tailscale" (behind Tailscale Serve or Funnel) or "url"
    remote_url: str = ""  # with "url": the address phones reach this box at, with no trailing slash
    remote_port: int = 8765
    display_mode: str = "1920x1080@60"
    spotify: bool = True  # Spotify Connect, through go-librespot
    jellyfin_url: str = ""
    remote_devices: list[str] = field(default_factory=lambda: [r"vc4-hdmi-\d+"])  # input devices to grab as TV remotes
    updates: str = "auto"  # "auto" (installs at night), "notify" (waits for the phone) or "off"; read by system/tenfoot-update

    @property
    def screen(self):
        w, h = self.display_mode.split("@")[0].split("x")
        return int(w), int(h)

    @property
    def listen_host(self):
        return "0.0.0.0" if self.remote_mode == "lan" else "127.0.0.1"


def load(path=None):
    """Settings from a TOML file. A mistyped key stops the service at once instead of being ignored."""
    path = Path(path) if path else CONFIG_DIR / "config.toml"
    try:
        values = tomllib.loads(path.read_text())
    except FileNotFoundError:
        return Settings()
    known = {f.name for f in fields(Settings)}
    unknown = set(values) - known
    if unknown:
        raise SystemExit(f"{path}: unknown settings: {', '.join(sorted(unknown))}")
    settings = Settings(**values)
    if settings.remote_mode not in ("lan", "tailscale", "url"):
        raise SystemExit(f"{path}: remote_mode must be lan, tailscale or url")
    if settings.updates not in ("auto", "notify", "off"):
        raise SystemExit(f"{path}: updates must be auto, notify or off")
    if settings.remote_mode == "url" and not settings.remote_url.startswith(("http://", "https://")):
        raise SystemExit(f"{path}: remote_mode = \"url\" needs a remote_url")
    return settings


def write_private(path, text):
    """Write a file only this user can read, atomically."""
    path = str(path)
    tmp = path + ".tmp"
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write(text)
    os.replace(tmp, path)

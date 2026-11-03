"""The updater's news, for the TV and the phone, and the phone's "Update now". The updater runs as root
(system/tenfoot-update); this user can only read what it reports, and ask it to start."""
import json
import subprocess
from pathlib import Path

from .config import ROOT

STATUS = Path("/var/lib/tenfoot-update/status.json")


def status():
    """{version, available: {version, notes} | None, state: idle | downloading | installing, error, error_at, mode}"""
    try:
        st = json.loads(STATUS.read_text())
    except (OSError, ValueError):
        st = {}  # not installed by install.sh (a dev run), or the updater hasn't run yet
    out = {k: st.get(k) for k in ("available", "error", "error_at", "mode")}
    out["state"] = st.get("state") or "idle"
    out["version"] = (ROOT / "VERSION").read_text().strip()  # what's running
    return out


def start():
    """Start the updater now (polkit lets this user start this one unit, and nothing else)."""
    subprocess.run(["systemctl", "start", "--no-block", "tenfoot-update-now.service"], check=True, timeout=30,
                   capture_output=True)

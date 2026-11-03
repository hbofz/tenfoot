"""Who may use the phone remote. Everything lives under /<token>/, so the bare port is no use to
anyone. A token is the house link, a personal link, or the guest link the TV's QR code shows."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import subprocess
import sys

import qrcode
import qrcode.image.svg

from .config import CONFIG_DIR, RUN, write_private

TOKEN_FILE = CONFIG_DIR / "token"
PEOPLE_FILE = CONFIG_DIR / "people"
USAGE = """links          list the links
link NAME      make (or show) NAME's personal link; NAME is a-z, 0-9, _ or -
revoke NAME    that link stops working at once
revoke house   new shared secret: the shared link and the TV's QR code both change"""


def load_token(path=TOKEN_FILE):
    """The house secret: made once, kept out of the repo."""
    path = str(path)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
            f.write(secrets.token_urlsafe(18))
    token = open(path).read().strip()
    if len(token) < 16:
        sys.exit(f"{path} is too short to be a secret; delete it to make a new one")
    return token


def guest_token(house):
    """The link the TV's QR code shows, derived from the house secret, so revoking that kills this too."""
    mac = hmac.new(house.encode(), b"guest", hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac[:18]).decode()


def people(path=PEOPLE_FILE):
    """{name: token} of the personal links, one 'name token' per line."""
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return {}
    return {n: t for n, _, t in (line.partition(" ") for line in lines) if t}


def who(token, house, personal):
    """Whose link a token is: 'house', a person's name, 'guest', or None. Checks them all in constant time per link."""
    links = [("house", house), *personal.items(), ("guest", guest_token(house))]
    for name, t in links:
        if hmac.compare_digest(token.encode(), t.encode()):
            return name
    return None


def route(path, name_of):
    """('page'|'api'|'ws'|'redirect'|None, link name) for a request path. name_of(token) says whose
    link a token is (None: nobody's), so a wrong token gets the same answer as a wrong path."""
    parts = path.split("?")[0].split("/")  # ['', token, rest...]
    name = name_of(parts[1]) if len(parts) >= 2 else None
    if not name:
        return None, None
    if len(parts) == 2:
        return "redirect", name
    return {"": "page", "index.html": "page", "api": "api", "ws": "ws", "report.txt": "report"}.get("/".join(parts[2:])), name


def lan_ip():
    """This box's address on the home network. No packet is sent: connecting a UDP socket only picks the route."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))
        return s.getsockname()[0]


def base_url(settings):
    """Where phones reach this box, with no trailing slash."""
    if settings.remote_mode == "url":
        return settings.remote_url.rstrip("/")
    if settings.remote_mode == "lan":
        return f"http://{lan_ip()}:{settings.remote_port}"
    status = json.loads(subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=10).stdout)
    host = status["Self"]["DNSName"].rstrip(".")
    if not host:  # still starting at boot: a hostless link sends phones to "https://<token>/"
        raise RuntimeError("tailscale has no DNS name yet")
    return f"https://{host}"


def link_url(settings, token):
    return f"{base_url(settings)}/{token}/"


def write_qr(settings, house, path=None):
    """Draw the guest link as the QR code the home screen shows, so anyone in the room can scan it."""
    path = path or RUN / "remote-qr.svg"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = str(path) + ".tmp"
    qrcode.make(link_url(settings, guest_token(house)), image_factory=qrcode.image.svg.SvgPathFillImage, border=2).save(tmp)
    os.chmod(tmp, 0o600)  # it contains the link
    os.replace(tmp, path)


def cli(settings, args):
    """tenfoot links | link NAME | revoke NAME."""
    house = load_token()
    ppl = people()
    if args == ["links"]:
        for name in ["house", *sorted(ppl)]:
            print(name)
        return
    cmd, name = (args + [""])[:2]
    if cmd not in ("link", "revoke") or not re.fullmatch(r"[a-z0-9_-]{1,32}", name):
        sys.exit(USAGE)
    if cmd == "revoke" and name == "house":
        os.remove(TOKEN_FILE)
        subprocess.run(["systemctl", "--user", "restart", "tenfoot"], check=True, timeout=30)
        return print("revoked the house link and the guest QR; the TV shows a new QR")
    if name in ("house", "guest"):
        sys.exit(f"'{name}' is taken")
    if cmd == "link":
        ppl.setdefault(name, secrets.token_urlsafe(18))
    elif ppl.pop(name, None) is None:
        sys.exit(f"no link called {name}")
    write_private(PEOPLE_FILE, "".join(f"{n} {t}\n" for n, t in sorted(ppl.items())))
    print(link_url(settings, ppl[name]) if cmd == "link" else f"revoked {name}")

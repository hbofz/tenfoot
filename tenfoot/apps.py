"""The TV's apps, and what a URL means: which app it is, and whether a phone may open it."""
import ipaddress
import json
import re
import socket
import urllib.parse

from .config import CONFIG_DIR, ROOT, WEB_HOME

# Any page on these sites, sign-in pages too, is that app.
SITE_APPS = {"netflix.com": "netflix", "shahid.mbc.net": "shahid", "disneyplus.com": "disney", "hbomax.com": "hbomax",
             "crunchyroll.com": "crunchyroll", "paramountplus.com": "paramount"}
PAGES = {"home.html": "home", "spotify.html": "spotify", "sleep.html": "asleep", "setup.html": "setup"}


def load_apps(settings):
    """The apps in tile order: ~/.config/tenfoot/apps.json if you made one, else the defaults."""
    custom = CONFIG_DIR / "apps.json"
    apps = json.loads((custom if custom.exists() else ROOT / "apps.json").read_text())
    if not settings.spotify:
        apps = [a for a in apps if a["id"] != "spotify"]
    if settings.jellyfin_url and not any(a["id"] == "jellyfin" for a in apps):
        apps.insert(1, {"id": "jellyfin", "name": "Jellyfin", "url": settings.jellyfin_url, "color": "#b36cf2", "mouse": True})
    return apps


def same_site(url, base):
    """Is url on the same scheme, host and port as base? Not a prefix check: http://jf:8096@127.0.0.1/ starts with http://jf:8096."""
    if not base:
        return False
    a, b = urllib.parse.urlsplit(url), urllib.parse.urlsplit(base)
    try:
        return (a.scheme.lower(), a.hostname, a.port) == (b.scheme.lower(), b.hostname, b.port) and not a.username
    except ValueError:  # a port that isn't a number
        return False


def page_url(name):
    """The file:// address of a page next to the home screen."""
    return (WEB_HOME / name).as_uri()


def app_urls(apps):
    """id -> where the app opens; a bare file name is a page next to the home screen."""
    return {a["id"]: a["url"] if "://" in a["url"] else page_url(a["url"]) for a in apps}


def site_of(host, table):
    """The table's domain that host is, or is under; None if none."""
    return next((d for d in table if host == d or host.endswith("." + d)), None)


def app_of(url, jellyfin_url=""):
    """What the TV shows, for the phone's header: (app id, host). host names the site for "web"."""
    if url.startswith("file://"):
        return PAGES.get(url.split("?")[0].split("#")[0].rsplit("/", 1)[-1], "home"), None
    host = (urllib.parse.urlsplit(url).hostname or "").removeprefix("www.")
    if host == "youtube.com" and "/tv" in url:
        return "youtube", None
    site = site_of(host, SITE_APPS)
    if site:
        return SITE_APPS[site], None
    if same_site(url, jellyfin_url):
        return "jellyfin", None
    return "web", host or None


def in_house(url):
    """True if url leads to this box (DevTools, Spotify, the remote), the home network or a tailnet.
    Anyone with a guest link has the keyboard and touchpad, so they don't get admin pages too."""
    host = (urllib.parse.urlsplit(url).hostname or "").rstrip(".").lower()
    if not host or host == "localhost" or host.endswith(".localhost"):
        return True
    try:  # names too: a public name can point at 127.0.0.1 (e.g. nip.io)
        addrs = {a[4][0] for a in socket.getaddrinfo(host, None)}
    except (OSError, UnicodeError):
        return False  # doesn't resolve here, so it leads nowhere
    return any(not ipaddress.ip_address(a.split("%")[0]).is_global for a in addrs)


def youtube_tv(url):
    """A YouTube video link (watch, youtu.be, shorts, live) -> the same video in the TV app,
    which a Pi plays far better than the desktop site. Anything else is left alone."""
    p = urllib.parse.urlsplit(url)
    host = (p.hostname or "").removeprefix("www.").removeprefix("m.")
    vid = None
    if host == "youtu.be":
        vid = p.path[1:]
    elif host == "youtube.com" and p.path == "/watch":
        vid = urllib.parse.parse_qs(p.query).get("v", [""])[0]
    elif host == "youtube.com" and p.path.startswith(("/shorts/", "/live/")):
        vid = p.path.split("/")[2]
    if vid and re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
        return f"https://www.youtube.com/tv#/watch?v={vid}"
    return url


def to_url(text, jellyfin_url=""):
    """What the phone's "open on TV" box typed -> a web URL. Bare words, anything that isn't http(s)
    (file:, chrome:, javascript:, data:...) and addresses inside the house become a search."""
    t = text.strip()
    if urllib.parse.urlsplit(t).scheme.lower() in ("http", "https"):
        url = t
    elif "://" not in t and " " not in t and "." in t:
        url = "https://" + t
    else:
        url = None
    if not url or (in_house(url) and not same_site(url, jellyfin_url)):
        return "https://www.google.com/search?q=" + urllib.parse.quote(t)
    return youtube_tv(url)

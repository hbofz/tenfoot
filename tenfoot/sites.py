"""Per-site browser rules: what each site is told the browser is, and what it may not load."""
import re
import urllib.parse

from .apps import site_of

TV_UA = ("Mozilla/5.0 (SMART-TV; Linux; Tizen 6.0) AppleWebKit/537.36 (KHTML, like Gecko) "
         "76.0.3809.146/6.0 TV Safari/537.36")

# Shahid trackers the ad-blocking DNS lets through (Facebook's SDK is 217 kB of script). Not
# mParticle: blocked, it retries several times a second. Not Google's ad SDK: free accounts need it.
SHAHID_BLOCK = [{"urlPattern": u, "block": True} for u in ("*://connect.facebook.net/*", "*://*.bugsnag.com/*")]

# Script the other streaming sites load that a TV has no use for and the DNS filter lets through:
# tag managers, phone app links, the Chromecast sender SDK and ad pixels. On HBO that's 0.6-0.9 s
# of a Pi's script time per page load.
JUNK = ["*://www.googletagmanager.com/*", "*://www.google.com/ccm/*", "*://app.link/*", "*://*.branch.io/*",
        "*://www.gstatic.com/cv/*", "*://www.gstatic.com/cast/*", "*://www.gstatic.com/eureka/*",
        "*://connect.facebook.net/*", "*://www.facebook.com/tr*", "*://ct.pinterest.com/*", "*://s.pinimg.com/*",
        "*://bat.bing.com/*", "*://www.redditstatic.com/*", "*://sb.scorecardresearch.com/*"]
SITE_BLOCK = {d: [{"urlPattern": u, "block": True} for u in JUNK]
              for d in ("hbomax.com", "disneyplus.com", "crunchyroll.com", "paramountplus.com")}

# A show playing on one of these (its player page). Its video arrives in many small pieces, and
# with the Network domain on, Chromium reports every piece to the watcher: under HBO's player that
# was ~30% of a core in the browser and ~25% in this service. So Network is off once a player page
# has loaded, and on again for any page load and when the page leaves the player.
WATCHING = re.compile(r"https://(play\.hbomax\.com/video/watch/|www\.disneyplus\.com/([\w-]+/)?play/)")


def wants_tv(url):
    """youtube.com/tv only serves its TV app to TVs; every other site gets desktop Chrome."""
    p = urllib.parse.urlsplit(url)
    return p.hostname in ("youtube.com", "www.youtube.com") and p.path.startswith("/tv")


def wants_windows(url):
    """Shahid refuses Linux browsers ("outdated or unauthorized device", a 403 on the stream
    request), so it gets Chrome on Windows instead."""
    return urllib.parse.urlsplit(url).hostname == "shahid.mbc.net"


def windows_identity(desktop_ua):
    """The same Chrome, claiming Windows: UA string plus matching client hints."""
    major = re.search(r"Chrome/(\d+)", desktop_ua).group(1)
    ua = re.sub(r"\(X11; [^)]*\)", "(Windows NT 10.0; Win64; x64)", desktop_ua)
    meta = {"brands": [{"brand": "Chromium", "version": major}, {"brand": "Google Chrome", "version": major},
                       {"brand": "Not=A?Brand", "version": "24"}],
            "platform": "Windows", "platformVersion": "15.0.0", "architecture": "x86", "bitness": "64",
            "model": "", "mobile": False}
    return ua, meta


def identity(url, desktop_ua):
    """(user agent, setUserAgentOverride params) for a page on url."""
    if wants_tv(url):
        return TV_UA, {"userAgent": TV_UA}
    if wants_windows(url):
        ua, meta = windows_identity(desktop_ua)
        return ua, {"userAgent": ua, "userAgentMetadata": meta}
    return desktop_ua, {"userAgent": ""}  # "" clears the override: stock Chrome, client hints too


def rules_for(url):
    """The URL patterns a page on url may not load."""
    host = urllib.parse.urlsplit(url).hostname or ""
    return SHAHID_BLOCK if wants_windows(url) else SITE_BLOCK.get(site_of(host, SITE_BLOCK), [])

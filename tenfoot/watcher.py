"""Watches every tab over DevTools. As each page starts loading it sets that site's identity and
blocking, injects the TV layer, closes ad popups and pauses Spotify so two things never play at once."""
import itertools
import json
import threading
import time
import urllib.parse

import websocket

from .apps import app_of
from .browser import on_screen
from .config import INJECT
from .sites import WATCHING, identity, rules_for, wants_tv, wants_windows

# keyboard before sites: while the keyboard is up it takes the remote's keys first. Each in its own
# try: one that a page breaks (a site that bans innerHTML) leaves the rest working.
SCRIPTS = ("youtube.js", "spotify-web.js", "keyboard.js", "sites.js", "shahid.js", "pointer.js")
NETWORK_PARAMS = {"maxTotalBufferSize": 0, "maxResourceBufferSize": 0}  # keep no copies of responses for DevTools


def injected_script(jellyfin_url=""):
    host = urllib.parse.urlsplit(jellyfin_url).hostname or "jellyfin.invalid"
    return "\n".join(f'try {{\n{(INJECT / f).read_text()}\n}} catch (e) {{ console.error("{f}", e); }}'
                     for f in SCRIPTS).replace("__JELLYFIN_HOST__", host)


class Watcher:
    """One connection's worth of state. run() makes a new Watcher each time the browser (re)starts."""

    def __init__(self, send, desktop_ua, script, jellyfin_url="", on_app_opened=lambda: None):
        self.send = send
        self.desktop_ua = desktop_ua
        self.script = script
        self.jellyfin_url = jellyfin_url
        self.on_app_opened = on_app_opened
        self.pages = {}  # session -> target id (a page's main frame id is its target id)
        self.urls = {}  # page session -> the address it shows
        self.quiet = set()  # page sessions playing a show, their Network domain off (sites.WATCHING)

    def start(self):
        self.send("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True})

    def network(self, sid, url, loading=False):
        """Network off once url, a show's player page, has loaded; on (with its blocking) everywhere else."""
        off = WATCHING.match(url) and not loading
        if sid in self.quiet and not off:
            self.quiet.discard(sid)
            self.send("Network.enable", NETWORK_PARAMS, sid)
            self.send("Network.setBypassServiceWorker", {"bypass": True}, sid)
            self.send("Network.setBlockedURLs", {"urlPatterns": rules_for(url)}, sid)
        elif sid not in self.quiet and off:
            self.quiet.add(sid)
            self.send("Network.disable", None, sid)

    def network_on(self):
        """Network back on everywhere; True if it was off anywhere."""
        was = bool(self.quiet)
        for sid in list(self.quiet):
            self.network(sid, "about:blank", loading=True)  # the load that follows sets its own blocking
        return was

    def handle(self, message):
        params, session = message.get("params", {}), message.get("sessionId")
        method = message.get("method")
        if method == "Target.attachedToTarget":
            self.attached(params)
        elif method == "Fetch.requestPaused":
            self.request_paused(params, session)
        elif method == "Page.frameNavigated" and session in self.pages and not params["frame"].get("parentId"):
            self.moved(session, params["frame"]["url"], loading=True)  # a load a service worker answered, or back/forward
        elif method == "Page.navigatedWithinDocument" and params.get("frameId") == self.pages.get(session):
            self.moved(session, params["url"])  # these sites change pages without loading one
        elif method == "Page.loadEventFired" and session in self.urls:
            self.network(session, self.urls[session])  # a player page opened directly: once it has loaded
        elif method == "Target.detachedFromTarget":
            sid = params.get("sessionId")
            self.quiet.discard(sid)
            self.pages.pop(sid, None)
            self.urls.pop(sid, None)

    def moved(self, sid, url, loading=False):
        if sid in self.urls:
            self.urls[sid] = url
        self.network(sid, url, loading)

    def is_ad_popup(self, target):
        """A tab a website opened, while only websites are open: on a TV that's an ad covering the film,
        with no tab bar to get back. Real apps keep theirs, e.g. a "sign in with Google" window."""
        return (on_screen(target) and target.get("openerId")
                and all(app_of(u, self.jellyfin_url)[0] == "web" for u in self.urls.values()))

    def attached(self, params):
        sid, target = params["sessionId"], params["targetInfo"]
        if self.is_ad_popup(target):
            # Let it run first: a new window starts in its opener's process, paused for us, and
            # closed while paused it leaves the opener frozen too (no clicks, pages never load).
            self.send("Runtime.runIfWaitingForDebugger", None, sid)
            self.send("Target.closeTarget", {"targetId": target["targetId"]})
            return
        if target["type"] == "page":
            self.pages[sid] = target["targetId"]
            if on_screen(target):
                self.urls[sid] = target["url"]
            self.send("Fetch.enable", {"patterns": [{"resourceType": "Document"}]}, sid)
            self.send("Page.enable", None, sid)
            # A site's service worker can answer page loads without the network, and then the Fetch
            # hook above never sees them: one visit to desktop youtube.com made every later
            # youtube.com/tv load come out as the website. So skip them (needs Network on).
            self.send("Network.enable", NETWORK_PARAMS, sid)
            self.send("Network.setBypassServiceWorker", {"bypass": True}, sid)
            self.send("Page.addScriptToEvaluateOnNewDocument", {"source": self.script}, sid)
            if not params.get("waitingForDebugger"):
                # Already open when this connection started (the service restarted): its identity and
                # blocking went with the old connection.
                self.send("Emulation.setUserAgentOverride", identity(target["url"], self.desktop_ua)[1], sid)
                self.send("Network.setBlockedURLs", {"urlPatterns": rules_for(target["url"])}, sid)
                self.network(sid, target["url"])  # mid-show already
        self.send("Runtime.runIfWaitingForDebugger", None, sid)

    def request_paused(self, params, session):
        request = params["request"]
        if params.get("frameId") != self.pages.get(session):  # frames keep the page's identity
            return self.send("Fetch.continueRequest", {"requestId": params["requestId"]}, session)
        url = request["url"]
        # Opening a web app pauses Spotify. The home and Spotify screens are file:// and never pass through here.
        if url.startswith("http"):
            threading.Thread(target=self.on_app_opened, daemon=True).start()
        self.network(session, url, loading=True)  # a page loading gets its blocking; off once it has loaded
        tv, windows = wants_tv(url), wants_windows(url)
        ua, override = identity(url, self.desktop_ua)
        self.send("Emulation.setUserAgentOverride", override, session)
        self.send("Network.setBlockedURLs", {"urlPatterns": rules_for(url)}, session)
        headers = [{"name": k, "value": v} for k, v in request["headers"].items()
                   if k.lower() != "user-agent" and not ((tv or windows) and k.lower().startswith("sec-ch-ua"))]
        headers.append({"name": "User-Agent", "value": ua})
        if windows:
            headers.append({"name": "Sec-CH-UA-Platform", "value": '"Windows"'})
        self.send("Fetch.continueRequest", {"requestId": params["requestId"], "headers": headers}, session)


def run(browser, script, jellyfin_url="", on_app_opened=lambda: None):
    """Watch for good. Chromium restarting is normal, not a crash: be back within 2 s, or a page
    opened in the gap gets the wrong identity."""
    while True:
        try:
            _watch(browser, script, jellyfin_url, on_app_opened)
        except (OSError, websocket.WebSocketException):
            time.sleep(2)


def _watch(browser, script, jellyfin_url, on_app_opened):
    info = browser.version()
    ws = websocket.create_connection(info["webSocketDebuggerUrl"], suppress_origin=True, enable_multithread=True)
    ids = itertools.count(1)

    def send(method, params=None, session=None):
        message = {"id": next(ids), "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        ws.send(json.dumps(message))
    try:
        watcher = Watcher(send, info["User-Agent"].replace("HeadlessChrome", "Chrome"), script, jellyfin_url, on_app_opened)
        browser.network_on = watcher.network_on
        watcher.start()
        while True:
            watcher.handle(json.loads(ws.recv()))
    finally:
        browser.network_on = lambda: False
        ws.close()

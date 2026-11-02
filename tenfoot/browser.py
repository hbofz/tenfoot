"""The kiosk's Chromium, through its DevTools port on localhost."""
import json
import time
import urllib.request

import websocket


def on_screen(target):
    """The tab the TV shows; Chromium also lists hidden chrome:// helper pages."""
    return target["type"] == "page" and not target["url"].startswith("chrome://")


class Browser:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"
        self.network_on = lambda: False  # set by the watcher: Network back on in every quiet page

    def _tabs(self):
        return json.load(urllib.request.urlopen(self.base + "/json/list", timeout=3))

    def version(self):
        return json.load(urllib.request.urlopen(self.base + "/json/version", timeout=3))

    def current_url(self):
        return next(t["url"] for t in self._tabs() if on_screen(t))

    def one_tab(self):
        """Close every tab but one. The kiosk has no tab bar: a second tab (an ad's) hides the page,
        plays on unseen, and commands would go to whichever tab Chromium lists first."""
        for t in [t for t in self._tabs() if on_screen(t)][1:]:
            urllib.request.urlopen(self.base + "/json/close/" + t["id"], timeout=3).close()

    def call(self, method, params=None):
        """One DevTools call against the tab on screen -> (result, the tab's url)."""
        tab = next(t for t in self._tabs() if on_screen(t))
        ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=5, suppress_origin=True)
        try:
            ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == 1:
                    if "error" in msg:  # e.g. the page crashed; never report that as success
                        raise ValueError(msg["error"].get("message", "DevTools error"))
                    return msg.get("result", {}), tab["url"]
        finally:
            ws.close()

    def navigate(self, url):
        """Load url in the tab on screen. A page playing a show has Network off, and a service worker
        could answer this load where the watcher never sees it: turn it on and let that land first."""
        try:
            quiet = self.network_on()
        except Exception:  # the watcher's connection is down: it sets everything up when it reconnects
            quiet = False
        if quiet:
            time.sleep(0.2)
        return self.call("Page.navigate", {"url": url})

    def evaluate(self, expression):
        return self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})[0]

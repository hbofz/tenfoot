#!/usr/bin/env python3
"""Frame rate of the page in a kiosk, measured on the Pi over the DevTools port.
  python3 fps.py [port]                 5 s of requestAnimationFrame, idle
  python3 fps.py [port] --keys Right,Down   ... pressing those keys every 500 ms (cycling)
  python3 fps.py [port] --eval 'js'     just print what the expression returns
Prints fps=<frames per second> long=<frames over 25 ms>. Use 9333 for shot.sh-style test kiosks,
9222 for the live one (read-only: no --keys while people watch)."""
import json
import sys
import urllib.request

import websocket  # python3-websocket

KEYS = {"Right": 39, "Left": 37, "Up": 38, "Down": 40, "Enter": 13}


def page(port):
    tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5))
    return websocket.create_connection(next(t for t in tabs if t["type"] == "page")["webSocketDebuggerUrl"], timeout=30,
                                       suppress_origin=True)  # like the service: Chromium refuses an Origin header


def call(ws, method, params, n=[0]):
    n[0] += 1
    ws.send(json.dumps({"id": n[0], "method": method, "params": params}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == n[0]:
            return msg.get("result", {})


def press(ws, key):
    for kind in ("rawKeyDown", "keyUp"):
        call(ws, "Input.dispatchKeyEvent", {"type": kind, "key": "Arrow" + key if key in ("Right", "Left", "Up", "Down") else key,
                                             "windowsVirtualKeyCode": KEYS[key]})


MEASURE = """new Promise((done) => {
  const t0 = performance.now(); let last = t0, frames = 0, long = 0;
  (function f(t) { frames++; if (t - last > 25) long++; last = t;
    if (t - t0 < 5000) requestAnimationFrame(f); else done(JSON.stringify({fps: frames / ((t - t0) / 1000), long})); })(t0);
})"""


def main(args):
    port = int(args[0]) if args and args[0].isdigit() else 9333
    ws = page(port)
    if "--eval" in args:
        r = call(ws, "Runtime.evaluate", {"expression": args[args.index("--eval") + 1], "returnByValue": True, "awaitPromise": True})
        return print(json.dumps(r.get("result", {}).get("value")))
    keys = args[args.index("--keys") + 1].split(",") if "--keys" in args else []
    call(ws, "Runtime.evaluate", {"expression": "window.__fps = " + MEASURE, "awaitPromise": False})
    import time
    for i in range(10 if keys else 0):
        press(ws, keys[i % len(keys)])
        time.sleep(0.5)
    r = call(ws, "Runtime.evaluate", {"expression": "window.__fps", "awaitPromise": True, "returnByValue": True})
    d = json.loads(r["result"]["value"])
    print(f"fps={d['fps']:.1f} long={d['long']}")


if __name__ == "__main__":
    main(sys.argv[1:])

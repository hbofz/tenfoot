"""Two web servers. The remote: the phone's page and API, under a secret link. The local API:
localhost only, for the file:// home and Spotify screens."""
import base64
import hashlib
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler

from . import links, lyrics, visualizer
from .config import WEB_REMOTE


def ws_messages(rfile):
    """The text messages a browser sends over a WebSocket (RFC 6455), until it closes.
    ponytail: no fragmented messages; browsers send small ones whole"""
    while True:
        head = rfile.read(2)
        if len(head) < 2 or not head[1] & 0x80:  # gone, or unmasked (browsers always mask)
            return
        n = head[1] & 0x7F
        if n >= 126:
            n = int.from_bytes(rfile.read(2 if n == 126 else 8), "big")
        if n > 10000:
            return
        mask, data = rfile.read(4), rfile.read(n)
        if head[0] & 0x0F == 8:  # close
            return
        if head[0] & 0x0F == 1:  # text; pings and binary are skipped
            yield bytes(b ^ mask[i % 4] for i, b in enumerate(data)).decode()


def remote_handler(controls, house):
    """The request handler class for the phone's server."""

    class Remote(BaseHTTPRequestHandler):
        timeout = 20  # drop clients that connect and then sit silent

        def link(self):
            """(what the path asks for), remembering whose link it is for commands and the error log."""
            kind, self.name = links.route(self.path, lambda tok: links.who(tok, house, links.people()))
            return kind

        def do_GET(self):
            kind = self.link()
            if kind == "redirect":
                self.send_response(301)
                self.send_header("Location", self.path.split("?")[0] + "/")
                self.send_header("Content-Length", "0")
                return self.end_headers()
            if kind == "ws" and self.headers.get("Upgrade", "").lower() == "websocket":
                return self.pointer_stream()
            if kind != "page":
                return self.send_error(404)
            body = (WEB_REMOTE / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            # The URL is the key: never send it on as a Referer, keep it out of caches, never framed.
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def pointer_stream(self):
            """Mouse moves, clicks and scrolls as a stream: the phone sends each the moment the finger
            moves. As POSTs, one in flight at a time, the pointer moved once per round trip (50-200 ms)."""
            key = self.headers.get("Sec-WebSocket-Key", "") + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
            self.protocol_version = "HTTP/1.1"  # the handshake must be 1.1
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", base64.b64encode(hashlib.sha1(key.encode()).digest()).decode())
            self.end_headers()
            self.close_connection = True
            try:
                for msg in ws_messages(self.rfile):  # the phone says something every 10 s, else timeout drops it
                    cmd = json.loads(msg)
                    if isinstance(cmd, dict) and cmd.get("a") in ("move", "click", "scroll"):
                        controls.handle(cmd)
            except Exception:  # went quiet (phone locked), or junk: the phone reconnects or falls back to POSTs
                pass

        def do_POST(self):
            if self.link() != "api":
                return self.send_error(404)
            try:
                n = int(self.headers.get("Content-Length", 0))
                if not 0 <= n <= 10000:
                    raise ValueError("too big")
                cmd = json.loads(self.rfile.read(n))
                if not isinstance(cmd, dict):
                    raise ValueError("not a command")
                cmd["by"] = self.name  # whose link sent it (set here, never by the phone)
                result = controls.handle(cmd)
                code, msg = 200, (json.dumps(result).encode() if result is not None else b"ok")
            except Exception as ex:  # report to the phone instead of dying
                code, msg = 400, str(ex).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

        def log_message(self, fmt, *args):
            # Errors only (every touchpad move would otherwise be a disk write), with the token blanked out.
            if not str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
                return
            parts = self.path.split("?")[0].split("/")
            msg = (fmt % args).replace(parts[1], "<token>") if len(parts) > 1 and parts[1] else fmt % args
            print(f"http: {msg} link={getattr(self, 'name', None)} from={self.headers.get('X-Forwarded-For') or self.client_address[0]} ua={self.headers.get('User-Agent', '')[:60]}", flush=True)

    return Remote


class Local(BaseHTTPRequestHandler):
    """What the TV's own pages ask for. Sites on the TV can't reach it (chromium-policy.json)."""
    wifi_setup = None  # not "setup": that's a method the request handler needs

    def reply(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")  # the pages are file://
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/setup":
            status = self.wifi_setup.status() if self.wifi_setup else {"state": "off"}
            return self.reply(200, json.dumps(status).encode())
        if url.path == "/lyrics":
            q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
            try:
                lines = lyrics.lookup(q["track"], q.get("artist", ""), q.get("album", ""), int(q.get("seconds", 0)))
                return self.reply(200, json.dumps({"lines": lines}).encode())
            except Exception as ex:
                return self.reply(502, json.dumps({"error": str(ex)}).encode())
        if url.path != "/bands":
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        def write(line):
            self.wfile.write(f"data: {line}\n\n".encode())
            self.wfile.flush()
        try:
            visualizer.stream(write)
        except (BrokenPipeError, ConnectionResetError):
            pass  # screen closed

    def log_message(self, *args):
        pass

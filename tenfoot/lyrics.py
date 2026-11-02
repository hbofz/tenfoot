"""Synced lyrics from LRCLIB (lrclib.net), a free, open lyrics database that needs no account."""
import functools
import json
import re
import urllib.error
import urllib.parse
import urllib.request

LINE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")
API = "https://lrclib.net/api/get?"


def parse_lrc(text):
    """'[00:12.34] words' lines -> [{t: seconds, text}]. Empty lines are instrumental breaks, kept
    so a line's highlight ends before the break."""
    lines = []
    for raw in (text or "").splitlines():
        m = LINE.match(raw.strip())
        if m:
            lines.append({"t": int(m[1]) * 60 + float(m[2]), "text": m[3].replace("♪", "").strip()})
    return lines


@functools.lru_cache(maxsize=64)  # failures raise, so they aren't remembered
def lookup(track, artist, album, seconds):
    q = urllib.parse.urlencode({"track_name": track, "artist_name": artist, "album_name": album, "duration": seconds})
    req = urllib.request.Request(API + q, headers={"User-Agent": "Tenfoot (https://github.com/hbofz/tenfoot)"})
    try:
        return parse_lrc(json.load(urllib.request.urlopen(req, timeout=10)).get("syncedLyrics"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []  # none for this track
        raise

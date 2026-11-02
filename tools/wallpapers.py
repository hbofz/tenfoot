#!/usr/bin/env python3
"""Fetch the home screen's wallpapers (web/home/wallpapers.js) from Wikimedia Commons into web/home/wallpapers/: each one cut
to exactly 1920x1080 (the TV's mode, so the Pi never scales it) plus a small blurred copy: the frosted glass of the
dock and the backdrop behind the app grid (blurring live is too much for the Pi's GPU). Only makes what's missing.
Each photo's author and licence go in web/home/wallpapers/CREDITS.txt. Needs python3-pil. Run: python3 tools/wallpapers.py [how many]"""
import html, io, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from PIL import Image, ImageEnhance, ImageFilter

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "web", "home", "wallpapers")
UA = {"User-Agent": "Tenfoot-wallpapers/1.0 (https://github.com/hbofz/tenfoot)"}  # Wikimedia asks for a descriptive one
W, H = 1920, 1080


def load():
    text = open(os.path.join(HERE, "web", "home", "wallpapers.js")).read()
    return json.loads(re.sub(r",(\s*[\]}])", r"\1", text.split("=", 1)[1].strip().rstrip(";")))


def get(url):
    for wait in (30, 60, 120, 0):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or not wait:  # 429: Wikimedia's rate limit, back off and retry
                raise
            after = e.headers.get("Retry-After", "")
            time.sleep(int(after) if after.isdigit() else wait)


def fetch(name):
    q = urllib.parse.urlencode({"action": "query", "format": "json", "prop": "imageinfo", "titles": "File:" + name,
                                "iiprop": "url|extmetadata", "iiurlwidth": 2560})
    page = next(iter(json.loads(get("https://commons.wikimedia.org/w/api.php?" + q))["query"]["pages"].values()))
    if "imageinfo" not in page:
        raise LookupError(f"not on Commons (renamed or deleted?): {name}")
    ii = page["imageinfo"][0]
    meta = ii.get("extmetadata", {})
    field = lambda k: " ".join(html.unescape(re.sub(r"<[^>]+>", "", meta.get(k, {}).get("value", ""))).split())[:80]
    credit = f"{name}: {field('Artist') or 'unknown'}, {field('LicenseShortName') or 'see Commons'}, https://commons.wikimedia.org/wiki/File:{urllib.parse.quote(name)}"
    return Image.open(io.BytesIO(get(ii.get("thumburl") or ii["url"]))).convert("RGB"), credit


def cover(im, w, h):
    r = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
    left, top = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((left, top, left + w, top + h))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    for wp in load()[:limit]:
        path = os.path.join(OUT, wp["id"] + ".jpg")
        if not os.path.exists(path):
            try:
                im, credit = fetch(wp["file"])
                im = cover(im, W, H)
                with open(os.path.join(OUT, "CREDITS.txt"), "a") as f:
                    f.write(credit + "\n")
            except Exception as e:  # one bad entry shouldn't stop the rest
                print(f"{wp['id']}: skipped, {e}")
                continue
            im.save(path + ".tmp", "JPEG", quality=84, optimize=True)  # baseline: the Pi decodes it fastest
            os.replace(path + ".tmp", path)  # never a half-written photo that looks done
            print(wp["id"])
            time.sleep(2)  # go easy on Commons
        if not os.path.exists(path[:-4] + "-blur.jpg"):
            # 480x270 stretched 4x stays smooth; glass keeps the photo's colour, a little richer and darker (like tvOS)
            im = Image.open(path).resize((W // 4, H // 4), Image.LANCZOS).filter(ImageFilter.GaussianBlur(8))
            im = ImageEnhance.Brightness(ImageEnhance.Color(im).enhance(1.35)).enhance(0.85)
            im.save(path[:-4] + "-blur.jpg.tmp", "JPEG", quality=80)
            os.replace(path[:-4] + "-blur.jpg.tmp", path[:-4] + "-blur.jpg")

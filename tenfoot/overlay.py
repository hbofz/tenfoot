"""Small notes drawn over whatever page is on screen."""
import json

# A site's own fullscreen player hides everything outside it; a video or frame can't hold the note.
HOST = "const fs = document.fullscreenElement, host = fs && !/^(VIDEO|IFRAME)$/.test(fs.tagName) ? fs : document.documentElement;"
TOAST = """(() => {
  let b = document.getElementById("tenfoot-toast");
  if (!b) {
    b = document.createElement("div");
    b.id = "tenfoot-toast";
    b.style.cssText = "position:fixed;bottom:7vh;left:50%;translate:-50% 0;z-index:2147483647;padding:1.4vh 2vw;border-radius:3vh;" +
      "background:rgba(20,20,20,.85);color:#fff;font:600 1.3vw system-ui,sans-serif;pointer-events:none;white-space:nowrap";
  }
  HOST
  if (b.parentNode !== host) host.appendChild(b);
  b.textContent = TEXT;
  clearTimeout(window.__tenfootToast);
  window.__tenfootToast = setTimeout(() => b.remove(), MS);
})()""".replace("HOST", HOST)
VOLUME_BAR = """(() => {
  let b = document.getElementById("tenfoot-vol");
  if (!b) {
    b = document.createElement("div");
    b.id = "tenfoot-vol";
    b.append(document.createElement("div"), document.createElement("span"));  // not innerHTML: YouTube's Trusted Types refuse it
    b.style.cssText = "position:fixed;top:6vh;right:4vw;z-index:2147483647;display:flex;align-items:center;gap:1vw;" +
      "padding:1.4vh 1.4vw;border-radius:2vh;background:rgba(20,20,20,.85);color:#fff;font:600 1.3vw system-ui,sans-serif";
    b.firstChild.style.cssText = "width:14vw;height:.8vh;border-radius:.4vh;background:rgba(255,255,255,.25)";
  }
  HOST
  if (b.parentNode !== host) host.appendChild(b);
  b.firstChild.style.backgroundImage = `linear-gradient(90deg,#fff ${LEVEL}%,transparent ${LEVEL}%)`;
  b.lastChild.textContent = MUTED ? "Muted" : LEVEL;
  clearTimeout(window.__tenfootVol);
  window.__tenfootVol = setTimeout(() => b.remove(), 1500);
})()""".replace("HOST", HOST)


DIM = """(() => {
  let d = document.getElementById("tenfoot-dim");
  HOST
  if (!ON) {
    const was = !!d || !!window.__tenfootDimmed;
    d?.remove();
    if (window.__tenfootDimmed) window.__tenfootDimmed.style.filter = "";
    window.__tenfootDimmed = null;
    return was;
  }
  if (!d) {
    d = document.createElement("div");
    d.id = "tenfoot-dim";
    d.style.cssText = "position:fixed;inset:0;z-index:2147483646;background:#000;opacity:.85;pointer-events:none;transition:opacity 2s";
  }
  if (d.parentNode !== host) host.appendChild(d);
  // a full screen video or frame shows above anything outside it: dim it directly
  if (fs && /^(VIDEO|IFRAME)$/.test(fs.tagName)) { fs.style.filter = "brightness(.15)"; window.__tenfootDimmed = fs; }
})()""".replace("HOST", HOST)


def dim_js(on):
    """Darken whatever's on screen (tenfoot/idle.py), or bring it back."""
    return DIM.replace("ON", "true" if on else "false")


def toast_js(text, ms):
    return TOAST.replace("TEXT", json.dumps(text)).replace("MS", str(int(ms)))


def volume_js(level, muted):
    return VOLUME_BAR.replace("LEVEL", str(int(level))).replace("MUTED", "true" if muted else "false")

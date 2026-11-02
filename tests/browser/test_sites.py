"""Checks inject/sites.js (the TV layer for the streaming sites) with real key presses in Chromium,
on small pages built like the real sites' tricky parts, served at the sites' own addresses so each
site's rules apply. Nothing goes out: every other request is refused.
Run: python3 tests/browser/test_sites.py (needs `pip install playwright && playwright install chromium`)."""
import os
from playwright.sync_api import sync_playwright

LAYER = os.environ.get("LAYER", os.path.join(os.path.dirname(__file__), "..", "..", "inject", "sites.js"))
STYLE = """<style>body { margin: 0; background: #000; color: #fff; font: 20px sans-serif; }
  header { position: fixed; top: 0; left: 0; right: 0; height: 80px; display: flex; gap: 20px; align-items: center;
           padding: 0 40px; background: #111; z-index: 5; }
  .row { display: flex; gap: 20px; overflow-x: scroll; padding: 20px 60px; }
  .tile { flex: none; width: 260px; height: 300px; background: #333; display: block; position: relative; }
  button, a { color: #fff; } </style>"""

# HBO Max: the banner is one big link with a full-screen player box over it, rows scroll sideways,
# each tile has a "..." menu, Left at a row's start opens the slide-out menu.
HBO = STYLE + """
<header><button data-testid="slide_out_nav_menuButton" style="width:40px;height:40px">=</button>
  <a href="/" style="width:80px">HBO</a><a href="/search" style="margin-left:auto">Search</a></header>
<section style="height:800px;position:relative">
  <a data-testid="immersive-hero-surface-button" href="/show/hero" style="position:absolute;inset:0"></a>
  <div data-testid="overlay-root" tabindex="0" style="position:absolute;inset:0"></div>
  <button data-testid="play_button" style="position:absolute;left:60px;top:650px;width:250px;height:60px">Watch</button>
  <button data-testid="myList_button" style="position:absolute;left:330px;top:650px;width:60px;height:60px;border-radius:50%">+</button>
  <button data-testid="immersive-hero-audio-button" style="position:absolute;right:60px;top:680px;width:60px;height:60px">mute</button>
</section>""" + "".join('<div class="row" data-testid="tileList">' + "".join(
    f'<a class="tile" data-testid="{r}{i}_tile" href="/movie/{r}-{i}"><div style="height:100%;border-radius:12px"></div></a>' for i in range(12)) + "</div>" for r in "ab") + """
<div style="height:1200px"></div>
<script>
  document.querySelector("[data-testid=slide_out_nav_menuButton]").onclick = () => setTimeout(() => {
    document.body.insertAdjacentHTML("beforeend", `<nav data-testid="slideOutMenu" style="position:fixed;left:0;top:0;bottom:0;width:400px;
      background:#222;z-index:9;display:flex;flex-direction:column;gap:10px;padding:100px 40px">
      <button data-testid="closeMenuButton">x</button><a href="/home" aria-current="page">Home</a><a href="/series">Series</a>
      <a href="/movies">Movies</a></nav>`);
    document.querySelector("[data-testid=closeMenuButton]").onclick = () => document.querySelector("[data-testid=slideOutMenu]").remove();
  }, 200);
  document.querySelectorAll(".tile").forEach((t) => t.insertAdjacentHTML("beforeend",
    '<button data-testid="dropdownToggleButton" style="position:absolute;right:0;top:0;width:40px;height:40px">...</button>'));
</script>"""

# Disney+: replaces window.CSS, a tab bar that lets only its chosen tab be focused, rows of tiles whose
# captions are links of their own (Continue Watching), labels with quotes in them.
DISNEY = """<script>window.CSS = {};</script>""" + STYLE + """
<div style="padding:120px 60px 0;display:flex;gap:20px"><a href="/play/x" style="width:120px;height:56px">PLAY</a>
  <button style="width:56px;height:56px" aria-label="Add to watchlist">+</button></div>
<ul role="tablist" tabindex="0" style="display:flex;gap:40px;list-style:none;padding:20px 60px;margin:0">
  <li role="tab" tabindex="0" aria-selected="true">SUGGESTED</li><li role="tab" tabindex="-1">DETAILS</li></ul>
""" + "".join(f'<div class="row" data-testid="set-shelf">' + "".join(
    f'<div style="flex:none"><a class="tile" data-testid="set-item" href="/browse/{r}{i}" aria-label="Tile {r}{i} &quot;quoted&quot;"></a>'
    f'<a data-testid="cw-set-item-metadata" href="/browse/{r}{i}c" style="display:block;height:60px">caption</a></div>' for i in range(12))
    + "</div>" for r in "ab")

# Any site (default rules): fixed top menu, a sticky bar holding Watch Now, row titles that are
# disabled links, tiles that are role=link divs.
STICKY = STYLE + """
<header><a href="/watch/home" style="width:100px">Home</a><a href="/watch/movies">Movies</a></header>
<div style="height:500px"></div>
<div style="position:sticky;top:80px;display:flex;gap:20px;padding:0 60px;z-index:4">
  <button style="width:180px;height:60px">Add to My Stuff</button><button style="width:200px;height:60px">WATCH NOW</button></div>
""" + "".join(f'<a aria-disabled="true" href="/watch/home" style="display:block;padding:0 60px;width:200px">Row {r}</a>'
              f'<div class="row">' + "".join(f'<div class="tile" role="link" tabindex="0" aria-label="P{r}{i}"></div>' for i in range(12))
              + "</div>" for r in "ab") + """<div style="height:800px"></div>"""


# The ring: 9 px out from the highlighted thing on every side (on any page: its own box sizing, its zoom).
RING = "[...document.documentElement.children].find((d) => d.style.zIndex === '2147483647')"
RING_ON_HIGHLIGHT = f"""(() => {{ const r = tvHighlight.getBoundingClientRect(), g = {RING}.getBoundingClientRect();
  return [g.left + 9 - r.left, g.top + 9 - r.top, g.right - 9 - r.right, g.bottom - 9 - r.bottom].every((d) => Math.abs(d) < 1); }})()"""


# Crunchyroll: shimmering placeholders for rows not loaded yet; a watch page with the player under the
# site's menu, which ignores Enter, and a button over the video (Skip Intro).
CRUNCHY_HOME = STYLE + """<style>.loading-animation--x::after { content: ""; display: block; height: 20px; animation: swipe 1s infinite; }
  @keyframes swipe { to { background-position: 100px 0; } }</style>""" + \
    "".join(f'<div class="loading-image--y loading-animation--x" style="width:200px">p{i}</div>'
            f'<div class="loading-title--t loading-animation--x" style="width:200px">t{i}</div>' for i in range(5))
CRUNCHY_WATCH = STYLE + """<header style="position:static">menu</header>
<div class="video-player-wrapper" style="position:relative;width:1280px;height:720px">
  <video id="empty" style="position:absolute;width:100%;height:100%"></video><video style="width:100%;height:100%"></video></div>
<button id="skip" style="width:200px;height:60px">Skip Intro</button><x-next></x-next>
<script>customElements.define("x-next", class extends HTMLElement { connectedCallback() {
    this.attachShadow({ mode: "open" }).innerHTML = "<button>Next Episode</button>";
    this.shadowRoot.querySelector("button").onclick = () => window.nexted = 1; } });const c = document.createElement("canvas"); c.getContext("2d").fillRect(0, 0, 10, 10);
  addEventListener("keyup", (e) => { if (e.key === "Enter" && e.target === document.body) show.paused ? show.play() : show.pause(); });  // Paramount+'s way
  const show = document.querySelector("video:not(#empty)");  // Disney+ keeps an empty player in front of the show's
  show.srcObject = c.captureStream(); window.skipped = 0; skip.onclick = () => skipped++;</script>"""


# A site that changes pages without loading one: a poster opens a show page, Back redraws the home a
# moment later with the posters in another order.
SPA = STYLE + """<div id="app"></div><script>
  const home = (shift) => '<div style="height:200px"></div>' + ["a", "b"].map((r) => '<div class="row" data-testid="tileList">' + [...Array(8)].map((_, i) =>
    `<a class="tile" data-testid="${r}${(i + shift) % 8}_tile" href="/movie/${(i + shift) % 8}"></a>`).join("") + "</div>").join("");
  app.innerHTML = home(0);
  addEventListener("click", (e) => { const a = e.target.closest("a"); if (!a) return; e.preventDefault(); history.pushState({}, "", a.href);
    app.innerHTML = '<div style="height:300px"></div><button style="margin-left:60px;width:200px;height:60px">Play</button>' +
      `<a class="tile" data-testid="similar" href="${a.getAttribute("href")}">More like this</a>`; });
  addEventListener("popstate", () => { app.innerHTML = ""; setTimeout(() => app.innerHTML = home(3), 1200); });
</script>"""


# A player whose controls show only while the mouse moves and hide again (HBO's): the site's footer
# under the show, a subtitles button that opens a menu over it and puts the focus in there.
PLAYER_UI = STYLE + """<style>#ui { position: fixed; inset: 0; opacity: 0; z-index: 2; } #ui.on { opacity: 1; }
  #bar { position: absolute; left: 0; right: 0; bottom: 40px; height: 60px; } #bar button { position: absolute; top: 0; height: 48px; width: 48px; }
  #panel { position: absolute; right: 60px; bottom: 140px; width: 400px; display: none; } #panel.open { display: block; }
  #panel [role=radio] { display: block; height: 44px; width: 380px; }</style>
<video muted style="position:fixed;inset:0;width:100%;height:100%;z-index:1"></video><footer style="position:absolute;top:1000px;left:0;right:0"><a href="/help" style="display:block;width:300px;height:40px;margin-left:810px">Help</a></footer>
<div id="ui"><div id="bar"><button style="left:866px" aria-label="Skip back 10 seconds"></button><button id="pp" style="left:938px" aria-label="Pause"></button>
  <button id="ahead" style="left:1010px" aria-label="Skip ahead 10 seconds"></button><button id="subs" style="left:1772px" aria-label="Audio and Subtitle Settings"></button>
  <button style="left:1828px" aria-label="Full Screen"></button><span class="fullscreen-icon control" tabindex="0" style="position:absolute;left:1870px;width:40px;height:48px"></span></div>
  <input type="range" id="timeline" aria-label="Timeline" value="50" style="position:absolute;left:60px;right:60px;bottom:120px;width:1800px">
  <div id="panel"><div role="radio" tabindex="0" aria-label="Off">Off</div><div role="radio" tabindex="0" aria-label="English CC">English CC</div></div></div>
<script>const c = document.createElement("canvas"); c.getContext("2d").fillRect(0, 0, 10, 10);
  const v = document.querySelector("video"); v.srcObject = c.captureStream(); v.play();
  let t; addEventListener("mousemove", () => { ui.className = "on"; clearTimeout(t); t = setTimeout(() => ui.className = "", 3000); });  // controls for a moving mouse
  pp.onclick = () => v.paused ? v.play() : v.pause(); subs.onclick = () => { panel.classList.toggle("open"); bar.style.visibility = "hidden"; setTimeout(() => panel.firstElementChild.focus(), 100); };  // HBO puts the focus in its menu, over the button
  panel.addEventListener("click", () => {}); new MutationObserver(() => panel.classList.contains("open") || (bar.style.visibility = "")).observe(panel, { attributes: true });
  window.cc = "Off"; panel.onclick = (e) => cc = e.target.getAttribute("aria-label"); window.skips = 0; ahead.onclick = () => skips++;
  addEventListener("keydown", (e) => { if (e.key === "Escape") panel.classList.remove("open"); window.siteKeys = (window.siteKeys || "") + e.key[0]; });
</script>"""
# Disney+'s: the player and its controls are web components, the controls inside another's shadow root.
SHADOW_PLAYER = STYLE + """<x-player></x-player><script>
  customElements.define("x-controls", class extends HTMLElement { connectedCallback() {
    this.attachShadow({ mode: "open" }).innerHTML = `<style>div { display: none; position: fixed; left: 0; right: 0; bottom: 40px; height: 60px; }
      div.on { display: block; } button { position: absolute; width: 48px; height: 48px; }</style>
      <div><button style="left:936px" aria-label="Pause"></button><button style="left:1800px" aria-label="Settings"></button></div>`; } });
  customElements.define("x-player", class extends HTMLElement { connectedCallback() {
    const r = this.attachShadow({ mode: "open" });
    r.innerHTML = `<video muted style="position:fixed;inset:0;width:100%;height:100%"></video><x-controls></x-controls>
      <div id="catch" style="position:fixed;inset:0 0 120px 0"></div>`;
    r.getElementById("catch").addEventListener("mousemove", () => r.querySelector("x-controls").shadowRoot.querySelector("div").className = "on");
  } });
</script>"""


# Any other website: its own zoom (Spotify's player sets 1.5), a dropdown that closes when its focus
# leaves, a search box, and an article whose next link is screens away.
GENERIC = STYLE + """<script>document.documentElement.style.zoom = "1.5";</script>
<div style="padding:80px 40px 40px;display:flex;gap:20px"><a href="/a" style="width:200px">First</a><input id="q" aria-label="Search"></div>
<div style="padding:0 40px;display:flex;gap:20px"><a href="/help" style="width:200px">Help</a><button id="menu" style="width:120px">Season</button></div>
<div id="list" role="listbox" hidden style="padding:0 40px"><div role="option" tabindex="0">S1</div><div role="option" tabindex="0">S2</div></div>
<p style="height:3000px">An article.</p><a href="/b">Far</a>
<script>menu.onclick = () => { list.hidden = false; list.firstElementChild.focus(); };
  list.addEventListener("focusout", (e) => { if (!list.contains(e.relatedTarget)) list.hidden = true; });</script>"""

# Shahid: rows slide by arrows beside them, which do nothing until a mouse has moved over them.
SHAHID = STYLE + """<div style="padding-top:200px;overflow:hidden"><div class="group/carousel" style="position:relative">
  <div><div class="slider" style="display:flex;gap:20px;transition:transform .3s">""" + "".join(
    f'<div class="slider-slide"><a class="tile" href="/en/player/episodes/{i}" aria-label="S{i}"></a></div>' for i in range(12)) + """</div></div>
  <div style="position:absolute;left:0;top:0;bottom:0"><div id="prev" style="width:40px;height:300px"></div></div>
  <div style="position:absolute;right:0;top:0;bottom:0"><div id="next" style="width:40px;height:300px"></div></div></div></div>
<script>let armed = false, page = 0; addEventListener("mousemove", (e) => { armed ||= e.clientX > innerWidth - 60; });
  const go = (d) => { if (!armed) return; page = Math.max(0, page + d); document.querySelector(".slider").style.transform = `translateX(${-1400 * page}px)`; };
  next.onclick = () => go(1); prev.onclick = () => go(-1);</script>"""

# More of any website: a #section link, a search box whose suggestions close when it loses its focus, a
# form's buttons beside the box, and (below) a sign-in dialog over a page, and a page that scrolls its <body>.
WEB = STYLE + """<div style="padding:100px 0 0 600px"><a href="/above">Above</a></div>
<div style="padding:20px 40px 0;display:flex;gap:20px"><input id="q" aria-label="Search" style="width:500px">
  <input type="submit" value="Go" aria-label="Go" style="width:80px"><input type="submit" value="Lucky" aria-label="Lucky" style="width:80px"></div>
<div id="sugg" role="listbox" hidden style="margin-left:40px;width:300px"><div role="option" tabindex="-1" id="s1">pi 5</div><div role="option" tabindex="-1">pi 4</div></div>
<a href="#far" style="display:block;margin:200px 40px 0;width:200px">Jump</a><p style="height:3000px"></p><p id="far">Far down</p><p style="height:1000px"></p>
<script>q.onfocus = () => { sugg.hidden = false; }; q.onblur = () => { sugg.hidden = true; };
  window.picked = ""; sugg.onclick = (e) => { picked = e.target.textContent; };</script>"""
DIALOG = STYLE + """<div style="padding:100px 40px">""" + "".join(f'<a href="/s{i}" style="display:block;height:100px">Story {i}</a>' for i in range(10)) + """</div>
<div aria-modal="true" role="dialog" style="position:fixed;inset:0;background:rgba(0,0,0,.6);display:grid;place-items:center">
  <div><button>Accept</button> <button>Settings</button></div></div>"""
BODY_SCROLLS = """<style>html { overflow: hidden; height: 100%; } body { height: 100%; overflow: auto; margin: 0; }</style>
<a href="/top" style="display:block;margin:200px 40px">Top</a><p style="height:4000px"></p><a href="/bottom">Bottom</a>"""

def run(page, url, html):
    page.context.unroute("**/*")
    page.context.route("**/*", lambda route: route.fulfill(body=html, content_type="text/html") if route.request.url == url else route.abort())
    page.goto(url)
    page.wait_for_timeout(300)


def press(page, *keys):
    for k in keys:
        page.keyboard.press(k)
        page.wait_for_timeout(450)  # smooth scrolls settle
    return page.evaluate("(() => { const t = window.tvHighlight; return t && (t.getAttribute('aria-label') || t.getAttribute('data-testid') || t.innerText || t.getAttribute('href')); })()")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport={"width": 1920, "height": 1080}).new_page()
        here = os.path.join(os.path.dirname(__file__), "..", "..", "inject")
        page.add_init_script(path=os.environ.get("KEYBOARD", os.path.join(here, "keyboard.js")))  # the TV's order: the keyboard gets keys first
        page.add_init_script(path=LAYER)
        page.add_init_script(path=os.path.join(here, "pointer.js"))  # the pointer's ring
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        run(page, "https://play.hbomax.com/", HBO)
        assert press(page, "ArrowDown") == "play_button"          # the page's first thing: not the menu bar, the full-screen link or player box
        assert press(page, "ArrowUp") in ("slide_out_nav_menuButton", "HBO")  # the bar is up there
        assert press(page, "ArrowDown") == "play_button"
        assert press(page, "ArrowDown") == "a0_tile"
        assert press(page, *["ArrowRight"] * 6) == "a6_tile"
        assert page.evaluate("document.querySelector('[data-testid=tileList]').scrollLeft") > 0  # the row scrolled it in
        assert page.evaluate(f"scrollBy(0, 150), {RING_ON_HIGHLIGHT}")  # the page moves without a key: the ring with it, at once
        assert page.evaluate(f"{RING}.style.borderRadius") == "21px"  # the picture's corners (12 px), 9 px out
        assert page.evaluate("document.activeElement === document.body")  # a poster doesn't take the site's focus (HBO's work on it)
        # Once still, nothing runs every frame (a look twice a second: about 2 frames asked for a second).
        assert page.evaluate("""new Promise((ok) => setTimeout(() => { let n = 0; const o = window.requestAnimationFrame;
          window.requestAnimationFrame = (cb) => (n++, o(cb)); setTimeout(() => ok(n), 1000); }, 1200))""") <= 4
        assert press(page, "ArrowDown") == "b6_tile" and press(page, "ArrowUp") == "a6_tile"
        assert press(page, "ArrowUp") in ("play_button", "myList_button")  # the nearest row, not the mute button or header
        assert press(page, "ArrowRight") == "myList_button" and page.evaluate(f"{RING}.style.borderRadius") == "50%"  # a round ring
        # A banner that rotates hides the highlighted button, its next slide's sits a line lower: the highlight goes there.
        page.evaluate("""document.querySelector('[data-testid=myList_button]').style.display = 'none';
          document.querySelector('section').insertAdjacentHTML('beforeend', '<button aria-label="next slide" ' +
            'style="position:absolute;left:330px;top:700px;width:60px;height:60px">+</button>')""")
        page.wait_for_timeout(1200)
        assert press(page) == "next slide" and page.evaluate(RING_ON_HIGHLIGHT)
        # A held arrow (the remote repeats it 30 times a second) moves a TV app's pace, not one poster per repeat.
        assert press(page, "ArrowDown") == "a1_tile" and press(page, "ArrowLeft") == "a0_tile"
        for _ in range(30):
            page.keyboard.press("ArrowRight")
            page.wait_for_timeout(33)
        page.wait_for_timeout(500)
        held = int(press(page).split("_")[0][1:])
        assert 3 <= held <= 10, held
        # Looked up while resting, where things are is thrown away once the page scrolls or changes.
        assert press(page, "ArrowLeft") == f"a{held - 1}_tile"
        page.wait_for_timeout(1500)
        page.evaluate("scrollBy(0, 400)")
        below = press(page, "ArrowDown")
        assert below.startswith("b") and page.evaluate(RING_ON_HIGHLIGHT)  # the row below as it is now, not as it was
        page.wait_for_timeout(1500)
        page.evaluate("""tvHighlight.insertAdjacentHTML('afterend', '<a class="tile" data-testid="new_tile" href="/movie/new"></a>')""")
        assert press(page, "ArrowRight") == "new_tile"
        run(page, "https://play.hbomax.com/", HBO)
        assert press(page, "ArrowDown", "ArrowDown", "ArrowLeft") == "Home"  # row start: the menu, on this page
        assert press(page, "ArrowDown") == "Series"
        assert press(page, "Alt+ArrowLeft") == "a0_tile" and not page.query_selector("[data-testid=slideOutMenu]")  # Back closes it
        assert page.evaluate("fetch('https://telegraph.prd.api.hbomax.com/events', {method: 'POST'}).then((r) => r.json())") == {}
        assert page.evaluate("document.createElement('video').play().then(() => 'played', (e) => e.name)") == "NotAllowedError"

        run(page, "https://play.hbomax.com/", SPA)
        assert press(page, "ArrowDown", "ArrowDown", "ArrowRight", "ArrowRight") == "b2_tile"
        page.keyboard.press("Enter")
        page.wait_for_timeout(100)
        assert press(page, "ArrowDown") == "Play"  # a new page starts afresh at once, not from where the poster was
        press(page, "Alt+ArrowLeft")
        page.wait_for_timeout(1800)
        # Back: the same poster wherever it went, in the row it was in, not the show page's link to it
        assert page.evaluate("window.tvHighlight?.dataset.testid") == "b2_tile"

        # Under the player, Lottie's icon loop gets 4 frames a second while the remote rests; all of them after a key.
        run(page, "https://play.hbomax.com/video/watch/x", STYLE + "<p>player</p>")
        lottie = """new Promise((ok) => { let n = 0; (0, eval)("//# sourceURL=chunk-lottie.js\\nwindow.loop = (f) => requestAnimationFrame(f)");
          const tick = () => { n++; loop(tick); }; loop(tick); setTimeout(() => ok(n), 1000); })"""
        page.wait_for_timeout(5200)
        assert page.evaluate(lottie) <= 6
        assert page.evaluate("""new Promise((ok) => { let ran = 0; const id = loop(() => ran++); cancelAnimationFrame(id);
          setTimeout(() => ok(ran), 600); })""") == 0  # cancelled means cancelled
        page.keyboard.press("Space")
        assert page.evaluate(lottie) >= 30

        # The player's own controls: Up or Down brings them up, the arrows go between them, OK presses one.
        run(page, "https://play.hbomax.com/video/watch/x", PLAYER_UI)
        assert press(page, "ArrowRight") is None and page.evaluate("siteKeys") == "A"  # controls down: Right is the site's (seek)
        assert press(page, "ArrowDown") == "Pause"  # on screen and on top: not the footer under the show
        assert press(page, "ArrowRight", "ArrowRight", "ArrowRight") == "Audio and Subtitle Settings"  # not Full Screen (the TV is)
        assert press(page, "ArrowUp") == "Timeline"
        page.evaluate("siteKeys = ''")
        assert press(page, "ArrowRight") == "Timeline" and page.evaluate("siteKeys") == "A"  # a timeline's Left and Right are its seeking
        press(page, "Enter")
        assert page.evaluate("[v.paused, timeline.value]") == [True, "51"]  # OK pauses (no click at a made-up spot)
        page.evaluate("v.play()")
        assert press(page, "ArrowDown") == "Skip back 10 seconds"  # under the timeline's left end
        assert press(page, "ArrowRight", "ArrowRight", "ArrowRight") == "Audio and Subtitle Settings"
        page.keyboard.press("Enter")
        page.wait_for_timeout(600)
        assert press(page) == "Off"  # its menu opened over it: the highlight went where the site put its focus
        assert press(page, "ArrowDown") == "English CC"
        press(page, "Enter")
        assert page.evaluate("cc") == "English CC"
        press(page, "Alt+ArrowLeft")  # Back: the menu and the controls go, the show stays
        assert page.evaluate("[location.pathname, panel.className, window.tvHighlight]") == ["/video/watch/x", "", None]
        assert press(page, "ArrowDown") == "Pause"
        press(page, "Enter")
        assert page.evaluate("v.paused") and page.evaluate("""[...document.querySelectorAll('div')].find((d) => d.style.zIndex === '2147483646').style.display""") == "none"  # theirs show it
        page.evaluate("v.play()")
        assert press(page, "ArrowDown", "ArrowRight") == "Skip ahead 10 seconds"
        page.wait_for_timeout(4500)  # nobody touches the remote: the controls fade away, and the highlight with them
        assert page.evaluate("window.tvHighlight") is None
        press(page, "Enter")  # OK pauses again, it doesn't press the button the highlight was on
        assert page.evaluate("[v.paused, skips]") == [True, 0]
        run(page, "https://www.disneyplus.com/play/x", SHADOW_PLAYER)
        assert press(page, "ArrowDown") == "Pause" and press(page, "ArrowRight") == "Settings"  # inside web components
        press(page, "Alt+ArrowLeft")
        assert page.evaluate("[location.pathname, window.tvHighlight]") == ["/play/x", None]

        run(page, "https://www.disneyplus.com/browse/entity-x", DISNEY)
        assert press(page, "ArrowDown") == "PLAY"
        assert press(page, "ArrowDown") == "SUGGESTED"            # the tab, not the bar around it
        assert press(page, "ArrowRight") == "DETAILS"             # though the site keeps it out of the Tab order
        assert press(page, "ArrowDown") == 'Tile a0 "quoted"'
        # Its own highlight shows (the site's focus, as after a key), not our ring
        assert page.evaluate(f"document.activeElement === tvHighlight && tvHighlight.matches(':focus-visible') && {RING}.style.display === 'none'")
        assert press(page, "ArrowDown") == 'Tile b0 "quoted"'     # not the caption under the tile
        assert page.evaluate("""new Promise((ok) => { const x = new XMLHttpRequest();
          x.open('GET', 'https://disney.playback.edge.bamgrid.com/v2/media/1'); x.onloadend = () => ok(x.status); x.send(); })""") == 0
        assert page.evaluate("fetch('https://log.go.com/log').then((r) => r.status)") == 200

        run(page, "https://www.crunchyroll.com/", CRUNCHY_HOME)
        assert page.evaluate("document.getAnimations().length") == 0  # the placeholders hold still
        assert page.evaluate("document.documentElement.style.zoom") == "1.25"  # couch-sized text
        run(page, "https://www.crunchyroll.com/watch/x/y", CRUNCHY_WATCH)
        page.wait_for_timeout(600)
        assert page.evaluate("document.documentElement.style.zoom") == ""  # not on the player: it sizes itself to the screen
        assert page.evaluate("""[[2, 2], [innerWidth - 2, innerHeight - 2]].every(([x, y]) =>
          document.elementFromPoint(x, y)?.closest('.video-player-wrapper'))""")  # the player covers the screen, menu and all
        page.evaluate("show.play()")
        page.wait_for_timeout(300)
        paused = "show.paused"
        bar = """(() => { const b = [...document.querySelectorAll('div')].find((d) => d.style.zIndex === '2147483646');
          return b.style.display === 'block' && b.innerText.replace(/\\s+/g, ' ').trim(); })()"""
        assert press(page, "Enter") is None and page.evaluate(paused)  # OK pauses
        assert page.evaluate(bar).startswith("0:0")  # and says where (a live stream: no time left)
        press(page, "Enter")
        assert not page.evaluate(paused) and page.evaluate(bar) is False  # and plays, the bar gone
        press(page, "MediaPlayPause")
        assert page.evaluate(paused) and page.evaluate(bar)  # the remote's play/pause key too
        press(page, "MediaPlayPause")
        assert not page.evaluate(paused)
        page.wait_for_timeout(1600)
        page.evaluate("show.pause()")  # the site pausing by itself (the credits): its own screen, no bar
        page.wait_for_timeout(300)
        assert page.evaluate(paused) and page.evaluate(bar) is False
        page.evaluate("show.play()")
        page.focus("#skip")
        press(page, "Enter")
        assert page.evaluate("skipped") == 1 and not page.evaluate(paused)  # a focused button gets OK instead
        press(page, "ArrowRight")
        assert page.evaluate("document.activeElement.id") == "skip"  # the player keeps the arrows (no highlight moving)
        page.evaluate("document.querySelector('x-next').shadowRoot.querySelector('button').focus()")
        press(page, "Enter")
        assert page.evaluate("window.nexted") == 1 and not page.evaluate(paused)  # one inside a web component too

        run(page, "https://www.paramountplus.com/shows/x/", STICKY)
        assert press(page, "ArrowDown") == "Add to My Stuff"      # the sticky bar is page, not a pinned menu
        assert press(page, "ArrowRight") == "WATCH NOW"
        assert press(page, "ArrowDown", "ArrowDown") == "Pb1"     # past the disabled row titles
        page.add_style_tag(content="* { box-sizing: border-box; }")
        assert page.evaluate("document.documentElement.style.zoom") == "1.25" and press(page, "ArrowRight") == "Pb2"
        assert page.evaluate(RING_ON_HIGHLIGHT)
        assert press(page, "ArrowUp", "ArrowUp") in ("Add to My Stuff", "WATCH NOW")
        assert press(page, "ArrowUp") in ("Home", "Movies")       # the menu bar last
        zoom = "document.documentElement.style.zoom"
        assert page.evaluate(f"history.pushState({{}}, '', '/shows/video/x/'), {zoom}") == ""  # the player at once
        assert page.evaluate(f"new Promise((ok) => {{ addEventListener('popstate', () => ok({zoom}), {{ once: true }}); history.back(); }})") == "1.25"

        # Any other website: the highlight too, the site's own zoom kept
        run(page, "https://www.example.org/", GENERIC)
        assert press(page, "ArrowDown") == "First" and page.evaluate("document.documentElement.style.zoom") == "1.5"
        assert page.evaluate(RING_ON_HIGHLIGHT)
        assert press(page, "ArrowRight") == "Search" and page.evaluate("document.activeElement.id") == "q"  # a text box takes the focus
        page.keyboard.press("ArrowDown")
        assert page.evaluate("document.activeElement.id") != "q"  # and lets go at once: it would keep the next arrows and OK
        assert press(page) == "Season"
        press(page, "Enter")
        assert press(page, "ArrowDown") == "S1" and press(page, "ArrowDown") == "S2"
        assert page.evaluate("!list.hidden")  # the dropdown keeps its focus, so it stays open
        assert press(page, "ArrowDown") == "S2" and page.evaluate("scrollY") > 300  # the next link is screens away: a step towards it
        for _ in range(6):
            press(page, "ArrowDown")
        assert press(page) == "Far"
        # The pointer moving (the phone's touchpad): the highlight goes; an arrow brings it back from where it was
        page.mouse.move(400, 400)
        page.mouse.move(420, 430)
        assert press(page) is None
        cursor = "getComputedStyle(document.elementFromPoint(420, 430)).cursor"
        assert page.evaluate(cursor).startswith('url("data:image/svg+xml')  # the pointer: a ring big enough for the couch
        assert press(page, "ArrowUp") == "S2"
        # Not in YouTube's TV app: it has its own
        run(page, "https://www.youtube.com/tv", STYLE + "<a href='/x'>x</a>")
        assert page.evaluate("'tvHighlight' in window") is False

        run(page, "https://shahid.mbc.net/en", SHAHID)
        assert press(page, "ArrowDown", *["ArrowRight"] * 6) == "S6"
        press(page, "ArrowRight")
        page.wait_for_timeout(500)
        assert press(page) == "S7" and page.evaluate("page") == 1  # at the row's end it slid the next posters in

        run(page, "https://www.example.org/", WEB)
        assert press(page, "ArrowDown", "ArrowDown") == "Go" and press(page, "ArrowRight") == "Lucky"  # a form's button isn't a text box
        assert press(page, "ArrowLeft", "ArrowLeft") == "Search" and press(page, "ArrowDown") == "pi 5"  # its suggestion
        assert page.evaluate("!sugg.hidden")  # the box kept its focus, so its list stayed
        press(page, "Enter")
        assert page.evaluate("[picked, window.tvKeyboard ?? null]") == ["pi 5", None]  # OK picked it (no keyboard instead)
        page.evaluate("document.activeElement.blur()")
        assert press(page, "ArrowDown") == "Jump"
        press(page, "Enter")
        page.wait_for_timeout(1300)
        assert page.evaluate("[location.hash, scrollY > 2000]") == ["#far", True]  # the jump stays (not taken for a Back)

        run(page, "https://www.example.org/", DIALOG)
        assert press(page, "ArrowDown") == "Accept" and press(page, "ArrowRight") == "Settings"  # the dialog first, the page under it out of reach
        run(page, "https://www.example.org/", BODY_SCROLLS)
        assert press(page, "ArrowDown") == "Top"
        press(page, "ArrowDown")
        assert page.evaluate("document.body.scrollTop") > 300  # a step towards the far link, in the box that scrolls

        assert not errors, errors
        browser.close()
    print("sites-tv ok")


main()

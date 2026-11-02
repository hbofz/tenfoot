"""Checks inject/keyboard.js (the TV's on-screen keyboard) with real key presses in Chromium, with
sites.js loaded after it as on the TV, on pages served at a streaming site's address.
Run: python3 tests/browser/test_keyboard.py (needs `pip install playwright && playwright install chromium`)."""
import os
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(__file__)
KEYBOARD = os.environ.get("KEYBOARD", os.path.join(HERE, "..", "..", "inject", "keyboard.js"))
LAYER = os.path.join(HERE, "..", "..", "inject", "sites.js")
STYLE = """<style>body { margin: 0; background: #000; color: #fff; font: 20px sans-serif; }
  .row { display: flex; gap: 20px; padding: 20px 60px; } .tile { flex: none; width: 260px; height: 300px; background: #333; display: block; }</style>"""

# A search page whose box the site focuses itself, results under it, a search that goes on Enter's keyup.
SEARCH = STYLE + """<input id="q" type="search" placeholder="Search titles" autofocus style="margin:120px 60px 0;width:600px;height:60px">
<div class="row">""" + "".join(f'<a class="tile" href="/movie/{i}" aria-label="R{i}"></a>' for i in range(4)) + """</div>
<script>q.focus(); history.replaceState(null, "", location.href);  // while the page is still loading, as Paramount+ does
  window.keyups = 0; q.addEventListener("keyup", (e) => e.key === "Enter" && keyups++);
  window.searched = 0; q.addEventListener("keydown", (e) => e.key === "Enter" && searched++);</script>"""
# A sign-in form: nothing focused until the highlight gets there.
SIGN_IN = STYLE + """<form id="f" style="margin:120px 60px"><input id="user" name="username" style="width:600px;height:60px"></form>
<script>window.sent = 0; f.onsubmit = (e) => { e.preventDefault(); sent++; };</script>"""


# Sign-in with two boxes and a button that isn't a submit button (the site's own click handler sends it).
TWO_BOXES = STYLE + """<form id="f" style="margin:120px 60px"><input id="user" autofocus style="width:600px;height:60px">
  <input id="pass" type="password" style="width:600px;height:60px"><button type="button" id="go">Sign in</button></form>"""
# A remembered email; a PIN of boxes where each digit moves the cursor on.
EMAIL = STYLE + """<input id="mail" type="email" value="me@x.com" autofocus style="margin:120px 60px;width:600px;height:60px">"""
PIN = STYLE + """<div style="margin:120px 60px">""" + "".join(f'<input id="p{i}" maxlength="1" style="width:60px;height:60px">' for i in range(4)) + """</div>
<script>p0.focus(); document.querySelectorAll("input").forEach((b, i, all) => b.oninput = () => all[i + 1]?.focus());</script>"""
# A search page that puts the cursor back in its box when you come back to it (Paramount+).
SPA_SEARCH = STYLE + """<div id="app"></div><script>
  const search = () => { app.innerHTML = '<input id="q" style="margin:120px 60px 0;width:600px;height:60px"><div class="row">' +
    [0, 1, 2, 3].map((i) => `<a class="tile" href="/movie/${i}" aria-label="R${i}"></a>`).join("") + "</div>"; q.focus(); };
  search();
  addEventListener("click", (e) => { const a = e.target.closest("a"); if (!a) return; e.preventDefault(); history.pushState({}, "", a.href);
    app.innerHTML = '<div style="height:300px"></div><button style="margin-left:60px;width:200px;height:60px">Play</button>'; });
  addEventListener("popstate", () => setTimeout(search, 300));
</script>"""


def run(page, url, html, headers=None):
    page.context.unroute("**/*")
    page.context.route("**/*", lambda route: route.fulfill(body=html, content_type="text/html", headers=headers) if route.request.url == url else route.abort())
    page.goto(url)
    page.wait_for_timeout(400)


def press(page, *keys):
    for k in keys:
        page.keyboard.press(k)
        page.wait_for_timeout(120)
    return page.evaluate("window.tvKeyboard && window.tvKeyboard.key")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport={"width": 1920, "height": 1080}).new_page()
        page.add_init_script(path=KEYBOARD)
        page.add_init_script(path=LAYER)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        value = lambda: page.evaluate("q.value")

        run(page, "https://play.hbomax.com/search", SEARCH)
        assert press(page) == "a"  # the site put the cursor in its box: the keyboard is up, on "a"
        press(page, "Enter", "ArrowRight", "Enter")
        assert value() == "ab"
        assert press(page, "ArrowDown", "ArrowDown") == "⇧"  # the actions under the letters
        press(page, "Enter", "ArrowUp", "ArrowUp", "Enter")  # shift, then "b": one capital
        assert value() == "abB" and press(page) == "b"
        assert press(page, "ArrowDown", "ArrowDown", "ArrowRight", "ArrowRight", "ArrowRight") == "⌫"
        press(page, "Enter")
        assert value() == "ab"
        assert press(page, "ArrowLeft", "ArrowLeft") == "123"
        press(page, "Enter")
        assert press(page, "ArrowUp", "ArrowUp") == "3"  # numbers and symbols
        press(page, "Enter")
        assert value() == "ab3" and page.evaluate("keyups") == 0  # the site's Enter-keyup search never saw OK
        page.keyboard.insert_text("x")  # typed from the phone
        page.wait_for_timeout(100)
        assert page.evaluate("[...document.querySelectorAll('div')].find((d) => d.shadowRoot).shadowRoot.querySelector('.text').textContent") == "ab3x"
        press(page, "Enter")  # the phone's Enter (a real Enter key, like OK): send what it typed
        assert page.evaluate("[q.value, searched, window.tvKeyboard]") == ["ab3x", 1, None]
        press(page, "Enter")  # OK on the box again
        page.evaluate("searched = 0")
        press(page, "Alt+ArrowLeft")
        assert page.evaluate("window.tvKeyboard") is None and page.evaluate("location.pathname") == "/search"  # Back: the keyboard only
        press(page, "ArrowDown")
        assert page.evaluate("tvHighlight.getAttribute('aria-label')") == "R0" and page.evaluate("window.tvKeyboard") is None
        press(page, "ArrowUp")  # the highlight passes over the box: no keyboard yet
        assert page.evaluate("tvHighlight.id") == "q" and page.evaluate("window.tvKeyboard") is None
        assert press(page, "Enter") == "a"  # OK on it opens it
        press(page, "ArrowDown", "ArrowDown", "ArrowDown")  # off the bottom: on to the results
        assert page.evaluate("window.tvKeyboard") is None and page.evaluate("tvHighlight.getAttribute('aria-label')") == "R0"
        press(page, "ArrowUp", "Enter", "ArrowDown", "ArrowDown", *["ArrowRight"] * 4)
        assert press(page) == "Done" and page.evaluate("searched") == 0
        press(page, "Enter")
        page.wait_for_timeout(300)
        assert page.evaluate("[searched, window.tvKeyboard]") == [1, None]  # Done: the site's search goes, the keyboard stays away

        # A site that zooms its page after its box got the cursor (Paramount+): the keyboard keeps its size.
        run(page, "https://www.paramountplus.com/search/", SEARCH)
        assert page.evaluate("""(() => { const h = [...document.querySelectorAll('div')].find((d) => d.shadowRoot);
          return [document.documentElement.style.zoom, +h.style.zoom * 1.25]; })()""") == ["1.25", 1]

        run(page, "https://play.hbomax.com/signin", SIGN_IN)
        assert page.evaluate("window.tvKeyboard") is None
        press(page, "ArrowDown")
        assert press(page, "Enter") == "a"
        press(page, "Enter", "ArrowDown", "ArrowDown")
        for _ in range(4):
            press(page, "ArrowRight")
        assert press(page) == "Done"
        press(page, "Enter")
        assert page.evaluate("[sent, user.value, window.tvKeyboard]") == [1, "a", None]  # sent, and the keyboard put away

        run(page, "https://play.hbomax.com/signin", TWO_BOXES)
        press(page, "Enter", *["ArrowDown"] * 2, *["ArrowRight"] * 4)
        assert press(page) == "Done"
        press(page, "Enter")
        page.wait_for_timeout(300)
        assert page.evaluate("[location.pathname + location.search, user.value]") == ["/signin", "a"]  # not sent as a link with the password in it

        # A site that bans innerHTML (Trusted Types, like Google's sign-in): the keyboard still comes up.
        run(page, "https://play.hbomax.com/search", SEARCH, {"Content-Security-Policy": "require-trusted-types-for 'script'"})
        assert press(page) == "a"

        run(page, "https://play.hbomax.com/account", EMAIL)
        press(page, "Enter")
        assert page.evaluate("mail.value") == "me@x.coma"  # typed at the end, though email boxes can't say where the cursor is

        run(page, "https://play.hbomax.com/pin", PIN)
        press(page, *["ArrowDown"] * 2, "ArrowRight", "Enter", "ArrowUp", "ArrowUp", "Enter")  # 123, then "3": the cursor moves to the next box
        assert page.evaluate("[p0.value, document.activeElement.id]") == ["3", "p1"] and press(page) == "3"  # still on the numbers

        run(page, "https://play.hbomax.com/search", SPA_SEARCH)
        press(page, "Alt+ArrowLeft", "ArrowDown", "ArrowRight", "ArrowRight")
        assert page.evaluate("tvHighlight.getAttribute('aria-label')") == "R2"
        press(page, "Enter")
        page.wait_for_timeout(300)
        page.evaluate("""(() => { const h = [...document.querySelectorAll('div')].find((d) => d.shadowRoot); window.opens = 0;
          new MutationObserver(() => h.style.display === 'block' && opens++).observe(h, { attributes: true }); })()""")
        press(page, "Alt+ArrowLeft")
        page.wait_for_timeout(1200)  # the site redraws its search page and puts the cursor in the box
        assert page.evaluate("[opens, tvHighlight && tvHighlight.getAttribute('aria-label')]") == [0, "R2"]  # Back to the result, no keyboard, not even for a moment

        assert not errors, errors
        browser.close()
    print("keyboard-tv ok")


main()

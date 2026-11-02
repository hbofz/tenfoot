// Injected with youtube.js, before sites.js. The TV's on-screen keyboard, like Apple TV's: a
// text field on any site (a search box, a sign-in form) is typed into with the remote's arrows and
// OK. Apple TV shows this grid with remotes other than its own touch remote: a D-pad reaches any key
// in a few presses. Not in YouTube's TV app, which has its own.
(() => {
  if (window !== top || /(^|\.)youtube\.com$/.test(location.hostname) && location.pathname.startsWith("/tv")) return;

  const ROWS = { abc: ["abcdefghijklm", "nopqrstuvwxyz"], "123": ["1234567890.-_", "@'&!?,:/#+()*"] };
  const ACTIONS = [["shift", "⇧", 2], ["mode", "123", 2], ["space", "space", 5], ["delete", "⌫", 2], ["done", "Done", 2]];
  const COLS = 13;
  const FIELD = "input:not([type]), input[type=text], input[type=search], input[type=email], input[type=url], " +
                "input[type=password], input[type=tel], input[type=number], textarea";

  let field = null;  // the text field being typed into; the keyboard is open while it's set
  let mode = "abc", upper = false;
  let row = 0, col = 0;  // the focused key: its row (0-1 characters, 2 the actions) and column
  let moved = -Infinity;  // when an arrow last moved the page's highlight (sites.js focuses what it highlights)
  let ate = null;  // a key the keyboard took: its release too (a site's search may go on Enter's keyup)

  // Its own shadow root, so a site's styles can't reach it.
  const host = document.createElement("div");
  host.style.cssText = "position: fixed; left: 0; right: 0; bottom: 0; z-index: 2147483645; display: none;";
  const root = host.attachShadow({ mode: "open" });
  const css = document.createElement("style");
  css.textContent = `
    .panel { margin: 0 auto 48px; width: 1360px; box-sizing: border-box; padding: 36px 44px 40px; border-radius: 44px;
      background: rgba(30, 30, 34, .82); backdrop-filter: blur(36px) saturate(1.4); color: #fff;
      box-shadow: 0 30px 90px rgba(0, 0, 0, .55), inset 0 1px 0 rgba(255, 255, 255, .14); }
    .label { font-size: 24px; font-weight: 600; opacity: .55; height: 30px; }
    .text { font-size: 48px; font-weight: 600; height: 64px; margin: 6px 0 26px; white-space: nowrap; overflow: hidden;
      display: flex; align-items: center; justify-content: flex-end; }
    .text span { flex: none; }
    /* the caret's auto margin keeps the text on the left until it outgrows the line; then its end shows */
    .text i { flex: none; width: 4px; height: 54px; margin: 0 auto 0 3px; border-radius: 2px; background: #fff; }
    .text .empty { opacity: .4; margin-right: auto; }
    .text:has(.empty) i { order: -1; margin: 0 6px 0 0; }
    .keys { display: grid; grid-template-columns: repeat(${COLS}, 1fr); gap: 10px; }
    .key { height: 88px; border-radius: 18px; display: flex; align-items: center; justify-content: center;
      font-size: 42px; color: rgba(255, 255, 255, .86); transition: transform .12s ease-out, background-color .12s ease-out; }
    .key.small { font-size: 30px; font-weight: 600; }
    .key.on { background: #fff; color: #111; transform: scale(1.12); box-shadow: 0 14px 34px rgba(0, 0, 0, .45); }
    .key.lit { color: #fff; background: rgba(255, 255, 255, .16); }
  `;
  const panel = document.createElement("div");
  panel.className = "panel";
  const [label, text, keys] = ["label", "text", "keys"].map((c) => panel.appendChild(Object.assign(document.createElement("div"), { className: c })));
  root.append(css, panel);

  // The keys of row r: [what it does, what it shows, first column, columns wide].
  const rowKeys = (r) => {
    if (r === 2) {
      let c = 0;
      return ACTIONS.map(([act, face, w]) => [act, act === "mode" ? (mode === "abc" ? "123" : "abc") : face, (c += w) - w, w]);
    }
    return [...ROWS[mode][r]].map((ch, c) => [ch, upper ? ch.toUpperCase() : ch, c, 1]);
  };
  const here = (ks) => ks.findIndex(([, , c, w]) => col >= c && col < c + w);
  const at = () => rowKeys(row)[here(rowKeys(row))];

  let built = "";  // the keys drawn (letters or numbers, which case); moving only moves the white key
  const draw = () => {
    if (built !== mode + upper) {
      built = mode + upper;
      keys.replaceChildren(...[0, 1, 2].flatMap((r) => rowKeys(r).map(([act, face, c, w]) => {
        const k = document.createElement("div");
        k.className = "key" + (r === 2 ? " small" : "") + (act === "shift" && upper ? " lit" : "");
        k.style.gridColumn = `${c + 1} / span ${w}`;
        k.textContent = face;
        k.place = [r, c, w];
        return k;
      })));
    }
    for (const k of keys.children) {
      const [r, c, w] = k.place;
      k.classList.toggle("on", r === row && col >= c && col < c + w);
    }
    const v = field.value, secret = field.type === "password";
    const shown = document.createElement("span");
    shown.textContent = v ? (secret ? "•".repeat(v.length) : v) : field.placeholder || "";
    if (!v) shown.className = "empty";
    text.replaceChildren(shown, document.createElement("i"));
    label.textContent = (field.getAttribute("aria-label") || field.labels?.[0]?.textContent || "").split(/[,:]/)[0].trim() ||
                        (field.type === "search" || /search/i.test(field.name + field.placeholder) ? "Search" : "");
  };

  // Typed the way a person's typing arrives, so a site's own code (React's) sees it as such.
  const setValue = (v) => {
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(field), "value").set.call(field, v);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  };
  const type = (s) => document.execCommand("insertText", false, s) || setValue(field.value + s);
  const press = (act) => {
    if (act === "shift") upper = !upper;
    else if (act === "mode") mode = mode === "abc" ? "123" : "abc";
    else if (act === "space") type(" ");
    else if (act === "delete") document.execCommand("delete") || setValue(field.value.slice(0, -1));
    else if (act === "done") return done();
    else {
      type(upper ? act.toUpperCase() : act);
      upper = false;  // one capital, like a phone's shift
    }
    draw();
  };
  const done = () => {
    const f = field;
    close();
    // What Enter does: the site's own keys first (a search box searches on its keydown or keyup), then
    // a form's default button, or a form of one box sends itself.
    const key = (type) => new KeyboardEvent(type, { key: "Enter", code: "Enter", keyCode: 13, bubbles: true, cancelable: true, composed: true });
    const taken = !f.dispatchEvent(key("keydown"));
    f.dispatchEvent(key("keyup"));
    if (taken || !f.form) return;
    const b = [...f.form.elements].find((e) => e.type === "submit");
    if (b) b.click();
    else if (f.form.querySelectorAll(FIELD).length === 1) f.form.requestSubmit();
  };

  const open = (f) => {
    if (!field) mode = "abc", upper = false, row = 0, col = 0, built = "";
    field = f;
    try { f.setSelectionRange(f.value.length, f.value.length); } catch { getSelection().modify("move", "forward", "documentboundary"); }
    fit();
    host.style.display = "block";
    draw();
  };
  // The same size on every site: sites.js zooms some pages, sometimes after a site has already
  // put the cursor in its box (Paramount+).
  const fit = () => { host.style.zoom = 1 / (parseFloat(document.documentElement.style.zoom) || 1); };
  const close = () => {
    field = null;
    host.style.display = "none";
  };

  const isField = (el) => el?.matches?.(FIELD) && !el.disabled && !el.readOnly;
  const deep = (el) => { while (el?.shadowRoot?.activeElement) el = el.shadowRoot.activeElement; return el; };
  // A field the site puts the cursor in (a search page's box) opens it; one the highlight only passes
  // on its way somewhere opens on OK.
  addEventListener("focusin", (e) => {
    const el = e.composedPath()[0];
    if (isField(el) && el !== field && performance.now() - moved > 400) open(el);
  }, true);
  addEventListener("focusout", (e) => {
    if (e.composedPath()[0] === field) setTimeout(() => deep(document.activeElement) !== field && close(), 0);
  }, true);
  let busy = false, phoned = false;  // phoned: the phone typed since the last remote key
  addEventListener("input", (e) => { if (field && e.composedPath()[0] === field) { phoned ||= !busy; draw(); } }, true);  // typed from the phone

  addEventListener("popstate", () => { moved = Infinity; });  // Back: a page that focuses its box redrawn, not the user's doing
  addEventListener("keyup", (e) => {
    if (e.key !== ate) return;
    ate = null;
    e.preventDefault();
    e.stopImmediatePropagation();
  }, true);
  addEventListener("keydown", (e) => {
    if (!e.isTrusted) return;  // a site's own, or the Enter that Done sends
    ate = null;
    if (field && !field.isConnected) close();  // the site took its box away
    if (e.key.startsWith("Arrow")) phoned = false;
    if (!field) {
      moved = e.key.startsWith("Arrow") && !e.altKey ? performance.now() : -Infinity;
      const f = deep(document.activeElement);
      // (not with the highlight on something else: a search box's suggestion, which OK picks)
      if (e.key !== "Enter" || !isField(f) || window.tvHighlight && window.tvHighlight !== f) return;
      open(f);  // OK on a highlighted text field
    } else if (e.altKey && e.key === "ArrowLeft" || e.key === "Escape") {
      close();  // Back: the keyboard first, the page next time
    } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      const ks = rowKeys(row), i = here(ks) + (e.key === "ArrowRight" ? 1 : -1);
      if (ks[i]) col = ks[i][2];
      draw();
    } else if (e.key === "ArrowUp") {
      if (row > 0) row--, draw();
    } else if (e.key === "ArrowDown") {
      if (row === 2) {
        moved = performance.now();
        close();
        return;  // off the bottom: on to what's under the field (sites.js moves the highlight)
      }
      row++;
      draw();
    } else if (e.key === "Enter") {
      busy = true;
      phoned ? done() : press(at()[0]);  // the phone's Enter: send what it typed
      busy = false;
    } else if (e.key === "Backspace") {
      busy = true;
      press("delete");
      busy = false;
    } else return;  // anything else (a phone's typing) goes to the field as it is
    e.preventDefault();
    e.stopImmediatePropagation();
    ate = e.key;
  }, true);

  Object.defineProperty(window, "tvKeyboard", { get: () => field && { row, col, mode, upper, key: at()[1] } });  // for tests
  const start = () => {
    document.body.append(host);
    fit();  // a zoom set while the page loaded
    new MutationObserver(fit).observe(document.documentElement, { attributes: true, attributeFilter: ["style"] });
  };
  if (document.body) start();
  else document.addEventListener("DOMContentLoaded", start);
})();

// Injected with youtube-tv.js into every website the TV shows, apart from YouTube's TV app and the
// TV's own screens (both have their own highlight). None of the others has a TV web app, so make
// the desktop site work like one from the remote: the arrows jump a big highlight to the nearest
// thing to pick in that direction, OK picks it. The streaming sites below get their own rules on
// top. Players keep the site's own keys (space pauses, arrows seek and change volume), but OK
// pauses and plays, like a TV app.
(() => {
  // Per site: player = its player's pages (the address's path, and its #/route where the site keeps
  // its pages there: Jellyfin); slide = the buttons that slide a row of posters (clicked at
  // a row's end); skip = never highlighted; zoom = page zoom (1 where the site sizes itself by the
  // screen's width); menu = [button, panel, close button] of a slide-out menu that Left opens;
  // previews: false = trailers don't play by themselves (each one is a video decode on the Pi);
  // preview = what a self-playing trailer fetches; drop = analytics the DNS filter blocks (both
  // answered here, see below); css = the site's own fixes; ring: false = the site draws a TV
  // highlight of its own, shown instead of ours (off the player). Any other site: no player pages
  // (a video full screen still keeps its keys), and its own zoom.
  const SLIDERS = "[aria-label*=next i], [aria-label*=previous i]";  // a guess until each site is seen signed in
  const SITES = {
    "netflix.com": { player: /^\/watch/, slide: "[aria-label=Next], [aria-label=Previous], .handle" },  // logged out, logged in
    // its own highlight is its TV app's: the poster lifts, a white ring hugs it
    "disneyplus.com": { player: /\/play\//, slide: SLIDERS, zoom: 1, previews: false, ring: false,
                        preview: /^https:\/\/disney\.playback\.edge\.bamgrid\.com\//,
                        skip: "[data-testid=cw-set-item-metadata]",  // the caption under a Continue Watching poster
                        drop: /^https:\/\/(browser-intake-datadoghq\.com|([\w-]+\.)?cws\.conviva\.com|log\.go\.com|[\w-]+\.braze\.com|events\.launchdarkly\.com)\//,
                        // its start-up spinner keeps spinning, hidden under the app, a redraw every frame
                        css: "#bap-app-placeholder[aria-busy=false] { display: none !important; }" },
    "hbomax.com": { player: /\/video\/watch\//, zoom: 1, previews: false, drop: /^https:\/\/telegraph\./,
                    // the tiles' "..." menus, the row arrows (rows scroll by themselves), the banner's page dots and mute button
                    skip: "[data-testid=dropdownToggleButton], [aria-label*='titles in'], [data-testid^=pagination-dot], [data-testid=immersive-hero-audio-button]",
                    menu: ["[data-testid=slide_out_nav_menuButton]", "[data-testid=slideOutMenu]", "[data-testid=closeMenuButton]"] },
    "crunchyroll.com": { player: /\/watch\//,  // rows scroll by themselves
                         // the banner's arrows and page dots, the rows' arrows, the title link under each poster
                         // or episode, an episode's "..." menu
                         skip: "[aria-label^='Show slide'], [aria-label$=' Item'], [aria-label^='Scroll '], [class*=browse-card__title-link], " +
                               "[class*=playable-card__title-link], [class*=playable-card-more-options]",
                         // The grey placeholders of rows not loaded yet (459 on the home page) shimmer, and the
                         // banner's timer bar fills: each a redraw every frame, the Pi's whole renderer when idle.
                         // A promo bubble floats over the bottom corner, and a highlighted poster or episode opens
                         // a mouse hover card of more links over itself. The player fills the screen, like a TV app's,
                         // not the page under the site's menu.
                         css: "[class*=loading-animation]::after, [class*=loading-image]::after, [class*=hero-carousel__page-loader] " +
                              "{ animation: none !important; } div[class^='fab--'], [class*=browse-card__hover], [class*=playable-card__hover-info] " +
                              "{ display: none !important; } " +
                              "html[data-tv-player] .video-player-wrapper { position: fixed !important; inset: 0 !important; " +
                              "width: 100vw !important; height: 100vh !important; z-index: 2147483000 !important; }" },
    "paramountplus.com": { player: /\/(video|live-tv)\//, slide: SLIDERS, previews: false,  // shows and movies, live channels
                           // a row's "for <profile>" filter and the menu's other profiles (one OK and it's someone
                           // else's list), Keep Watching's Edit (removes shows from it)
                           skip: ".dropdown__filter button, .dropdown__filter a, .user-profiles-menu-dropdown a, .edit-carousel" },
    // A poster plays at once (OK on it starts the show). Rows slide with arrows that work only once a
    // mouse has moved over the page (see slide); the banner's trailer is a second video decode under the page.
    "shahid.mbc.net": { player: /\/player\//, slide: "div:has(> .slider) ~ div > div", zoom: 1, previews: false },
    "__JELLYFIN_HOST__": { player: /^\/web\/#\/video/, zoom: 1 },  // filled in from jellyfin_url
    // The Web tile's start: not the little "about this result" and ad buttons beside every result
    "google.com": { player: /$^/, zoom: null, skip: "[aria-label='About this result'], [aria-label*='Why this ad']" },
  };
  // Not in frames (the players are in the page itself) nor the TV's own pages (file:), nor YouTube's TV app.
  if (window !== top || !/^https?:$/.test(location.protocol) || /(^|\.)youtube\.com$/.test(location.hostname) && location.pathname.startsWith("/tv")) return;
  const site = Object.keys(SITES).find((d) => location.hostname === d || location.hostname.endsWith("." + d));
  const { player: PLAYER, slide: SLIDE, skip: SKIP, zoom: ZOOM = 1.25, menu: MENU, previews = true, preview: PREVIEW, drop: DROP,
          css: CSS = "", ring: RING = true } = SITES[site] ?? { player: /$^/, zoom: null };
  // The page we're on: its path, and its #/route on a site that keeps its pages there (not a #section).
  const page = () => location.pathname + (/^#!?\//.test(location.hash) ? location.hash : "");
  const ours = () => RING || PLAYER.test(page());  // our ring is the highlight (always on a player's controls)
  // Tabs, menu items and options count even when the site takes them out of the Tab order (Disney+'s
  // tab bars let only the chosen tab be focused); the bar around them is never the thing to pick.
  const NEVER = [SLIDE, SKIP, "[role=tablist]"].filter(Boolean).join(", ");
  const PICKABLE = "a[href], button, input, select, textarea, [role=button], [role=link], [role=tab], [role=menuitem], [role=option], " +
                   "[tabindex]:not([tabindex='-1'])";
  const CONTROLS = "a[href], button, input, select, textarea, [role=button], [role=link], [role=menuitem], [role=option], [role=tab], [role=slider]";
  const DIRS = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] };
  let cur = null, last = null;  // the highlighted element, and where it was (these sites re-render a lot)
  let sliding = false;  // a row is sliding in its next posters
  let before = null;  // what was highlighted before the slide-out menu opened
  let controls = false;  // on a player: its own controls are up, the highlight on one of them

  if (!previews) {  // only the player plays; a trailer asking to play is told no, as a browser's autoplay rules would
    const play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
      return PLAYER.test(page()) ? play.call(this) : Promise.reject(new DOMException("no trailers on the TV", "NotAllowedError"));
    };
    addEventListener("play", (e) => PLAYER.test(page()) || e.target.pause(), true);  // <video autoplay>
  }

  // Lottie (vector animation) draws a player's control icons every frame even while the controls
  // are hidden, and each frame makes the page lay itself out: over half a core under HBO's player.
  // There, once nobody has touched the remote for 5 s (the controls hide), it gets 4 frames a second.
  let touched = 0;
  addEventListener("keydown", () => { touched = performance.now(); }, true);
  addEventListener("pointermove", (e) => {
    touched = performance.now();
    // The pointer moving (the phone's touchpad, a mouse) picks now: the highlight goes until an arrow
    // brings it back, from where it was. (Not the still pointer the browser re-reports as a page scrolls under it.)
    if (e.isTrusted && (e.movementX || e.movementY) && cur && !controls) cur = null, wake(0);
  }, true);
  const raf = window.requestAnimationFrame, caf = window.cancelAnimationFrame;
  const held = new Map();  // our frame id -> its timer, then (negated) the frame it asked for
  let heldId = 1e9;  // apart from the browser's own ids
  window.requestAnimationFrame = function (cb) {
    if (!(PLAYER.test(page()) && performance.now() - touched > 5000 && /lottie/i.test(new Error().stack)))
      return raf.apply(this, arguments);
    const id = ++heldId;
    held.set(id, setTimeout(() => held.set(id, -raf.call(window, (t) => { held.delete(id); cb(t); })), 250));
    return id;
  };
  window.cancelAnimationFrame = function (id) {
    const h = held.get(id);
    if (h === undefined) return caf.apply(this, arguments);
    held.delete(id);
    h < 0 ? caf.call(window, -h) : clearTimeout(h);
  };

  // Requests answered on the Pi instead of going out. Analytics the DNS filter blocks (drop) are told
  // "delivered": a site that can't deliver them keeps every event and re-saves the lot on each new
  // one (HBO's queue reached 1.6 MB of JSON, rewritten per event, a third of the Pi's time on its
  // pages). A trailer's video (preview) is refused off the player page, so it never starts
  // downloading (Disney+ fetched 3 MB of trailer in 30 s for banners nobody watched).
  const fate = (url) => DROP?.test(url) ? "ok" : PREVIEW?.test(url) && !PLAYER.test(page()) ? "no" : null;
  if (DROP || PREVIEW) {
    const fetch0 = window.fetch;
    window.fetch = function (input) {
      const f = fate(input?.url ?? String(input));
      return f === "ok" ? Promise.resolve(new Response("{}", { headers: { "Content-Type": "application/json" } }))
        : f === "no" ? Promise.reject(new TypeError("Failed to fetch")) : fetch0.apply(this, arguments);
    };
    const FATE = Symbol("fate"), open0 = XMLHttpRequest.prototype.open, send0 = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url) {
      this[FATE] = fate(String(url));
      return open0.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function (body) {
      if (!this[FATE]) return send0.call(this, body);
      // Somewhere that answers at once without leaving the Pi: "{}", or a failed connection.
      open0.call(this, "GET", this[FATE] === "ok" ? "data:application/json,{}" : "https://0.0.0.0/");
      return send0.call(this);
    };
    const beacon0 = navigator.sendBeacon?.bind(navigator);
    if (beacon0) navigator.sendBeacon = (url, data) => fate(String(url)) === "ok" || beacon0(url, data);
  }

  // The highlight is its own layer over the page, so the rows of posters, which clip anything sticking
  // out, can't cut it off. It jumps to the next thing at once, like a TV app's, and lands with a little
  // settle drawn by the graphics chip (a glide drawn by the page lagged a busy page's every move). It
  // sits in the page, not on the screen, so a scroll carries it in step with what it rings; only what
  // moves on its own (a row sliding, a bar pinned to the screen, a site's own scrolling pane) is
  // followed by hand.
  const ring = document.createElement("div");
  ring.style.cssText = `position: absolute; left: 0; top: 0; z-index: 2147483647; pointer-events: none; display: none;
    box-sizing: border-box; border: 5px solid #fff; box-shadow: 0 0 0 6px rgba(0,0,0,.6), 0 0 36px rgba(255,255,255,.45);
    will-change: transform;`;
  let drawn = "", ringed = null, moored = false, until = 0, following = false, lost = [];  // ringed: what it's on; moored: held to the screen, not the page
  // The ring's corners: the highlighted thing's (a round button gets a round ring), else those of the
  // picture filling it (a poster link's), 9 px out like the ring. (z: the page's zoom, which the ring undoes.)
  const corners = (el, r, z) => {
    for (const e of [el, ...[...el.querySelectorAll("*")].slice(0, 40)]) {
      const c = getComputedStyle(e).borderTopLeftRadius, q = e === el ? r : e.getBoundingClientRect();
      if (parseFloat(c) && q.width > r.width - 6 && q.height > r.height / 2) return c.includes("%") ? c : `${parseFloat(c) * z + 9}px`;
    }
    return "9px";
  };
  const draw = () => {  // put the ring on the highlighted thing, where it is now
    const playing = PLAYER.test(page()) && !controls;  // no ring over the show, only on its controls
    const was = seen();
    // The site redrew it, or hid it (a banner that rotates: Disney+'s keeps a hidden copy per slide):
    // take what's in its place, or near it (the next slide's button sits a line higher or lower) once
    // it has faded in; given up on after 3 s.
    if (cur && was && !playing && !(cur.isConnected && (controls || cur.checkVisibility()))) {
      const x = was.left + was.width / 2, y = was.top + was.height / 2, d = (q) => Math.hypot(q.left + q.width / 2 - x, q.top + q.height / 2 - y);
      let el = pointAt(x, y)?.closest(PICKABLE);
      if (lost[0] !== cur) lost = [cur, performance.now(), 0];
      if ((!el || !usable(el) || controls && !control(el)) && performance.now() - lost[2] > 250 && (lost[2] = performance.now()))
        el = candidates().map((e) => [e, d(e.getBoundingClientRect())]).filter(([, n]) => n < 200).sort((a, b) => a[1] - b[1])
          .find(([e]) => usable(e) && (!controls || control(e)))?.[0];
      else if (el && !(usable(el) && (!controls || control(el)))) el = null;
      if (el || performance.now() - lost[1] > 3000) cur = el ?? null;
      if (el) focus(el);
    }
    const r = !playing && cur?.isConnected && (controls || cur.checkVisibility()) && cur.getBoundingClientRect(), z = parseFloat(document.documentElement.style.zoom) || 1;
    if (r) last = r, lastAt = [scrollX, scrollY], lost = [];  // where it is now
    const jump = r && cur !== ringed;  // a new thing: the ring settles onto it
    if (jump) {
      ringed = cur;
      moored = pinned(cur, true) || scroller(cur, false) !== document.scrollingElement;
      if (ours()) ring.style.borderRadius = corners(cur, r, z);
    }
    const [x, y] = moored ? [0, 0] : [scrollX, scrollY];  // the page's corner, where the ring sits
    // In the screen's pixels: the ring undoes the page's zoom (the same ring on every site).
    const box = r && ours() && !window.tvKeyboard &&  // not over the keyboard
                [moored ? "fixed" : "absolute", 1 / z, r.left + x - 9, r.top + y - 9, r.width + 18, r.height + 18];
    if (String(box) !== drawn) {  // touch the page only when the ring moves, so an idle TV stays idle
      drawn = String(box);
      if (!box) ring.style.display = "none";
      else {
        // On the page (it could have replaced <html>: a React app redrawing all), or in what's full screen (over the rest)
        const fs = document.fullscreenElement, host = fs && !/^(VIDEO|IFRAME)$/.test(fs.tagName) ? fs : document.documentElement;
        if (ring.parentNode !== host) host.append(ring);
        Object.assign(ring.style, { display: "block", position: box[0], zoom: box[1], translate: `${box[2]}px ${box[3]}px`, width: `${box[4]}px`, height: `${box[5]}px` });
        if (jump) ring.animate([{ scale: 1.06 }, { scale: 1 }], { duration: 160, easing: "cubic-bezier(.2, .8, .3, 1)" });
      }
    }
  };
  // Where the highlighted thing was last seen, on the screen as it's scrolled now.
  let lastAt = [0, 0];
  const seen = () => last && !moored ? new DOMRect(last.x + lastAt[0] - scrollX, last.y + lastAt[1] - scrollY, last.width, last.height) : last;
  const follow = () => {
    draw();
    if (performance.now() < until) requestAnimationFrame(follow);
    else following = false;
  };
  // Follow every frame only for a moment after something moves (a key, a scroll, a slide): asking
  // where the highlight is each frame makes the page lay itself out each frame, and under HBO's
  // player that was half a core. Between moves, a look twice a second catches a banner that rotates.
  // Without our ring (the site draws its own), one look is enough.
  const wake = (ms = 1000) => {
    until = Math.max(until, performance.now() + (ours() ? ms : 0));
    if (!following) following = !!requestAnimationFrame(follow);
  };
  // The page's own scroll carries the ring (and moves "last" with it, see seen); the rest is followed.
  addEventListener("scroll", (e) => {
    remap();  // (see map)
    if (moored || e.target !== document) wake();
  }, { capture: true, passive: true });
  // <html data-tv-player> while on a player page, for a site's css (these sites change pages without
  // loading one). Couch-sized text off the player only: 1.25 lays 1920x1080 out like 1536x864, and a
  // player sized to the screen came out a quarter too big (Paramount+ cut the bottom of the show off).
  const marked = () => {
    const html = document.documentElement, playing = PLAYER.test(page()), z = playing || ZOOM === 1 ? "" : String(ZOOM);
    html?.toggleAttribute("data-tv-player", playing);
    if (html && ZOOM !== null && html.style.zoom !== z) html.style.zoom = z;  // (any other site: its own, Spotify's 1.5)
  };
  // A new page (picked, not Back): its first key starts afresh, and Back to the page left lands
  // where the highlight was. Noticed as the site changes the address, and at the next key or tick
  // in case it changed it some other way.
  let path = page();
  const fresh = () => {
    marked();
    if (page() === path) return;
    const was = remembered.get(path);
    if (was && last) was.at = seen();  // a title can be in two rows: Back looks for the copy nearest this
    path = page();
    cur = last = null;
    controls = false;
    wake(0);  // the ring goes
  };
  for (const k of ["pushState", "replaceState"]) {
    const f = history[k];
    history[k] = function () {
      const r = f.apply(this, arguments);
      fresh();
      return r;
    };
  }
  setInterval(() => {
    fresh();
    if (cur) wake(0);
    // The player's controls gone (a second after a key the site may still be opening a menu)
    if (controls && performance.now() - touched > 1000 && !adopt()) hideControls();
    const v = PLAYER.test(page()) && main();
    if (v) hook(v);  // the remote's play/pause key too
    if (bar.style.display === "block") show();  // gone once the page leaves the player
  }, 500);
  const start = () => {
    marked();
    const bars = document.createElement("style");
    bars.textContent = "html:root, * { scrollbar-width: none !important; }" + CSS;  // a TV has no scrollbars (Shahid sets html's own)
    document.head.append(bars);
    document.documentElement.append(ring);  // beside the page's body: placed from the page's own corner
    document.body.append(bar);
  };

  // Paused from the remote (OK, play/pause): where you are, along the bottom like Apple TV's player
  // (these players show nothing for a key, only for the mouse). Not when the site pauses by itself
  // (the credits' next-episode screen, "still watching?"): that's its own screen to read. It goes
  // when the show plays again.
  const bar = document.createElement("div");
  bar.style.cssText = `position: fixed; left: 0; right: 0; bottom: 0; height: 240px; z-index: 2147483646; pointer-events: none;
    display: none; color: #fff; background: linear-gradient(transparent, rgba(0,0,0,.75)); font-variant-numeric: tabular-nums;`;
  // (built without innerHTML: a site may ban it, Trusted Types)
  const part = (tag, css) => Object.assign(document.createElement(tag), { style: css });
  bar.append(part("div", "position:absolute;left:96px;right:96px;bottom:120px;height:10px;border-radius:5px;background:rgba(255,255,255,.28);overflow:hidden"),
             part("span", "position:absolute;left:96px;bottom:64px"), part("span", "position:absolute;right:96px;bottom:64px;opacity:.7"));
  bar.firstElementChild.append(part("div", "height:100%;border-radius:5px;background:#fff"));
  const clock = (s) => {
    s = Math.max(0, Math.floor(s));
    const [h, m, sec] = [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60].map((n, i) => i ? String(n).padStart(2, "0") : n);
    return h ? `${h}:${m}:${sec}` : `${+m}:${sec}`;
  };
  let barred = false;  // the show was paused from the remote
  const show = (e) => {
    const v = scrubbed;
    if (e?.type === "pause") barred = performance.now() - touched < 1500;
    if (!barred || controls || !v?.paused || v.ended || !PLAYER.test(page()) && !document.fullscreenElement) {
      barred = false;
      return void (bar.style.display = "none");
    }
    const end = isFinite(v.duration) ? v.duration : 0, [track, at, left] = bar.children;
    bar.style.font = `600 30px/1 ${getComputedStyle(document.body).fontFamily}`;
    bar.style.zoom = 1 / (parseFloat(document.documentElement.style.zoom) || 1);  // the same size on every site
    track.firstElementChild.style.width = end ? `${100 * v.currentTime / end}%` : "0";
    at.textContent = clock(v.currentTime);
    left.textContent = end ? "-" + clock(end - v.currentTime) : "";
    bar.style.display = "block";
  };
  // The show's video (the biggest showing a picture: Disney+ keeps an empty one too), whose pausing,
  // playing and seeking move the bar.
  const main = () => [...document.querySelectorAll("video")].sort((a, b) =>
    !a.videoWidth - !b.videoWidth || b.clientWidth * b.clientHeight - a.clientWidth * a.clientHeight)[0];
  let scrubbed = null;
  const hook = (v) => {
    if (v === scrubbed) return;
    for (const ev of ["seeked", "play", "pause"]) { scrubbed?.removeEventListener(ev, show); v.addEventListener(ev, show); }
    scrubbed = v;
  };

  // One key press asks the same boxes about their overflow, size and pinning many times; ask each once.
  let styles = new Map(), rects = new Map(), pins = new Map();
  const style = (p) => styles.get(p) || styles.set(p, getComputedStyle(p)).get(p);
  const rect = (p) => rects.get(p) || rects.set(p, p.getBoundingClientRect()).get(p);
  // A row of posters that scrolls sideways (not a pane that scrolls down and spills over a little).
  const isRow = (p, s) => /auto|scroll/.test(s.overflowX) && p.scrollWidth > p.clientWidth + 1 && p.scrollHeight <= p.clientHeight + 2;
  // The box that scrolls el sideways (such a row) or up and down (the page, or a site's own pane).
  const scroller = (el, sideways) => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const s = style(p);
      if (sideways ? isRow(p, s) : /auto|scroll/.test(s.overflowY) && p.scrollHeight > p.clientHeight + 2) return p;
    }
    if (sideways) return null;
    const b = document.body;  // <body> as the page's scroller (<html> holding still), else the page's
    return b && /auto|scroll/.test(style(b).overflowY) && b.scrollHeight > b.clientHeight + 2 ? b : document.scrollingElement || document.documentElement;
  };

  // The slide-out menu's panel while it's open.
  const menuPanel = () => {
    const p = MENU && document.querySelector(MENU[1]);
    return p?.checkVisibility() && p.getBoundingClientRect().right > 0 ? p : null;
  };

  // What might be picked (only the menu's, while it's open); a fresh look at the page each time.
  const candidates = () => {
    styles = new Map(), rects = new Map(), pins = new Map();
    return PLAYER.test(page()) ? deep(document) : [...(menuPanel() || dialog() || document).querySelectorAll(PICKABLE)];
  };
  // A dialog over the page (cookies, sign in): only its things, as the page under it is out of reach.
  const dialog = () => [...document.querySelectorAll("dialog[open], [aria-modal=true]")].find((d) => d.checkVisibility() && d.querySelector(PICKABLE));
  // ...and where they are: looked up while the TV rests after a press, so the next press needn't
  // measure a big page first (Crunchyroll's home: 2000 of them, 50 ms of every press). Thrown away
  // when the page changes or scrolls (between presses these pages sit still; HBO's only changes are
  // its animated icons' drawing, not counted), and looked up again for 10 s after a press.
  let map = null, mapping = 0, idling = 0, pressedAt = -Infinity;
  const geometry = () => {
    if (!map || PLAYER.test(page()) || menuPanel() || dialog()) return candidates().map((el) => [el, el.getBoundingClientRect()]);
    styles = new Map(), rects = new Map(), pins = new Map();
    return map;
  };
  const remap = () => {
    map = null;
    clearTimeout(mapping);
    cancelIdleCallback(idling);
    mapping = idling = 0;
    if (performance.now() - pressedAt < 10000 && !PLAYER.test(page()))
      mapping = setTimeout(() => idling = requestIdleCallback(() => {
        mapping = idling = 0;
        map = menuPanel() || dialog() ? null : candidates().map((el) => [el, el.getBoundingClientRect()]);
      }, { timeout: 1000 }), 150);
  };
  new MutationObserver((l) => l.some((m) => m.target !== ring) && remap()).observe(document, { subtree: true, childList: true,
    attributeFilter: ["class", "style", "hidden", "href", "role", "tabindex", "disabled", "aria-disabled", "open"] });
  for (const t of ["resize", "transitionend", "animationend", "load"]) addEventListener(t, remap, true);  // (a picture's load: an image)
  // Inside web components too, on a player (Disney+'s; elsewhere the pages are big and don't need it).
  const deep = (root) => [...root.querySelectorAll(PICKABLE), ...[...root.querySelectorAll("*")].flatMap((e) => e.shadowRoot ? deep(e.shadowRoot) : [])];
  // Pickable and showing, short of half the screen: a banner that's one big link under its own
  // buttons, or a trailer's player, isn't a thing to pick. Below or above the screen counts (moving
  // down scrolls to the next row), and so does the rest of a row that scrolls sideways (picking
  // scrolls it in), but not the hidden ends of a row that slides: those slide in when the highlight
  // runs off the row's end (see slide). The costly part, so asked of as few as possible.
  const usable = (el, r = el.getBoundingClientRect()) =>
    r.width > 8 && r.height > 8 && r.width * r.height < innerWidth * innerHeight / 2 && !el.disabled &&
    el.getAttribute("aria-disabled") !== "true" &&  // row titles that are links to nowhere
    !(NEVER && el.matches(NEVER)) && shown(el, r) && el.checkVisibility({ opacityProperty: true, visibilityProperty: true }) &&
    !(el !== cur && cur && (el.contains(cur) || cur.contains(el)));
  const pickables = () => candidates().filter((el) => usable(el));
  // Mostly within the screen's width and every clipping box around it: a row hides its ends, a
  // collapsed part of a form (Netflix's sign-in page's password step) hides its fields. Up and down only
  // boxes that hide for good count; a panel that scrolls (a show's episode list) can bring things in.
  const shown = (el, r) => {
    let [lo, hi, top, bot] = [-Infinity, Infinity, -Infinity, Infinity], row = false;
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const s = style(p);
      if (row) {}  // what's around a scrolling row doesn't matter: picking scrolls the rest in
      else if (isRow(p, s)) row = true;
      else if (s.overflowX !== "visible") [lo, hi] = [Math.max(lo, rect(p).left), Math.min(hi, rect(p).right)];
      if (/hidden|clip/.test(s.overflowY)) [top, bot] = [Math.max(top, rect(p).top), Math.min(bot, rect(p).bottom)];
    }
    if (!row) [lo, hi] = [Math.max(lo, 0), Math.min(hi, innerWidth)];  // and the screen's edges
    return Math.min(r.right, hi) - Math.max(r.left, lo) > r.width / 2 &&
      Math.min(r.bottom, bot) - Math.max(r.top, top) > r.height / 2;
  };

  // In a bar pinned to the screen (a site's top menu)? It's always just above whatever row is in
  // view, so up and down from the page reach it last, like a TV app, only once the page runs out.
  // (Not sticky: a Watch Now bar can be. The ring holds to sticky ones too: they stop scrolling.)
  const pinned = (el, sticky = false) => {
    if (!el) return false;
    const p = style(el).position;
    if (p === "fixed" || sticky && p === "sticky") return true;
    if (sticky) return pinned(el.offsetParent, true);
    let v = pins.get(el);
    if (v === undefined) pins.set(el, v = pinned(el.offsetParent));
    return v;
  };

  // The nearest one in direction [dx, dy] from rect r. Sideways: distance along the arrow plus twice
  // the miss up or down, so the next poster in the same row beats a closer one in the row below.
  // Up and down, like a TV app: the nearest row first, then what's most in line in it (from a
  // poster on the right, Up reaches the banner's one button on the left, not a menu further up
  // that happens to be in line). From something wide (a search box, a Resume button) "in line"
  // means its left end. Bars pinned to the screen come last (see pinned).
  // Scored on position alone first; only the best few are then checked for being usable (Disney+'s
  // home has 400 links: checking them all took 80-200 ms a key press).
  const nearest = (r, [dx, dy]) => {
    const cx = r.left + Math.min(r.width, dy ? 300 : Infinity) / 2, cy = r.top + r.height / 2;
    const scored = [], fromPage = dy && !(cur && pinned(cur));
    for (const [el, q] of geometry()) {
      if (el === cur) continue;
      const along = dx ? (dx > 0 ? q.left - r.right : r.left - q.right) : (dy > 0 ? q.top - r.bottom : r.top - q.bottom);
      if (along < -Math.min(r.width, r.height, q.width, q.height) / 2) continue;  // not that way
      if (dx && (q.bottom <= r.top || q.top >= r.bottom)) continue;  // sideways stays beside it (start of a row: stay put)
      if (dy && Math.min(r.bottom, q.bottom) - Math.max(r.top, q.top) > 0.4 * Math.min(r.height, q.height)) continue;  // same row
      const side = dx ? Math.max(0, Math.abs(q.top + q.height / 2 - cy) - q.height / 2)
                      : Math.max(0, Math.abs(q.left + q.width / 2 - cx) - q.width / 2);
      scored.push({ el, q, side, along: Math.max(0, along) });
    }
    const ok = (c) => usable(c.el, c.q) && (!controls || control(c.el, c.q));
    if (dx) return scored.sort((a, b) => a.along + 2 * a.side - b.along - 2 * b.side).find(ok)?.el ?? null;
    // The nearest row: in the page if there's one that way, else a pinned bar's. Asked of the nearest
    // only, in order: whether something is pinned is costly over a big page (40 ms a press on Crunchyroll's).
    const onBar = (c) => fromPage && pinned(c.el);
    let row, barRow;
    for (const c of scored.sort((a, b) => a.along - b.along)) {
      if (!ok(c)) continue;
      if (!onBar(c)) { row = c; break; }
      barRow ??= c;
    }
    row ??= barRow;
    if (!row) return null;
    const near = row.along + Math.max(40, row.q.height / 2), pin = onBar(row);  // the rest of that row
    return scored.filter((c) => c.along <= near).sort((a, b) => a.side - b.side).find((c) => onBar(c) === pin && ok(c))?.el ?? row.el;
  };

  // page -> { sel: the link (or labelled button) last highlighted there, at: where it was as we left },
  // to land on again after Back
  const remembered = new Map();
  const quote = (v) => `"${v.replace(/["\\]/g, "\\$&").replace(/\n/g, "\\a ")}"`;  // not CSS.escape: Disney+ replaces window.CSS
  const handle = (el) => [["href", "a"], ["aria-label", ""]].map(([k, t]) => el.getAttribute(k) && `${t}[${k}=${quote(el.getAttribute(k))}]`).find(Boolean);
  const pick = (el) => {
    cur = el;
    if (!controls && handle(el)) remembered.set(page(), { sel: handle(el), at: null });  // not a player's button for Back
    draw();  // the ring there now, in this very frame
    // Then followed a moment only on the screen (a menu sliding in); in the page, its scroll carries
    // the ring, a row's scroll wakes it, and each look makes a busy page lay itself out again.
    wake(moored ? 600 : 0);
    focus(el);
    const r = el.getBoundingClientRect();
    const row = scroller(el, true);  // a row that scrolls sideways: bring the poster in
    if (row) {
      const q = row.getBoundingClientRect();
      if (r.left < q.left || r.right > q.right)
        row.scrollBy({ left: r.left < q.left ? r.left - q.left - 48 : r.right - q.right + 48, behavior: "smooth" });
    }
    // Keep the highlighted row in the middle of the screen. Only up and down: scrolling a sliding
    // row sideways would fight the site's own sliding.
    if (!controls && (r.top < innerHeight * 0.2 || r.bottom > innerHeight * 0.8))
      scroller(el, false).scrollBy({ top: r.top + r.height / 2 - innerHeight / 2, behavior: "smooth" });
  };

  // The slide button beside rect r on side dx, if r is in a row of posters. Netflix shows them
  // only while the mouse is over the row, so don't ask whether they're visible.
  const rowArrow = (r, dx) => SLIDE && [...document.querySelectorAll(SLIDE)].find((a) => {
    const q = a.getBoundingClientRect(), cy = r.top + r.height / 2;
    return q.height && q.top < cy && q.bottom > cy && dx * (q.left + q.right - r.left - r.right) > 0;  // can overlap the poster
  });
  // Ran off the end of a row: slide it like a TV app, then highlight the next poster from where the
  // highlighted one went (a full slide carries it off screen, the last one moves it a poster or
  // two), or from the row's edge if the site redrew the row.
  const slide = (arrow, r, dx) => {
    sliding = true;
    const q = arrow.getBoundingClientRect();
    hover(arrow, q.left + q.width / 2, q.top + q.height / 2);  // (Shahid's arrows do nothing until a mouse has moved over them)
    setTimeout(() => arrow.click(), 50);
    wake(850);  // the highlighted poster slides along
    setTimeout(() => {
      sliding = false;
      remap();  // where things were mid-slide isn't where they are
      const from = cur?.isConnected ? cur.getBoundingClientRect() : new DOMRect(dx > 0 ? -1 : innerWidth + 1, r.top, 0, r.height);
      const next = nearest(from, [dx, 0]);
      if (next) pick(next);
    }, 750);  // Netflix's slide takes about half a second
  };

  // Left with nothing further left opens the slide-out menu, on the page we're on; Right or Back closes it.
  const when = (ok, then, tries = 30) => ok() ? then() : tries && setTimeout(() => when(ok, then, tries - 1), 50);
  const openMenu = () => {
    before = cur;
    document.querySelector(MENU[0])?.click();
    let items = [];  // once they've faded in: the page we're on, else the first item
    when(() => menuPanel() && (items = pickables().filter((el) => !el.matches(MENU[2]))).length,
         () => pick(items.find((el) => el.getAttribute("aria-current") === "page" || el.pathname === location.pathname) || items[0]));
  };
  const closeMenu = () => {
    document.querySelector(MENU[2])?.click();
    when(() => !menuPanel(), () => before?.isConnected && pick(before));
  };

  // Back to a page: highlight what we left it from (a poster, the trailer button), like a TV app, once the site has redrawn it
  // (HBO takes seconds on the Pi), the copy nearest where it was (a title can be in two rows). A key
  // pressed meanwhile wins, and so does a later Back (not the site putting the cursor in its search box).
  let restores = 0, presses = 0;
  addEventListener("popstate", () => {
    marked();  // the page's zoom before anything is measured on it
    if (page() === path) return;  // a jump to a #section of the page (Chrome tells that like a Back too)
    const was = remembered.get(page()), n = ++restores, k = presses, t0 = performance.now();
    path = page();
    cur = last = null;  // not the old page's highlight, nor what the page puts where it was (follow)
    controls = false;
    wake(0);
    if (!was) return;
    // This runs before the site redraws: the page being left may show a link to the same place. Unless
    // it's still there a second later: a menu bar on every page.
    const stale = new Set([...document.querySelectorAll(was.sel)].filter((a) => a.checkVisibility()));
    const away = (a) => { const q = a.getBoundingClientRect(); return Math.hypot(q.left - (was.at?.left ?? 0), q.top - (was.at?.top ?? 0)); };
    let el;
    const mine = () => n === restores && k === presses;
    when(() => !mine() || (el = [...document.querySelectorAll(was.sel)]
                .filter((a) => (!stale.has(a) || performance.now() - t0 > 1000) && a.checkVisibility()).sort((a, b) => away(a) - away(b))[0]),
         () => mine() && pick(el), 160);
  });

  // A player's controls show while the mouse moves over the show: pretend it did (one pixel back and forth).
  let wiggle = 0;
  const reveal = () => {
    const x = innerWidth / 2 + (wiggle ^= 1), y = innerHeight / 2;
    hover(pointAt(x, y), x, y);
  };
  const hover = (t, x = 0, y = 0) => {
    for (const E of [PointerEvent, MouseEvent])
      t?.dispatchEvent(new E(E === PointerEvent ? "pointermove" : "mousemove", { bubbles: true, composed: true, clientX: x, clientY: y }));
  };
  // What the screen shows at x, y, down inside web components (Disney+'s player is made of them).
  const pointAt = (x, y) => {
    let t = document.elementFromPoint(x, y);
    for (let u; t?.shadowRoot && (u = t.shadowRoot.elementFromPoint(x, y)) && u !== t;) t = u;
    return t;
  };
  const showing = (el) => { styles = new Map(), rects = new Map(); return usable(el); };  // fresh measurements
  // Only what's on the screen and on top: HBO's player page has the site's footer under the show.
  const onTop = (el, r = el.getBoundingClientRect()) => {
    if (r.top < 0 || r.left < 0 || r.bottom > innerHeight || r.right > innerWidth) return false;
    for (let n = pointAt(r.left + r.width / 2, r.top + r.height / 2); n; n = n.parentNode || n.host) if (n === el) return true;
    return false;
  };
  // A player's button, on screen and on top, but not Full Screen: the TV is full screen already, and
  // the site's full screen covers the highlight.
  const control = (el, r) => onTop(el, r) && !el.matches("[aria-label*='full screen' i], [aria-label*=fullscreen i], [class*=fullscreen i]");
  const visible = () => pickables().filter((el) => control(el));
  const SLIDER = "[role=slider], input[type=range]";  // a timeline
  // What has the focus, down inside web components.
  const focusedNow = () => {
    let a = document.activeElement;
    while (a?.shadowRoot?.activeElement) a = a.shadowRoot.activeElement;
    return a;
  };
  // Once they're up (they may fade in), the button nearest the bottom middle: play/pause on most players
  // (not a timeline across the screen: Crunchyroll's). Not if a key or the page moved on meanwhile.
  const showControls = () => {
    const k = presses, p = page(), moved = () => k !== presses || p !== page();
    when(() => moved() || !controls && visible().length, () => {
      if (moved() || controls) return;
      const d = (el) => { const r = el.getBoundingClientRect(); return Math.hypot(r.left + r.width / 2 - innerWidth / 2, r.bottom - innerHeight) +
                                                                       (el.matches(SLIDER) ? 1e6 : 0); };
      controls = true;
      pick(visible().sort((a, b) => d(a) - d(b))[0]);
    });
  };
  // The highlight stays on the player's controls: on what the site put its focus on (a menu of theirs
  // it opened: HBO's subtitles), or where it is. False once neither is up.
  const adopt = () => {
    const a = focusedNow();
    if (a !== cur && a?.matches(PICKABLE) && showing(a) && control(a)) return pick(a), true;
    return !!cur?.isConnected && showing(cur) && control(cur);
  };
  // After OK on one: the highlight follows the site, or goes to what's nearest if the button went under a menu.
  const settle = (was, k) => {
    if (!controls || k !== presses || adopt()) return;
    const d = (el) => { const r = el.getBoundingClientRect(); return Math.hypot(r.left - was.left, r.top - was.top); };
    const near = visible().sort((x, y) => d(x) - d(y))[0];
    if (near) pick(near);
  };
  const hideControls = () => {
    if (cur && focusedNow() === cur) cur.blur();  // OK pauses again, not the button the highlight was on
    controls = false;
    cur = null;
    wake(0);  // the ring goes
  };

  // The site's focus goes along only where something needs it: a text box (it takes the typing), a
  // player's controls (what they act on), a site whose own highlight is its focus (Disney+'s). On
  // a poster, focusing cost HBO 25-50 ms a press of its own work. A text box left behind lets go at
  // once (it would keep the arrows and OK); anything else keeps the site's focus (a menu or a list
  // closes when its focus goes). A text box is focused once the ring is on screen; a player's
  // controls at once.
  let focusing = 0;
  const focus = (el) => {
    const go = () => cur === el && el.focus({ preventScroll: true, focusVisible: !ours() });  // no second, site-drawn ring
    if (controls || !ours()) return go();
    const a = focusedNow();
    if (a !== el && typing(a) && !el.closest("[role=listbox], [role=option]")) a.blur();  // (its own suggestions close without it)
    if (!typing(el)) return;
    const n = ++focusing;
    requestAnimationFrame(() => setTimeout(() => n === focusing && go()));
  };

  const typing = (el) => el?.matches?.("input:not([type]), input[type=text], input[type=search], input[type=email], input[type=url], " +
                                        "input[type=password], input[type=tel], input[type=number], textarea, select");
  // A site that puts the cursor in a text field itself (search pages) takes the highlight there too.
  addEventListener("focusin", (e) => { if (typing(e.target) && e.target !== cur) { cur = e.target; wake(); } });

  // A key the layer takes, its release too: Paramount+'s player pauses on Enter's keyup, and played
  // straight on again after the layer paused it.
  let ate = null;
  let heldKey = "", heldAt = 0, movedAt = 0;  // the last arrow and when it came; when the highlight last moved
  addEventListener("keyup", (e) => {
    if (!e.isTrusted || e.key !== ate) return;
    ate = null;
    e.preventDefault();
    e.stopImmediatePropagation();
  }, true);
  addEventListener("keydown", (e) => {
    if (!e.isTrusted || window.tenfootOwnKeys) return;  // a site's own, or the Enter the keyboard's Done sends; or
    // the TV's own page for a site that didn't load (web/home/offline.html), which does its own keys
    presses++;
    pressedAt = performance.now();
    if (!map && !mapping) remap();
    ate = null;  // its keyup went somewhere else (a frame)
    fresh();
    if (e.altKey && e.key === "ArrowLeft") {  // the remote's Back: some sites take Alt+Left for themselves (HBO switches tabs)
      if (controls) {  // the player's controls first (and a menu of theirs: subtitles), the show stays
        (focusedNow() || document).dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", keyCode: 27, bubbles: true, composed: true }));
        hideControls();
      } else if (menuPanel()) closeMenu();
      else history.back();
      e.preventDefault();  // so the browser doesn't go back a second time
      e.stopImmediatePropagation();
      ate = e.key;
      return;
    }
    const playing = PLAYER.test(page()) || document.fullscreenElement;
    if (playing && !site) return;  // a video full screen on any other site: its own keys
    if (controls && (!playing || !cur?.isConnected)) hideControls();  // off the player, or the site redrew them: from the start
    const focused = focusedNow();  // a Skip Intro button inside a web component
    // Up or Down on a player brings up its own controls (subtitles and audio, skipping, episodes), like a
    // TV app: the arrows go between them and OK presses one. Left and Right stay the site's (seeking).
    const dir = DIRS[e.key];
    if (playing && (controls ? dir || e.key === "Enter" : dir?.[1])) {
      reveal();
      if (!controls) showControls();
      else if (cur.matches(SLIDER) && (dir?.[0] || e.key === "Enter")) {
        if (dir) return;  // a timeline: Left and Right are its own seeking (it has the focus)
        const v = main();  // and OK pauses (a click would seek to wherever the click "was")
        if (v) hook(v), v.paused ? v.play() : v.pause();
      } else if (e.key === "Enter") {
        const was = cur.getBoundingClientRect(), k = presses;
        cur.click();
        setTimeout(() => settle(was, k), 300);  // a menu of theirs may take a moment to open
        setTimeout(() => settle(was, k), 1200);
      } else {
        const next = nearest(cur.getBoundingClientRect(), dir);
        if (next) pick(next);
      }
      e.preventDefault();
      e.stopImmediatePropagation();
      ate = e.key;
      return;
    }
    // OK pauses and plays, like a TV app (Crunchyroll's player ignores Enter), unless a button has it;
    // so does the remote's play/pause key (the page gets it as a key, and HBO's player ignores it)
    if (playing && (e.key === "MediaPlayPause" || e.key === "Enter" && !e.altKey && !focused?.matches(CONTROLS))) {
      const v = main();
      if (!v) return;
      hook(v);
      v.paused ? v.play() : v.pause();
      e.preventDefault();
      e.stopImmediatePropagation();
      ate = e.key;
      return;
    }
    if (playing || e.altKey || e.ctrlKey || e.metaKey) return;
    if (dir) {
      if (typing(document.activeElement) && dir[0]) return;  // left/right move the text cursor
      // A held arrow repeats 30 times a second: faster than a TV app moves, and than the Pi finds the
      // next thing on a big page, so the presses queued up and the highlight ran on after the button
      // was let go. Held, it moves at most every 110 ms, and never for a press that waited in line.
      const repeat = e.key === heldKey && e.timeStamp - heldAt < 90;  // no finger taps that fast
      heldKey = e.key, heldAt = e.timeStamp;
      if (repeat && (e.timeStamp - movedAt < 110 || performance.now() - e.timeStamp > 100)) {
        e.preventDefault();
        e.stopImmediatePropagation();
        ate = e.key;
        return;
      }
      movedAt = e.timeStamp;
      if (cur && !(cur.isConnected && cur.checkVisibility())) cur = null;  // gone: from where it was
      const panel = menuPanel();
      // First press, or the highlighted thing vanished: start from where it was, else the first thing
      // on the page itself (a show's Play), the site's menu bar only if there's nothing else.
      const from = cur ? cur.getBoundingClientRect() : seen() || new DOMRect(-1, 120, 0, 0);
      const step = (dy, to = cur) => scroller(to || document.body, false).scrollBy({ top: dy * innerHeight * 0.6, behavior: "smooth" });
      // The first press: the first thing on the screen, below a menu bar at the very top that scrolls
      // with the page (HBO's); the site's pinned menu bar only if there's nothing else.
      const first = (inBar, top = 0, bottom = innerHeight) => candidates().find((el) => {
        const t = el.getBoundingClientRect().top;
        return t >= top && t < bottom && pinned(el) === inBar && usable(el);
      });
      const next = cur || last ? nearest(from, dir) : first(false, innerHeight * 0.08) || first(false) || first(true) || first(false, 0, Infinity);
      const q = next?.getBoundingClientRect(), arrow = cur && dir[0] && rowArrow(from, dir[0]);
      if (sliding) {}  // wait for the posters to settle
      else if (panel && dir[0] > 0) closeMenu();
      else if (arrow && !(q && q.top < from.bottom && q.bottom > from.top)) slide(arrow, from, dir[0]);  // nothing more in this row
      // The next link of a page of text (an article) can be screens away: scroll a step towards it, like a TV browser.
      else if (cur && q && (dir[1] > 0 ? q.top > innerHeight * 1.5 : dir[1] < 0 && q.bottom < -innerHeight / 2)) step(dir[1], next);
      else if (next) pick(next);
      else if (MENU && !panel && dir[0] < 0) openMenu();
      else if (!cur && !next) return;  // nothing to pick on the page at all (a game, a map): its own arrows
      else if (dir[1]) step(dir[1]);  // nothing pickable that way: just scroll
    } else if (e.key === "Enter" && cur?.isConnected && !typing(cur)) {
      cur.click();
    } else return;
    e.preventDefault();
    e.stopImmediatePropagation();
    ate = e.key;
  }, true);

  Object.defineProperty(window, "tvHighlight", { get: () => cur });  // for checking it from DevTools
  if (document.documentElement && document.head) start();
  else document.addEventListener("DOMContentLoaded", start);
})();

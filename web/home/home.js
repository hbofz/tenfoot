// The home screen. The top row sits in a glass dock over the focused app's own full-screen picture (a shuffled photo,
// or what's playing on Spotify); Down goes to the grid. Spotify is asked directly (go-librespot on localhost:3678).
// Without it, or without any photos, it still works: clock, tiles.
const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const PLAYER = "http://localhost:3678";
const store = { get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
                set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} } };
function el(tag, props = {}, ...kids) {
  const e = Object.assign(document.createElement(tag), props);
  e.append(...kids.filter((k) => k != null && k !== false));
  return e;
}
const fit = () => (document.documentElement.style.zoom = innerWidth / 1920);  // drawn for 1080p; any other screen scales
addEventListener("resize", fit);
fit();

// ---------- Photos: each top-row app gets its own, from a bag shuffled every time home opens ----------
const WP = window.WALLPAPERS;
const shuffle = (a) => { for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
let bag = shuffle(WP.map((_, k) => k)), drawn = 0;
const missing = new Set();
const take = () => {
  for (let tries = 0; tries <= bag.length; tries++) {
    if (drawn >= bag.length) { bag = shuffle(bag); drawn = 0; }
    if (!missing.has(bag[drawn])) return bag[drawn++];
    drawn++;
  }
  return bag[0];
};
// A photo on screen is two images: itself, and its blurred copy lined up inside the glass dock. Kept decoded and
// reused (the last few), so moving along the dock swaps pictures at once.
const pool = new Map();
let shown = -1, z = 0, seq = 0, cleanTimer;
function photo(k) {
  let p = pool.get(k);
  if (!p) {
    const w = WP[k];
    p = { img: el("img", { src: `wallpapers/${w.id}.jpg`, alt: "" }), glass: el("div", { className: "g" }), blur: `wallpapers/${w.id}-blur.jpg` };
    p.glass.style.backgroundImage = `url(${p.blur})`;
    p.ready = Promise.all([p.img.decode(), el("img", { src: p.blur }).decode()]).then(() => true, () => false);
    $("photos").append(p.img);
    $("glass").append(p.glass);
  }
  pool.delete(k);
  pool.set(k, p);  // most recently used last
  const keep = new Set([...Object.values(photoOf), shown, k]);  // ponytail: one per dock app, plus the one showing:
  for (const [kk, pp] of pool) {                                 // ~60 MB of GPU layers
    if (pool.size <= 7) break;
    if (!keep.has(kk)) { pp.img.remove(); pp.glass.remove(); pool.delete(kk); }
  }
  return p;
}
async function showPhoto(k, slow = false, now = false) {
  const mine = ++seq, p = photo(k);
  const ok = await p.ready;
  if (mine !== seq) return;  // a newer request wins
  if (!ok) {  // not downloaded (yet): forget it and try another, so a partial set still shows pictures
    pool.delete(k);
    p.img.remove();
    p.glass.remove();
    missing.add(k);
    if (missing.size < WP.length) {
      const next = take();
      Object.keys(photoOf).filter((id) => photoOf[id] === k).forEach((id) => (photoOf[id] = next));
      return showPhoto(next, slow, now);
    }
    return;
  }
  if (k === shown) return;
  shown = k;
  p.img.style.zIndex = p.glass.style.zIndex = ++z;  // the new one fades in on top; the old one leaves once it's covered
  p.img.classList.toggle("slow", slow);
  p.img.classList.toggle("now", now);
  p.glass.classList.toggle("now", now);
  p.img.style.setProperty("--kx", `${(Math.random() * 2 - 1) * 1.5}%`);
  p.img.style.setProperty("--ky", `${(Math.random() * 2 - 1) * 1.2}%`);
  p.img.classList.toggle("kb", document.body.classList.contains("idle"));  // the screensaver's slow drift, kept till it's covered
  p.img.classList.add("on");
  p.glass.classList.add("on");
  clearTimeout(cleanTimer);  // only the newest swap tidies up, once its fade is done
  cleanTimer = setTimeout(() => {
    for (const [kk, pp] of pool) if (kk !== shown) { pp.img.classList.remove("on", "kb"); pp.glass.classList.remove("on"); }
  }, slow ? 2100 : 500);
  $("wash").firstElementChild.src = p.blur;
  const [place, ...region] = WP[k].place.split(", ");
  $("place").firstElementChild.textContent = place;
  $("place").lastElementChild.textContent = [region.join(", "), `Photo: ${WP[k].by}`].filter(Boolean).join(" · ");
}

// ---------- Icons ----------
const ITEMS = window.APPS;  // COLS (icons per row) comes from nav.js
const photoOf = {};
ITEMS.slice(0, COLS).forEach((a) => (photoOf[a.id] = take()));
const tiles = ITEMS.map((a, n) => {
  const row = Math.floor(n / COLS);
  const t = el("a", { className: "tile" + (row ? " inrow" : ""), href: a.url });
  t.style.left = `${90 + 298 * (n % COLS)}px`;
  t.style.top = `${row ? 1050 + 258 * (row - 1) : 824}px`;
  // ponytail: a coloured tile with the name; apps.json could take an icon file when someone wants one
  const icon = el("div", { className: "icon", textContent: a.name });
  icon.style.setProperty("--c", a.color);
  t.append(el("div", { className: "lift" }, el("div", { className: "shadow" }),
              el("div", { className: "sway" }, el("div", { className: "sway2" }, icon))),
           el("div", { className: "label", textContent: a.name }));
  (row ? $("rows") : $("dock")).append(t);
  return t;
});

let i = Math.min(store.get("tile", 0), tiles.length - 1);
let restTimers = [];
function rest() {  // resting on one icon: it sways after a moment, the others dim a little later; after a minute it
  // holds still, so the Pi stops drawing frames for nobody
  document.body.classList.remove("rest", "dim");
  restTimers.forEach(clearTimeout);
  restTimers = [setTimeout(() => document.body.classList.add("rest"), 2500), setTimeout(() => document.body.classList.add("dim"), 5000),
                setTimeout(() => document.body.classList.remove("rest"), 60000)];
}
function focusTile(n) {
  const wasGrid = i >= COLS;
  i = n;
  tiles[i].focus({ preventScroll: true });
  const grid = i >= COLS;
  document.body.classList.toggle("grid", grid);
  // the grid keeps the last top-row app's picture (opening straight into the grid: the one above); back up from it,
  // the new one is swapped in under the fading wash
  if (!grid || shown < 0) showPhoto(photoOf[ITEMS[i % COLS].id], false, wasGrid && !grid);
  store.set("tile", i);
  rest();
  update();
}
const BUMP = { l: ["-10px", "0px", "-1.5deg"], r: ["10px", "0px", "1.5deg"], u: ["0px", "-10px", "0deg"], d: ["0px", "10px", "0deg"] };
function bump(dir) {
  const t = tiles[i];
  ["--bx", "--by", "--br"].forEach((v, k) => t.style.setProperty(v, BUMP[dir][k]));
  t.classList.remove("bump");
  void t.offsetWidth;
  t.classList.add("bump");
}
addEventListener("keydown", (e) => {
  const dir = { ArrowLeft: "l", ArrowRight: "r", ArrowUp: "u", ArrowDown: "d" }[e.key];
  if (!dir) return;
  e.preventDefault();
  const n = nav.move(i, e.key, tiles.length);
  if (n >= 0) focusTile(n);
  else if (dir === "u") fullScreen();  // Up from the top row: just the picture
  else bump(dir);
});
tiles.forEach((t, n) => {
  t.addEventListener("mouseenter", () => n !== i && focusTile(n));
  t.addEventListener("click", (e) => {
    e.preventDefault();
    if (n !== i) focusTile(n);
    launch(ITEMS[n].url);
  });
});
// Clicking empty space would otherwise leave nothing focused for the remote.
addEventListener("mouseup", () => setTimeout(() => document.activeElement === tiles[i] || tiles[i].focus({ preventScroll: true }), 0));
function launch(url) {
  document.body.classList.add("launch");
  location.href = url;
  setTimeout(() => document.body.classList.remove("launch"), 8000);  // the app never came (offline?): be the home again
}

// ---------- What's on: Spotify, asked every 2 s ----------
let music = null;  // null = nothing playing, "out" = not signed in, else the track
async function pollMusic() {
  try {
    const opt = { cache: "no-store", signal: AbortSignal.timeout(2000) };
    // logged out, the player waits for a pair code and /status hangs; /auth/code answers at once
    if ((await (await fetch(PLAYER + "/auth/code", opt)).text()).includes('"code"')) music = "out";
    else {
      const st = await (await fetch(PLAYER + "/status", opt)).json();
      const t = st && !st.stopped && st.track;
      music = t ? { name: t.name || "", artist: (t.artist_names || []).join(", "), art: t.album_cover_url || "",
                    pos: t.position || 0, dur: t.duration || 0, paused: !!st.paused, at: Date.now() } : null;
    }
  } catch { music = null; }
  update();
}
// Spotify's album art as the picture: blurred into a small canvas once, stretched full screen (Apple Music style).
let artUrl = "";
function paintArt(url) {
  if (url === artUrl) return;
  artUrl = url;
  const img = new Image();
  img.onerror = () => artUrl === url && (artUrl = "");  // try again on the next poll
  img.onload = () => {
    if (artUrl !== url) return;  // a newer song's art was asked for meanwhile
    const c = $("art").getContext("2d"), s = Math.min(img.width, img.height * 16 / 9);
    c.filter = "blur(7px) saturate(1.3)";  // once, on the CPU, at 192x108; stretched 10x it's a soft wash
    c.drawImage(img, (img.width - s) / 2, (img.height - s * 9 / 16) / 2, s, s * 9 / 16, -24, -14, 240, 136);
    c.filter = "none";
    c.fillStyle = "rgb(0 0 0 / .25)";
    c.fillRect(0, 0, 192, 108);
    $("art2").getContext("2d").drawImage($("art"), 5, 78.5, 182, 22.8, 0, 0, 182, 23);  // the part behind the dock
  };
  img.src = url;
}

// The shelf: top left, the focused app's own content. Faded and rebuilt only when it's about something else.
let shelfKey = null, barFill = null;
function shelfFor(id) {
  if (id === "spotify") {
    if (music === "out") return { key: "out", kids: [el("div", { className: "hint1", textContent: "Spotify isn't connected. Press OK to set it up." })] };
    if (!music) return { key: "idle", kids: [el("div", { className: "hint1", textContent: `Play from your phone: in Spotify, choose ${window.TENFOOT.name}.` })] };
    const fill = el("b");
    return { key: "m" + music.name + music.art + music.paused, art: music.art, fill,
             kids: [el("div", { className: "np" }, el("img", { src: music.art, alt: "" }),
               el("div", { className: "col" }, el("div", { className: "eyebrow", textContent: music.paused ? "Paused" : "Now Playing" }),
                  el("div", { className: "title", textContent: music.name }), el("div", { className: "artist", textContent: music.artist }),
                  el("div", { className: "bar" }, fill)))] };
  }
  return null;
}
function update() {
  const id = ITEMS[i].id, s = i < COLS ? shelfFor(id) : null;
  document.body.classList.toggle("music", !!(s && s.art));
  document.body.classList.toggle("shelf", !!s);
  if (s && s.art) paintArt(s.art);
  const key = s ? id + s.key : "", box = $("shelf");
  if (key !== shelfKey) {
    shelfKey = key;
    box.classList.add("gone");
    if (s) setTimeout(() => {
      if (shelfKey !== key) return;
      box.replaceChildren(...s.kids);
      barFill = s.fill || null;
      box.classList.remove("gone");
      tickBar();
    }, 150);
  }
  tickBar();
}
function tickBar() {
  if (!barFill || !music || music === "out" || !music.dur) return;
  const pos = Math.min(music.dur, music.pos + (music.paused ? 0 : Date.now() - music.at));
  barFill.style.transform = `scaleX(${pos / music.dur})`;
}
setInterval(tickBar, 1000);

// ---------- Clock and weather ----------
const { latitude, longitude, temperatureUnit } = window.TENFOOT;
async function weather() {  // Open-Meteo: free, no account. Set latitude and longitude in config.toml; offline: just the time
  if (latitude == null || longitude == null) return;
  try {
    const q = `latitude=${latitude}&longitude=${longitude}&current=temperature_2m&temperature_unit=${temperatureUnit}`;
    const w = await (await fetch(`https://api.open-meteo.com/v1/forecast?${q}`)).json();
    $("temp").textContent = `${Math.round(w.current.temperature_2m)}°`;
  } catch {}
}
function tick() { $("time").textContent = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); }

// ---------- The phone remote's QR: written by the service; hidden while it's missing ----------
const qr = $("rq").firstElementChild;
qr.addEventListener("load", () => ($("rq").hidden = false));
qr.addEventListener("error", () => ($("rq").hidden = true));
const loadQr = () => (qr.src = `run/remote-qr.svg?${Date.now()}`);  // the box's address may change: pick up the new one
loadQr();
setInterval(loadQr, 60 * 1000);

// ---------- Just the picture: Up from the top row, or the screensaver after SAVER seconds idle (?saver=N) ----------
const SAVER = +(params.get("saver") || 600);
let idleTimer, placeTimer, rotateTimer;
function showPlace() {
  document.body.classList.add("showplace");
  clearTimeout(placeTimer);
  placeTimer = setTimeout(() => document.body.classList.remove("showplace"), 6000);
}
function fullScreen() {
  if (shown < 0) return;  // no photos here: nothing to show
  document.body.classList.add("full");
  showPlace();
}
function rotate() {  // a new photo for whatever's showing: every 45 s on the home, every 30 s as the screensaver
  clearTimeout(rotateTimer);
  const idle = document.body.classList.contains("idle");
  rotateTimer = setTimeout(() => {
    if (i >= COLS && !document.body.classList.contains("idle")) return rotate();  // the grid's backdrop stays put
    const k = take();
    if (i < COLS) photoOf[ITEMS[i].id] = k;
    showPhoto(k, true).then(() => document.body.classList.contains("idle") && showPlace());
    rotate();
  }, (idle ? 30 : 45) * 1000);
}
function wake(e) {
  const b = document.body.classList;
  if (b.contains("idle") || b.contains("full")) {
    if (b.contains("idle") && i < COLS) { const k = take(); photoOf[ITEMS[i].id] = k; showPhoto(k); }
    b.remove("idle", "full", "showplace");
    if (e.type === "keydown") { e.preventDefault(); e.stopImmediatePropagation(); }  // the wake press does nothing else
    rotate();
  }
  if (e.type !== "init") rest();
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => { b.add("idle"); b.remove("rest", "dim"); rotate(); }, SAVER * 1000);
}
for (const t of ["keydown", "mousemove", "mousedown", "wheel"]) addEventListener(t, wake, true);

focusTile(i);
for (const a of ITEMS.slice(0, COLS)) photo(photoOf[a.id]);  // decode the whole top row's pictures up front
tick();
setInterval(tick, 5000);
weather();
setInterval(weather, 15 * 60 * 1000);
pollMusic();
setInterval(pollMusic, 2000);
rotate();
wake({ type: "init" });

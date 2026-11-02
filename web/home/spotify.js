// Now Playing for the Pi's Spotify Connect player (go-librespot's API on localhost:3678).
// - status: polled once a second; the screen keeps its own smooth clock in between and only
//   resyncs on real drift (seek, pause, next song)
// - lyrics: line-synced lyrics from LRCLIB (through the service),
//   shown Apple Music style, whole lines; no lyrics = the waveform instead
// - visualizer: only for songs without synced lyrics; 48 frequency bands of what the TV is
//   actually playing, from the service (localhost:8766)
// spotify.html?demo=1[&nolyrics=1][&at=36] fakes a song and a beat, for building without music.
const API = "http://localhost:3678";
const VIZ = "http://127.0.0.1:8766/bands";
// Lyrics timing: how much later than the player's position to show them, for the TV's sound
// delay. Set from the phone remote ("Lyrics timing"), loaded via spotify-sync.js.
const lyricsDelay = () => ((window.spotifySync && window.spotifySync.lyricsMs) || 0) / 1000;
const DEMO = new URLSearchParams(location.search).has("demo");
const $ = (id) => document.getElementById(id);
const panels = ["pair", "idle", "down", "now"];
// Nobody playing for a while (the waiting, login-code or starting screen): back to the home screen.
// ?home=N overrides the 5 minutes, for testing.
const HOME_AFTER = +(new URLSearchParams(location.search).get("home") || 300) * 1000;
let waitingSince = null;
const show = (id) => {
  waitingSince = id === "now" ? null : waitingSince ?? performance.now();
  if (waitingSince !== null && performance.now() - waitingSince > HOME_AFTER) location.href = "home.html";
  panels.forEach((p) => ($(p).hidden = p !== id));
  document.body.classList.toggle("playing", id === "now");
  bandsOn(wantBands());
};
const mmss = (ms) => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}`;

let track = null, at = 0, paused = true, lastArt = "";
const posMs = () => (track ? Math.min(track.duration, track.position + (paused ? 0 : performance.now() - at)) : 0);

async function get(path) {
  const r = await fetch(API + path, { cache: "no-store", signal: AbortSignal.timeout(3000) });
  if (!r.ok) return null;
  const text = await r.text();
  return text ? JSON.parse(text) : null;
}

// ---------- album colour (used by the visualizer bars) ----------
let glow = "rgb(30 215 96)";
function glowFrom(img) {
  try {
    const c = document.createElement("canvas");
    c.width = c.height = 16;
    const g = c.getContext("2d");
    g.drawImage(img, 0, 0, 16, 16);
    const d = g.getImageData(0, 0, 16, 16).data;
    let r = 0, gr = 0, b = 0;
    for (let i = 0; i < d.length; i += 4) { r += d[i]; gr += d[i + 1]; b += d[i + 2]; }
    const n = d.length / 4, max = Math.max(r, gr, b) / n || 1, k = 230 / max;
    glow = `rgb(${Math.round((r / n) * k)} ${Math.round((gr / n) * k)} ${Math.round((b / n) * k)})`;
  } catch { glow = "rgb(30 215 96)"; }
  document.documentElement.style.setProperty("--glow", glow);
}
$("art").addEventListener("load", () => {
  $("art").style.opacity = 1;
  glowFrom($("art"));
  // Background: the cover shrunk to 48px, softened and saturated once, its edge faded to a soft
  // round blob, then stretched full screen. All done once here, so the GPU only moves two images.
  try {
    const c = document.createElement("canvas");
    c.width = c.height = 48;
    const g = c.getContext("2d");
    g.filter = "blur(2px) saturate(1.6)";
    g.drawImage($("art"), -4, -4, 56, 56);
    g.filter = "none";
    g.globalCompositeOperation = "destination-in";
    const edge = g.createRadialGradient(24, 24, 0, 24, 24, 24);
    edge.addColorStop(0.45, "#000");
    edge.addColorStop(1, "transparent");
    g.fillStyle = edge;
    g.fillRect(0, 0, 48, 48);
    $("bg1").src = $("bg2").src = c.toDataURL();
  } catch {}
});

// Background drift: the two blobs wander there and back over 42 s and 55 s. Stepped 20 times a
// second from here instead of a CSS animation: at this speed a step is under a pixel, and the Pi's
// GPU redraws the screen 20 times a second instead of 60 (half its work on the lyrics screen).
const DRIFT = [[$("bg1"), 42, 18, 12, 40, 0.25], [$("bg2"), 55, -20, -10, -35, 0.15]];
const calm = matchMedia("(prefers-reduced-motion: reduce)");
setInterval(() => {
  if (!document.body.classList.contains("playing") || calm.matches) return;
  const t = performance.now() / 1000;
  for (const [el, secs, x, y, deg, grow] of DRIFT) {
    const k = 0.5 - 0.5 * Math.cos((Math.PI * t) / secs);  // 0 -> 1 -> 0, easing in and out at both ends
    el.style.transform = `translate(${x * k}vmax, ${y * k}vmax) rotate(${deg * k}deg) scale(${1 + grow * k})`;
  }
}, 50);

function vizBig(on) {
  if (document.body.classList.contains("vizbig") === on) return;
  document.body.classList.toggle("vizbig", on);
  $("now").classList.toggle("nolyrics", on);
  bandsOn(wantBands());
  fit();
}
// The audio analysis runs only while the visualizer is on screen and the music is playing.
const wantBands = () => !$("now").hidden && document.body.classList.contains("vizbig") && !paused;

// ---------- saved accounts (display only; switching happens on the phone remote) ----------
const profiles = () => window.spotifyProfiles || { accounts: [] };
function reloadProfiles() {
  for (const f of ["run/spotify-profiles.js", "run/spotify-sync.js"]) {
    const s = document.createElement("script");
    s.src = `${f}?${Date.now()}`;
    s.onload = s.onerror = () => s.remove();
    document.head.appendChild(s);
  }
}
reloadProfiles();
setInterval(reloadProfiles, 3000);
const nameFor = (id) => (profiles().accounts.find((a) => a.id === id) || {}).name || null;
let shownKey = "";
function people(visible, active) {
  const nav = $("people"), list = profiles().accounts;
  const key = JSON.stringify([active, list]);
  if (key !== shownKey) {
    shownKey = key;
    nav.replaceChildren(...list.map((a) => {
      const b = document.createElement("button");
      b.tabIndex = -1;
      b.textContent = a.name.slice(0, 36);  // a tile holds this much
      if (a.id === active) b.insertAdjacentHTML("beforeend", "<small>listening now</small>");
      return b;
    }));
  }
  nav.hidden = !visible || !list.length;
}

// ---------- status ----------
function setTrack(t, isPaused, rtt = 0) {
  // The player's position arrives a little late (rtt/2 on average). Keep our own smooth clock
  // and only correct it when it has really drifted, so lyrics don't jitter every second.
  const measured = t.position + (isPaused ? 0 : rtt / 2);
  const same = track && track.uri === t.uri && paused === isPaused;
  const drift = same ? Math.abs(posMs() - measured) : Infinity;
  if (drift > 250) {
    at = performance.now();
    track = { ...t, position: measured };
  } else {
    track = { ...t, position: track.position };  // keep the running clock, take fresh metadata
  }
  paused = isPaused;
  $("title").textContent = $("bigTitle").textContent = t.name || "";
  $("artist").textContent = $("bigArtist").textContent = (t.artist_names || []).join(", ");
  $("paused").hidden = !paused;
  if (t.album_cover_url && t.album_cover_url !== lastArt) {
    lastArt = t.album_cover_url;
    $("art").style.opacity = 0; // never show the previous song's cover next to the new title
    $("art").src = lastArt;
  }
  loadLyrics(t);
}

async function poll() {
  if (DEMO) return;
  try {
    const code = await get("/auth/code").catch(() => null);
    if (code && code.code) {
      $("code").textContent = code.code;
      $("who").textContent = "";
      track = null;
      show("pair");
      return people(false);
    }
    const t0 = performance.now();
    const st = await get("/status");
    const rtt = performance.now() - t0;
    if (!st) { people(false); return show("down"); }
    const name = nameFor(st.username);
    $("who").textContent = st.username ? (name ? `Logged in as ${name}` : "Logged in") : "";
    $("whoNow").textContent = name ? `${name}'s Spotify` : "";
    const t = st.track;
    if (!t && st.buffering && !st.stopped) return;  // skipping: no track for ~1s while the next loads, keep the screen
    if (!t || st.stopped) { track = null; show("idle"); return people(true, st.username); }
    setTrack(t, !!st.paused, rtt);
    show("now");
    people(false);
  } catch {
    people(false);
    show("down");
  }
}

// ---------- lyrics ----------
let lyrics = { uri: null, lines: [], els: [], y: [], cur: -2 };

async function loadLyrics(t) {
  if (t.uri === lyrics.uri) return;
  lyrics = { uri: t.uri, lines: [], els: [], y: [], cur: -2 };
  $("lyrics").replaceChildren();
  // Lyrics usually answer in a fraction of a second; if they're slow, don't leave the right side empty.
  setTimeout(() => lyrics.uri === t.uri && !lyrics.lines.length && vizBig(true), 1500);
  if (!(DEMO && new URLSearchParams(location.search).has("nolyrics"))) {
    try {  // synced lyrics from LRCLIB, through the service
      const q = new URLSearchParams({ track: t.name, artist: (t.artist_names || []).join(", "), album: t.album_name || "", seconds: Math.round(t.duration / 1000) });
      const own = await (await fetch(`http://127.0.0.1:8766/lyrics?${q}`)).json();
      lyrics.lines = own.lines || [];
    } catch {}
    if (lyrics.uri !== t.uri) return; // song changed while we were fetching
  }
  vizBig(!lyrics.lines.length);  // decided once the answer is in, so songs with lyrics never flash the visualizer
  if (lyrics.lines.length) buildLines();
}

function buildLines() {
  const box = $("lyrics");
  box.replaceChildren();
  lyrics.els = lyrics.lines.map((line, i) => {
    const el = document.createElement("div");
    el.className = "ly";
    if (line.text) {
      el.textContent = line.text;
    } else {  // instrumental break: dots that fill in over its length
      const next = i + 1 < lyrics.lines.length ? lyrics.lines[i + 1].t : line.t + 4;
      el.style.setProperty("--dur", `${Math.max(1, next - line.t)}s`);
      el.innerHTML = '<span class="dots"><i style="--n:0"></i><i style="--n:1"></i><i style="--n:2"></i></span>';
    }
    box.append(el);
    return el;
  });
  layoutLines();
}

function layoutLines() {
  // Stack the lines once (their heights never change); drawing just slides them.
  let y = 0;
  const gap = innerHeight * 0.028;
  lyrics.y = lyrics.els.map((el) => { const top = y; y += el.offsetHeight + gap; return top; });
  lyrics.cur = -2;
  lyrics.fresh = true;  // first placement: appear in place, don't glide in from the top
}
addEventListener("resize", () => lyrics.els.length && layoutLines());
document.fonts.ready.then(() => lyrics.els.length && layoutLines());  // first song may measure before Inter loads

function drawLyrics(sec) {
  const lines = lyrics.lines;
  if (!lines.length) return;
  sec -= lyricsDelay();
  let i = -1;
  while (i + 1 < lines.length && lines[i + 1].t <= sec) i++;
  if (i === lyrics.cur) return;
  const goingDown = i > lyrics.cur;
  lyrics.cur = i;
  const c = Math.max(i, 0), box = $("lyrics").clientHeight;
  const shift = box * 0.42 - lyrics.y[c] - lyrics.els[c].offsetHeight / 2;
  lyrics.els.forEach((el, k) => {
    const d = k - i;
    if (Math.abs(d) > 9) {  // off screen: park it without animating
      el.style.transitionDelay = "0s";
    } else {
      // The Apple spring: lines further below follow a moment later, like a soft wave.
      el.style.transitionDelay = goingDown && d > 0 ? `${Math.min(d, 6) * 45}ms` : "0s";
    }
    if (lyrics.fresh) el.style.transition = "none";
    el.style.transform = `translateY(${lyrics.y[k] + shift}px) scale(${d === 0 ? 1 : 0.97})`;
    el.className = "ly" + (d === 0 ? " cur" : Math.abs(d) > 3 ? (Math.abs(d) > 9 ? " hide" : " far") : "");
  });
  if (lyrics.fresh) {
    lyrics.fresh = false;
    requestAnimationFrame(() => requestAnimationFrame(() => lyrics.els.forEach((el) => (el.style.transition = ""))));
  }
}

// ---------- visualizer (songs without synced lyrics) ----------
const N = 48;
let target = new Float32Array(N), level = new Float32Array(N);
let source = null;
function bandsOn(on) {
  if (DEMO || on === !!source) return;
  if (on) {
    source = new EventSource(VIZ);
    source.onmessage = (e) => { target = Float32Array.from(e.data.split(","), (v) => v / 99); };
  } else {
    source.close();
    source = null;
    target = new Float32Array(N);
  }
}

function demoBands(t) {
  const beat = ((t / 1000) * 100 / 60) % 1, kickEnv = Math.exp(-beat * 7);
  for (let i = 0; i < N; i++) {
    const x = i / N, wobble = 0.5 + 0.5 * Math.sin(t / 380 + i * 0.7) * Math.sin(t / 900 + i * 0.3);
    target[i] = Math.min(1, kickEnv * Math.max(0, 1 - x * 4) + wobble * (0.55 - x * 0.35) + Math.random() * 0.08);
  }
}

const canvas = $("viz"), ctx = canvas.getContext("2d");
function fit() { canvas.width = canvas.clientWidth; canvas.height = canvas.clientHeight; }
addEventListener("resize", fit);
fit();

const CAPS = 24;  // capsules per side
function drawBars() {
  if (canvas.width !== canvas.clientWidth) fit();  // it was measured while hidden (0x0)
  const w = canvas.width, h = canvas.height, mid = h / 2;
  ctx.clearRect(0, 0, w, h);
  const slot = w / (CAPS * 2), cw = Math.max(3, slot * 0.42), per = N / CAPS;
  for (let c = 0; c < CAPS; c++) {
    let v = 0;  // average this capsule's share of the 48 bands
    for (let j = 0; j < per; j++) v += level[c * per + j] / per;
    const ch = Math.max(cw, v * h * 0.95);
    ctx.fillStyle = `rgb(255 255 255 / ${(0.92 - (c / CAPS) * 0.6).toFixed(2)})`;  // bright centre, soft edges
    for (const side of [-1, 1]) {  // bass in the middle, treble out to both edges
      const x = w / 2 + side * (c + 0.5) * slot - cw / 2;
      ctx.beginPath();
      ctx.roundRect(x, mid - ch / 2, cw, ch, cw / 2);
      ctx.fill();
    }
  }
}

// ---------- frame loop ----------
let shown = {};
const setIf = (key, v, apply) => { if (shown[key] !== v) { shown[key] = v; apply(v); } };  // skip no-op DOM writes
function frame(now) {
  let wait = 100;
  if (!$("now").hidden) {
    if (document.body.classList.contains("vizbig")) {
      if (DEMO) demoBands(now);
      for (let i = 0; i < N; i++) {
        level[i] += (target[i] - level[i]) * (target[i] > level[i] ? 0.35 : 0.12);  // ease, never jump
      }
      drawBars();
    }
    if (track && track.duration) {
      const p = posMs();
      setIf("bar", Math.round((p / track.duration) * 1000) / 1000, (v) => ($("bar").style.transform = `scaleX(${v})`));  // ~0.6px steps
      setIf("pos", mmss(p), (v) => ($("pos").textContent = v));
      setIf("dur", mmss(track.duration), (v) => ($("dur").textContent = v));
      drawLyrics(p / 1000);
      const next = !paused && lyrics.lines[lyrics.cur + 1];
      if (next) wait = Math.min(wait, (next.t + lyricsDelay()) * 1000 - p);  // wake exactly when the next line starts
    }
  }
  // Only the visualizer draws every frame. Otherwise a few checks a second, plus a wake-up timed to
  // the next lyric line, so lines change on the dot without running every frame.
  if (document.body.classList.contains("vizbig") && !$("now").hidden) requestAnimationFrame(frame);
  else setTimeout(() => frame(performance.now()), Math.max(0, wait));
}

if (DEMO) {
  show("now");
  $("whoNow").textContent = "Sam's Spotify";
  setTrack({ uri: "spotify:track:03L2AoiRbWhvt7BDMx1jUB", name: "U With Me?", artist_names: ["Drake"], album_name: "Views",
             album_cover_url: "https://i.scdn.co/image/ab67616d0000b2739416ed64daf84936d89e671c",
             duration: 297373, position: +(new URLSearchParams(location.search).get("at") || 36) * 1000 }, false);
} else {
  (async function loop() { await poll(); setTimeout(loop, 1000); })();  // one at a time, never piling up
}
requestAnimationFrame(frame);

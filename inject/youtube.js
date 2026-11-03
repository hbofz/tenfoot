// Injected into every page before it loads; only acts on YouTube's TV app.
// 1. Smooth playback: offer the player only what a Pi 4 decodes in hardware.
// 2. SponsorBlock: skip community-marked sponsor reads, self-promo and "subscribe" reminders.
// 3. YouTube's own ads, the owner's choice: dropped from what the app reads, as TizenTube and youtube-webos do.
(() => {
  if (!/(^|\.)youtube\.com$/.test(location.hostname) || !location.pathname.startsWith("/tv")) return;

  window.__tenfoot = { skipped: 0, ads: 0 };

  // Smooth playback: the Pi 4 decodes only H.264 in hardware (not VP9 or AV1, which YouTube
  // prefers), up to 1080p60. Like TizenTube's "preferred codec" option, offer the player only
  // H.264 video (plus all audio).
  function preferH264(o) {
    const f = o && o.streamingData && o.streamingData.adaptiveFormats;
    if (!Array.isArray(f)) return;
    const mime = (x) => x.mimeType || "";
    const h264 = f.filter((x) => mime(x).includes("avc1"));
    if (!h264.length) return; // nothing better on offer: leave it playable
    // "Super resolution" formats are AI-upscaled copies of a low-res upload: a 480p video posing as
    // 1080p, all cost and no detail (VacuumTube; YouTube may change this tag).
    const real = h264.filter((x) => x.xtags !== "CgcKAnNyEgEx");
    const pool = real.length ? real : h264;
    o.streamingData.adaptiveFormats = f.filter((x) => mime(x).startsWith("audio/") || pool.includes(x));
  }

  // Ads: the player's schedule of them (adPlacements, adSlots, playerAds: all three, or it waits for one), and the
  // home screen's ad tiles, banner and promo shelves, wherever they sit (YouTube moves things between home, search and
  // the rows that load as you scroll). Never throws: whatever YouTube changes, the response still works without this.
  const AD_KEYS = ["adPlacements", "adSlots", "playerAds"];
  const AD_ITEMS = ["adSlotRenderer", "tvMastheadRenderer", "promoShelfRenderer"];
  const AD_MARK = /"(adPlacements|adSlots|playerAds|adSlotRenderer|tvMastheadRenderer|promoShelfRenderer|isAd)"/;
  const isAd = (x) => !!x && typeof x === "object" &&
    (AD_ITEMS.some((k) => k in x) || !!x.command?.reelWatchEndpoint?.adClientParams?.isAd);  // a Short that's an ad
  let removed = 0;
  function stripAds(o, depth = 0) {
    if (!o || typeof o !== "object" || depth > 64) return;
    if (Array.isArray(o)) {
      for (let i = o.length - 1; i >= 0; i--) {
        if (isAd(o[i])) { o.splice(i, 1); removed++; } else stripAds(o[i], depth + 1);
      }
      return;
    }
    for (const k of AD_KEYS) if (k in o) { delete o[k]; removed++; }
    for (const k in o) stripAds(o[k], depth + 1);
  }
  const noAds = (r) => { try { stripAds(r); } catch {} window.__tenfoot.ads = removed; };

  const parse = JSON.parse;
  JSON.parse = function (text, reviver) {
    const r = parse.call(this, text, reviver);
    if (typeof text === "string") {
      if (AD_MARK.test(text)) noAds(r);
      if (text.includes("adaptiveFormats")) preferH264(r);
    }
    return r;
  };
  // 60fps: the player keeps 60fps formats only if the browser answers "framerate=" in codec
  // checks. It tests that with an impossible framerate=9999, which Chromium (ignoring the
  // parameter) also says yes to, so every 60fps format was dropped. Say no above 60.
  const isType = MediaSource.isTypeSupported;
  MediaSource.isTypeSupported = function (type) {
    const fps = /;\s*framerate=([\d.]+)/.exec(type);
    return fps && +fps[1] > 60 ? false : isType.call(MediaSource, type);
  };
  const stringify = JSON.stringify;
  // Asking for a video, say it plays with no ads: without this the server holds back the first seconds of video for
  // about as long as the stripped ad would have run. On a copy: the app's own object may be frozen.
  JSON.stringify = function (value, ...rest) {
    try {
      const c = value?.playbackContext?.contentPlaybackContext;
      if (c && typeof c === "object" && !c.isInlinePlaybackNoAd) {
        value = { ...value, playbackContext: { ...value.playbackContext, contentPlaybackContext: { ...c, isInlinePlaybackNoAd: true } } };
      }
    } catch {}
    return stringify.call(this, value, ...rest);
  };
  // fetch().json() never goes through JSON.parse: send it through, so it gets the same (cheaply gated) treatment
  Response.prototype.json = async function () {
    return JSON.parse(await this.text());
  };

  // SponsorBlock. Asked by the first 4 hex digits of the video ID's SHA-256, so the server never
  // learns which video is playing; the answer covers every video with that prefix.
  const CATS = ["sponsor", "selfpromo", "interaction", "preview", "music_offtopic"];
  let vid = null, segs = [], done = new Set();
  async function load(id) {
    vid = id; segs = []; done = new Set();
    try {
      const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(id));
      const prefix = [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 4);
      const r = await fetch(`https://sponsor.ajay.app/api/skipSegments/${prefix}?categories=${encodeURIComponent(stringify(CATS))}`);
      const mine = r.ok && (await r.json()).find((v) => v.videoID === id);
      if (mine && vid === id) segs = mine.segments.map((s) => s.segment);
    } catch {}
  }
  function toast(msg) {
    const t = document.createElement("div");
    t.textContent = msg;
    t.style.cssText = "position:fixed;right:4vw;bottom:8vh;z-index:99999;padding:1.2vh 1.6vw;" +
      "background:rgba(0,0,0,.8);color:#fff;font:600 1.4vw sans-serif;border-left:.4vw solid #1ed760";
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2500);
  }
  setInterval(() => {
    const id = new URLSearchParams(location.hash.split("?")[1] || "").get("v");
    if (id && id !== vid) load(id);
    const v = document.querySelector("video");
    if (!v || v.paused || !segs.length) return;
    for (const [a, b] of segs) {
      // Each segment is skipped once: seeking back into it on purpose is respected.
      if (!done.has(a) && v.currentTime >= a && v.currentTime < b - 0.5) {
        done.add(a);
        v.currentTime = Number.isFinite(v.duration) ? Math.min(b, v.duration - 1) : b;  // a sponsor at the very end: stop just short of it, don't jump off the end
        window.__tenfoot.skipped++;
        toast("Skipped sponsor");
      }
    }
  }, 500);
})();

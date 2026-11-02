// Shahid (shahid.mbc.net): keep the Pi cool. Its video is DRM-protected, so the Widevine module
// decodes it in software (no hardware decoder for DRM video in Chromium on Linux): ~130% CPU at
// 1080p, which throttles the Pi. Like preferH264 for YouTube, edit what the player is offered:
// nothing above 720p, so even "Auto" stays light. A viewer's own lower choice still applies.
(() => {
  if (location.hostname !== "shahid.mbc.net") return;
  const MAX = 720;
  window.__tenfootShahid = { cut: 0 };

  function cap(text) {
    if (typeof text !== "string" || !text.includes("<MPD")) return text;
    const doc = new DOMParser().parseFromString(text, "application/xml");
    let cut = 0;
    for (const set of [...doc.getElementsByTagName("AdaptationSet")]) {
      const reps = [...set.getElementsByTagName("Representation")];
      const big = reps.filter((r) => +r.getAttribute("height") > MAX);
      if (big.length === reps.length) continue; // nothing smaller on offer: leave it playable
      big.forEach((r) => r.remove());
      cut += big.length;
    }
    if (!cut) return text;
    window.__tenfootShahid.cut += cut;
    return new XMLSerializer().serializeToString(doc);
  }

  // Manifests arrive as text or raw bytes; video segments are bytes too, so only peek at those.
  function capBytes(buf) {
    if (buf.byteLength > 4e6) return buf;
    const head = new TextDecoder().decode(new Uint8Array(buf, 0, Math.min(buf.byteLength, 512)));
    if (!head.includes("<MPD")) return buf;
    const s = new TextDecoder().decode(buf), c = cap(s);
    return c === s ? buf : new TextEncoder().encode(c).buffer;
  }

  // The player fetches its manifest with XMLHttpRequest; cover fetch too.
  const seen = new WeakMap(); // xhr -> [original, capped], so repeated reads stay cheap
  for (const prop of ["responseText", "response"]) {
    const d = Object.getOwnPropertyDescriptor(XMLHttpRequest.prototype, prop);
    Object.defineProperty(XMLHttpRequest.prototype, prop, {
      configurable: true,
      get() {
        const v = d.get.call(this);
        if (this.readyState !== 4 || !(typeof v === "string" || v instanceof ArrayBuffer)) return v;
        if (seen.get(this)?.[0] !== v) seen.set(this, [v, typeof v === "string" ? cap(v) : capBytes(v)]);
        return seen.get(this)[1];
      },
    });
  }
  const text = Response.prototype.text;
  Response.prototype.text = async function () { return cap(await text.call(this)); };
})();

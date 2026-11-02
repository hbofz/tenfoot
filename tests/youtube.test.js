// node tests/youtube.test.js : checks inject/youtube.js
const assert = require("assert");
const fs = require("fs");
const src = fs.readFileSync(__dirname + "/../inject/youtube.js", "utf8");
const run = (loc) => {
  const g = { location: loc, Response: class { async json() { return {}; } }, setInterval() {},
              window: {}, JSON: { parse: JSON.parse, stringify: JSON.stringify },
              MediaSource: { isTypeSupported: () => true } };  // like Chromium: ignores extra parameters
  new Function(...Object.keys(g), src)(...Object.values(g));
  return g;
};

const yt = run({ hostname: "www.youtube.com", pathname: "/tv", hash: "" });
// No ad handling: a response with ad fields comes through as it was.
const player = yt.JSON.parse(JSON.stringify({ adPlacements: [{ x: 1 }], playerAds: [{ y: 2 }] }));
assert.deepStrictEqual(player, { adPlacements: [{ x: 1 }], playerAds: [{ y: 2 }] });
assert.strictEqual(yt.JSON.stringify({ playbackContext: { contentPlaybackContext: {} } }).includes("NoAd"), false);

const fmts = yt.JSON.parse(JSON.stringify({ streamingData: { adaptiveFormats: [
  { mimeType: 'video/webm; codecs="vp9"' }, { mimeType: 'video/mp4; codecs="avc1.640028"' },
  { mimeType: 'video/mp4; codecs="av01.0.08M.08"' }, { mimeType: 'audio/webm; codecs="opus"' },
] } }));
assert.deepStrictEqual(fmts.streamingData.adaptiveFormats.map((f) => f.mimeType.split('"')[1]), ["avc1.640028", "opus"]);
const fps = yt.JSON.parse(JSON.stringify({ streamingData: { adaptiveFormats: [
  { mimeType: 'video/mp4; codecs="avc1.64002a"', height: 1080, fps: 60 },
  { mimeType: 'video/mp4; codecs="avc1.640028"', height: 1080, fps: 30 },
  { mimeType: 'video/mp4; codecs="avc1.4d401f"', height: 720, fps: 60 },
  { mimeType: 'audio/mp4; codecs="mp4a.40.2"' },
] } }));
assert.deepStrictEqual(fps.streamingData.adaptiveFormats.map((f) => f.fps || "audio"), [60, 30, 60, "audio"]); // hardware decode: 60fps is fine
const only60 = yt.JSON.parse(JSON.stringify({ streamingData: { adaptiveFormats: [
  { mimeType: 'video/mp4; codecs="avc1.64002a"', fps: 60 }, { mimeType: 'audio/mp4; codecs="mp4a"' } ] } }));
assert.strictEqual(only60.streamingData.adaptiveFormats.length, 2); // 60fps-only video still plays

const its = yt.MediaSource.isTypeSupported;  // the player's 60fps probe: valid yes, impossible no
assert.strictEqual(its('video/webm; codecs="vp9"; framerate=30'), true);
assert.strictEqual(its('video/webm; codecs="vp9"; framerate=9999'), false);
assert.strictEqual(its('video/mp4; codecs="avc1.64002A"; width=1920; height=1080; framerate=60'), true);
assert.strictEqual(its('video/mp4; codecs="avc1.64002A"'), true);

const vp9only =yt.JSON.parse(JSON.stringify({ streamingData: { adaptiveFormats: [{ mimeType: 'video/webm; codecs="vp9"' }] } }));
assert.strictEqual(vp9only.streamingData.adaptiveFormats.length, 1); // no H.264 offered: leave it playable

const sr = yt.JSON.parse(JSON.stringify({ streamingData: { adaptiveFormats: [
  { mimeType: 'video/mp4; codecs="avc1.640028"', height: 1080, fps: 30, xtags: "CgcKAnNyEgEx" },
  { mimeType: 'video/mp4; codecs="avc1.4d401e"', height: 480, fps: 30 },
  { mimeType: 'audio/mp4; codecs="mp4a.40.2"' },
] } }));
assert.deepStrictEqual(sr.streamingData.adaptiveFormats.map((f) => f.height || "audio"), [480, "audio"]); // the real 480p, not the upscale
const srOnly = yt.JSON.parse(JSON.stringify({ streamingData: { adaptiveFormats: [
  { mimeType: 'video/mp4; codecs="avc1.640028"', xtags: "CgcKAnNyEgEx" } ] } }));
assert.strictEqual(srOnly.streamingData.adaptiveFormats.length, 1); // nothing else on offer: still plays

const clean = yt.JSON.parse('{"title":"plain","items":[1,2]}');
assert.deepStrictEqual(clean, { title: "plain", items: [1, 2] });

(async () => {
  const r = await new yt.Response().json();       // fetch().json() path is hooked too
  assert.deepStrictEqual(r, {});
  const other = run({ hostname: "www.google.com", pathname: "/", hash: "" });
  assert.strictEqual(other.window.__tenfoot, undefined); // other sites untouched
  const desk = run({ hostname: "www.youtube.com", pathname: "/watch", hash: "" });
  assert.strictEqual(desk.window.__tenfoot, undefined);  // only the TV app
  console.log("youtube ok");
})();

// node tests/youtube.test.js : checks inject/youtube.js
const assert = require("assert");
const fs = require("fs");
const src = fs.readFileSync(__dirname + "/../inject/youtube.js", "utf8");
const run = (loc, body = {}) => {
  const g = { location: loc, Response: class { async text() { return JSON.stringify(body); } }, setInterval() {},
              window: {}, JSON: { parse: JSON.parse, stringify: JSON.stringify },
              MediaSource: { isTypeSupported: () => true } };  // like Chromium: ignores extra parameters
  new Function(...Object.keys(g), src)(...Object.values(g));
  return g;
};

const yt = run({ hostname: "www.youtube.com", pathname: "/tv", hash: "" });
// YouTube's own ads: the player's schedule goes, the video's formats are still sorted.
const player = yt.JSON.parse(JSON.stringify({ adPlacements: [{ x: 1 }], playerAds: [{ y: 2 }], adSlots: [{ z: 3 }], videoDetails: { id: "v" },
  streamingData: { adaptiveFormats: [{ mimeType: 'video/webm; codecs="vp9"' }, { mimeType: 'video/mp4; codecs="avc1.640028"' }] } }));
assert.deepStrictEqual(Object.keys(player).sort(), ["streamingData", "videoDetails"]);
assert.strictEqual(player.streamingData.adaptiveFormats.length, 1);
// ...wherever the player response sits
assert.deepStrictEqual(yt.JSON.parse(JSON.stringify([{ playerResponse: { adPlacements: [1], ok: 1 } }])), [{ playerResponse: { ok: 1 } }]);
// the home screen: the banner, ad tiles in the list and inside a row, and a Short that's an ad
const home = yt.JSON.parse(JSON.stringify({ contents: { tvBrowseRenderer: { content: { sectionListRenderer: { contents: [
  { tvMastheadRenderer: {} }, { adSlotRenderer: {} }, { promoShelfRenderer: {} },
  { shelfRenderer: { content: { horizontalListRenderer: { items: [{ tileRenderer: { id: 1 } }, { adSlotRenderer: {} }, { tileRenderer: { id: 2 } }] } } } },
] } } } }, entries: [{ command: { reelWatchEndpoint: { adClientParams: { isAd: true } } } }, { command: { reelWatchEndpoint: { videoId: "s" } } }] }));
const shelves = home.contents.tvBrowseRenderer.content.sectionListRenderer.contents;
assert.strictEqual(shelves.length, 1);
assert.deepStrictEqual(shelves[0].shelfRenderer.content.horizontalListRenderer.items.map((i) => i.tileRenderer.id), [1, 2]);
assert.deepStrictEqual(home.entries, [{ command: { reelWatchEndpoint: { videoId: "s" } } }]);
assert.ok(yt.window.__tenfoot.ads >= 8);
// a Shorts feed on its own: "isAd" is all there is to go on
assert.strictEqual(yt.JSON.parse(JSON.stringify({ entries: [{ command: { reelWatchEndpoint: { adClientParams: { isAd: true } } } }, { id: 1 }] })).entries.length, 1);
// odd shapes never throw
for (const odd of ['{"adSlots":null}', '{"contents":"x","isAd":1}', '"adSlots"', "null", "[null,1]"]) yt.JSON.parse(odd);
// asking for a video: "no ads", on a copy (the app's own object may be frozen); anything else as it was
const req = Object.freeze({ context: {}, playbackContext: Object.freeze({ contentPlaybackContext: Object.freeze({ vis: 0 }) }) });
assert.deepStrictEqual(JSON.parse(yt.JSON.stringify(req)).playbackContext.contentPlaybackContext, { vis: 0, isInlinePlaybackNoAd: true });
assert.deepStrictEqual(req.playbackContext.contentPlaybackContext, { vis: 0 });
assert.strictEqual(yt.JSON.stringify({ a: 1 }), '{"a":1}');
assert.strictEqual(yt.JSON.stringify({ a: 1 }, null, 1), '{\n "a": 1\n}');

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
  const ads = run({ hostname: "www.youtube.com", pathname: "/tv", hash: "" }, { playerAds: [1], items: [{ adSlotRenderer: {} }, { ok: 1 }] });
  assert.deepStrictEqual(await new ads.Response().json(), { items: [{ ok: 1 }] });  // and stripped there too
  const other = run({ hostname: "www.google.com", pathname: "/", hash: "" });
  assert.strictEqual(other.window.__tenfoot, undefined); // other sites untouched
  const desk = run({ hostname: "www.youtube.com", pathname: "/watch", hash: "" });
  assert.strictEqual(desk.window.__tenfoot, undefined);  // only the TV app
  console.log("youtube ok");
})();

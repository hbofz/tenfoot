// Injected with youtube.js into every page. The mouse pointer as a ring big enough to see from the
// couch: the remote's cursor (tenfoot/cursor.py) and the phone's touchpad move it. It's the
// system's pointer with a bigger picture, so the screen draws it, smooth however busy the page is (a
// ring the page drew lagged on a busy page); a few seconds after it stops, it hides.
(() => {  // (in frames too: the pointer there is the frame's)
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="56" height="56"><circle cx="28" cy="28" r="25" fill="none" ' +
              'stroke="rgba(0,0,0,.7)" stroke-width="4"/><circle cx="28" cy="28" r="21" fill="rgba(255,255,255,.3)" stroke="#fff" stroke-width="5"/></svg>';
  const RING = `url("data:image/svg+xml,${encodeURIComponent(svg)}") 28 28, default`;
  const style = document.createElement("style");
  let shown = false, idle;
  const show = (on) => { shown = on; style.textContent = `html, html * { cursor: ${on ? RING : "none"} !important; }`; };
  addEventListener("mousemove", (e) => {
    if (!e.isTrusted || !(e.movementX || e.movementY)) return;  // (not a resting pointer the page scrolls under)
    if (!style.isConnected) document.documentElement.append(style);
    if (!shown) show(true);
    clearTimeout(idle);
    idle = setTimeout(() => show(false), 5000);
  }, true);
})();

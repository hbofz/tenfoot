// Injected with youtube.js; only acts on Spotify's web player. Spotify has no TV web app,
// so scale the desktop player up to couch size (1920x1080 then lays out like 1280x720).
(() => {
  if (location.hostname !== "open.spotify.com") return;
  const zoom = () => (document.documentElement.style.zoom = "1.5");
  if (document.documentElement) zoom();
  document.addEventListener("DOMContentLoaded", zoom);
})();

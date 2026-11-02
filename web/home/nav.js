// Arrow keys on the home screen: a grid of app tiles, COLS across. Returns the tile to focus, or -1 when the key
// runs into an edge (the page nudges the tile instead, like tvOS: nothing wraps around).
// Down into a shorter last row lands on its last tile.
const COLS = 6;
function move(i, key, n, cols = COLS) {
  const col = i % cols, row = Math.floor(i / cols), rows = Math.ceil(n / cols);
  if (key === "ArrowLeft") return col ? i - 1 : -1;
  if (key === "ArrowRight") return col < cols - 1 && i + 1 < n ? i + 1 : -1;
  if (key === "ArrowUp") return row ? i - cols : -1;
  if (key === "ArrowDown") return row < rows - 1 ? Math.min(i + cols, n - 1) : -1;
  return i;
}

if (typeof module !== "undefined") module.exports = { move, COLS };
else window.nav = { move, COLS };

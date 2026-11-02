// node tests/nav.test.js : checks the home screen's arrow keys in web/home/nav.js
const assert = require("assert");
const { move } = require("../web/home/nav.js");
const n = 12;  // two full rows of six
assert.strictEqual(move(0, "ArrowRight", n), 1);
assert.strictEqual(move(0, "ArrowLeft", n), -1);  // edges nudge, nothing wraps
assert.strictEqual(move(5, "ArrowRight", n), -1);
assert.strictEqual(move(6, "ArrowLeft", n), -1);
assert.strictEqual(move(2, "ArrowDown", n), 8);
assert.strictEqual(move(8, "ArrowUp", n), 2);
assert.strictEqual(move(2, "ArrowUp", n), -1);
assert.strictEqual(move(8, "ArrowDown", n), -1);
// a short last row: Down lands on its last tile, Right stops at it
assert.strictEqual(move(4, "ArrowDown", 8), 7);
assert.strictEqual(move(7, "ArrowRight", 8), -1);
assert.strictEqual(move(7, "ArrowUp", 8), 1);
assert.strictEqual(move(3, "Enter", n), 3);
console.log("nav ok");

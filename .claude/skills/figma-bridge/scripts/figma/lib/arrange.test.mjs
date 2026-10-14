import { test } from "node:test";
import assert from "node:assert/strict";
import { shelf, grid, prefix, contains } from "./arrange.mjs";

test("shelf keeps a row within budget, wraps when the next cell overflows", () => {
  const cells = [
    { id: "a", w: 100, h: 50 },
    { id: "b", w: 100, h: 80 },
    { id: "c", w: 100, h: 50 },
  ];
  // budget 260, colGap 10: a(0)+b(110) = 210 fits; c would start at 220, 220+100=320 > 260 → wrap.
  const { placed, bottom } = shelf(cells, 0, 0, 260, 10, 20);
  assert.deepEqual(placed.map((p) => [p.id, p.nx, p.ny]), [["a", 0, 0], ["b", 110, 0], ["c", 0, 100]]);
  // row 1 height = max(50,80)=80, +rowGap 20 → row 2 at y=100; bottom = 100 + 50.
  assert.equal(bottom, 150);
});

test("grid lays fixed columns, row height = tallest cell in the row", () => {
  const cells = [
    { id: "a", w: 100, h: 50 },
    { id: "b", w: 100, h: 90 },
    { id: "c", w: 100, h: 50 },
  ];
  const { placed } = grid(cells, 2, 0, 0, 10, 20); // 2 cols
  assert.deepEqual(placed.map((p) => [p.id, p.nx, p.ny]), [["a", 0, 0], ["b", 110, 0], ["c", 0, 110]]);
  // row 1 tallest = 90, +rowGap 20 → row 2 at y = 110.
});

test("prefix splits on delimiter, falls back to 'misc' when absent or at index 0", () => {
  assert.equal(prefix("WORKFLOW — AUTH", "—"), "WORKFLOW");
  assert.equal(prefix("no delimiter here", "—"), "misc");
  assert.equal(prefix("— leading", "—"), "misc"); // delim at index 0 → not a real prefix
});

test("contains is strict and rejects equal-area / outside frames", () => {
  const B = { ax: 0, ay: 0, w: 100, h: 100 };
  assert.equal(contains(B, { ax: 10, ay: 10, w: 20, h: 20 }), true);  // inside, B larger
  assert.equal(contains(B, { ax: 0, ay: 0, w: 100, h: 100 }), false); // equal area → not strictly larger
  assert.equal(contains(B, { ax: 50, ay: 50, w: 80, h: 80 }), false); // spills outside B
});

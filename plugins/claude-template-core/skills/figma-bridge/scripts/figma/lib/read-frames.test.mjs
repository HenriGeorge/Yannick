import { test } from "node:test";
import assert from "node:assert/strict";
import { toFrame } from "./read-frames.mjs";

test("toFrame maps bounds + local position (absolute ≠ local, so each field is pinned)", () => {
  const child = { id: "1:2", name: "Hero", type: "FRAME" };
  // Distinct absolute (bbox) vs local (localPosition) values: a mutation swapping ox←b.x would now flip this test.
  const info = { absoluteBoundingBox: { x: 10, y: 20, width: 300, height: 400 }, localPosition: { x: 7, y: 13 } };
  assert.deepEqual(toFrame(child, info), { id: "1:2", name: "Hero", type: "FRAME", ax: 10, ay: 20, w: 300, h: 400, ox: 7, oy: 13 });
});

test("toFrame returns null when bounds are missing", () => {
  assert.equal(toFrame({ id: "1:2", name: "x", type: "FRAME" }, { localPosition: { x: 0, y: 0 } }), null);
});

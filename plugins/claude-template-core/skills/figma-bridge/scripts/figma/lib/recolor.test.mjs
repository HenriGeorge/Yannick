import { test } from "node:test";
import assert from "node:assert/strict";
import { hexToColor, makeMatcher, isWhite } from "./recolor.mjs";

test("hexToColor normalizes #rrggbb to 0..1 rgba, with/without leading #", () => {
  assert.deepEqual(hexToColor("#ffffff"), { r: 1, g: 1, b: 1, a: 1 });
  assert.deepEqual(hexToColor("000000"), { r: 0, g: 0, b: 0, a: 1 });
  const ink = hexToColor("#0a0a0a");
  assert.ok(Math.abs(ink.r - 10 / 255) < 1e-9 && ink.a === 1);
  assert.throws(() => hexToColor("#fff"), /bad hex/);
});

test("makeMatcher: exact name vs /regex/ selector", () => {
  const exact = makeMatcher("nav");
  assert.equal(exact("nav"), true);
  assert.equal(exact("nav0"), false); // exact, not prefix
  const re = makeMatcher("/^nav\\d+$/");
  assert.equal(re("nav0"), true);
  assert.equal(re("nav7"), true);
  assert.equal(re("nav"), false);
  assert.equal(re("navbar"), false);
});

test("isWhite is true only when every channel is near 1", () => {
  assert.equal(isWhite({ r: 1, g: 1, b: 1 }), true);
  assert.equal(isWhite({ r: 0.95, g: 0.95, b: 0.95 }), true);
  assert.equal(isWhite({ r: 0.55, g: 0.55, b: 0.55 }), false); // #8c8c8c grey
  assert.equal(isWhite(null), false);
});

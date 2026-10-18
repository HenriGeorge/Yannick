import { test } from "node:test";
import assert from "node:assert/strict";
import { diffVars, collectVars } from "./vars.mjs";

test("collectVars reads collections[].variables, raw rgba per mode, skips aliases + other collections", () => {
  const res = {
    collections: [
      { name: "Restraint", variables: [
        { name: "ink", resolvedType: "COLOR", valuesByMode: { "1:0": { r: 0, g: 0, b: 0, a: 1 } } },
        { name: "alias", resolvedType: "COLOR", valuesByMode: { "1:0": { type: "VARIABLE_ALIAS", id: "X" } } },
        { name: "gap", resolvedType: "FLOAT", valuesByMode: { "1:0": 8 } },
      ] },
      { name: "Other", variables: [{ name: "nope", resolvedType: "COLOR", valuesByMode: { "1:0": { r: 1, g: 1, b: 1, a: 1 } } }] },
    ],
  };
  assert.deepEqual(collectVars(res, "Restraint"), [{ name: "ink", rgba: { r: 0, g: 0, b: 0, a: 1 } }]);
});

function hexToRgba(hex) { const n = parseInt(hex.slice(1), 16); return { r: ((n >> 16) & 255) / 255, g: ((n >> 8) & 255) / 255, b: (n & 255) / 255, a: 1 }; }
const t = (name, hex) => ({ name, hex, value: hexToRgba(hex) });

test("diffVars buckets missing/extra/changed within tolerance", () => {
  const css = [t("ink", "#000000"), t("paper", "#ffffff"), t("red", "#ff0000")];
  const figma = [
    { name: "ink", rgba: { r: 0, g: 0, b: 0, a: 1 } },          // same
    { name: "paper", rgba: { r: 1, g: 1, b: 0.5, a: 1 } },      // changed
    { name: "ghost", rgba: { r: 0.2, g: 0.2, b: 0.2, a: 1 } },  // extra
  ];
  const d = diffVars(css, figma, 1 / 255);
  assert.deepEqual(d.missing.map((m) => m.name), ["red"]);
  assert.deepEqual(d.extra.map((e) => e.name), ["ghost"]);
  assert.deepEqual(d.changed.map((c) => c.name), ["paper"]);
});

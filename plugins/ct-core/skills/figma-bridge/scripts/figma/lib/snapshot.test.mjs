import { test } from "node:test";
import assert from "node:assert/strict";
import { toSnapshot } from "./snapshot.mjs";

test("toSnapshot keeps LOCAL positions only (ox/oy, not absolute ax/ay), id+name label", () => {
  // ax≠ox / ay≠oy so the test pins x←ox (local) — snapshot/restore depend on local coords, not absolute.
  const frames = [{ id: "1:2", name: "A", ax: 100, ay: 200, w: 9, h: 9, ox: 5, oy: 6 }];
  const snap = toSnapshot({ fileKey: "fk", page: "P", channel: "c", frames, now: "2026-10-07T00:00:00Z" });
  assert.deepEqual(snap, { fileKey: "fk", page: "P", channel: "c", savedAt: "2026-10-07T00:00:00Z", frames: [{ id: "1:2", name: "A", x: 5, y: 6 }] });
});

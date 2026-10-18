import { test } from "node:test";
import assert from "node:assert/strict";
import { run } from "./capture.mjs";

// The --storage-state guard must FAIL LOUD on a present-but-unusable value, rather than silently
// dropping auth and capturing the logged-out page. These inputs short-circuit before any lazy
// playwright/esbuild import, so the test needs no capture deps installed.

test("capture run: bare --storage-state (no =path) throws, not a silent unauthenticated capture", async () => {
  await assert.rejects(
    () => run(["--url=https://app.example.com", "--out=/tmp/ct-capture-test.svg", "--storage-state"]),
    /--storage-state requires a file path/,
  );
});

test("capture run: empty --storage-state= throws", async () => {
  await assert.rejects(
    () => run(["--url=https://app.example.com", "--out=/tmp/ct-capture-test.svg", "--storage-state="]),
    /--storage-state requires a file path/,
  );
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { buildStorageState } from "./auth.mjs";

test("buildStorageState: cookies get the origin host + root path", () => {
  const state = buildStorageState({
    origin: "https://admin.example.com",
    cookie: "jwt=abc.def.ghi; theme=dark",
    localStorage: {},
  });
  assert.deepEqual(state.cookies, [
    { name: "jwt", value: "abc.def.ghi", domain: "admin.example.com", path: "/" },
    { name: "theme", value: "dark", domain: "admin.example.com", path: "/" },
  ]);
  assert.deepEqual(state.origins, []); // no localStorage → no origins entry
});

test("buildStorageState: localStorage → one origins entry, values stringified", () => {
  const state = buildStorageState({
    origin: "https://app.example.com",
    cookie: "",
    localStorage: { token: "xyz", count: 3 },
  });
  assert.equal(state.cookies.length, 0);
  assert.deepEqual(state.origins, [
    {
      origin: "https://app.example.com",
      localStorage: [
        { name: "token", value: "xyz" },
        { name: "count", value: "3" },
      ],
    },
  ]);
});

test("buildStorageState: a value with '=' keeps everything after the first '='", () => {
  const state = buildStorageState({
    origin: "https://x.example.com",
    cookie: "sig=a=b=c",
    localStorage: {},
  });
  assert.equal(state.cookies[0].value, "a=b=c");
});

test("buildStorageState: missing origin throws", () => {
  assert.throws(() => buildStorageState({ cookie: "a=1" }), /missing `origin`/);
});

test("buildStorageState: no cookies AND no localStorage throws (nothing to auth with)", () => {
  assert.throws(
    () => buildStorageState({ origin: "https://x.example.com", cookie: "", localStorage: {} }),
    /nothing to authenticate/,
  );
});

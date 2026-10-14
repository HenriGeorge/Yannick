// auth.mjs — build a Playwright storageState from a browser-console session export, so `capture`
// can log into ANY gated page (`capture --storage-state=<state>`). Zero-dep (Node built-ins only:
// node:fs, node:path) — a pure
// JSON transform, no relay, no playwright — so it stays in the core (no `npm install`; see
// tests/test_figma_toolkit.sh FT2/FT3). Generalized from the Resonanz cg-figma `--from-session` path.
//
//   --session=<file>   browser-console export JSON: { origin, cookie, localStorage } (required)
//   --out=<file>       Playwright storageState JSON to write: { cookies, origins } (required)
//
// Produce the input in a logged-in tab's DevTools console (copies to clipboard):
//   copy(JSON.stringify({ origin: location.origin, cookie: document.cookie,
//     localStorage: Object.fromEntries(Object.entries(localStorage)) }, null, 2))
// Note: httpOnly cookies never appear in document.cookie — a site that keeps its session in an
// httpOnly cookie must instead be captured with a headed login (export the whole context). Most SPAs
// stash the token in localStorage, which IS exported here.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

function parseFlags(args) {
  const flags = {};
  for (const a of args) {
    const m = /^--([^=]+)=(.*)$/.exec(a);
    if (m) flags[m[1]] = m[2];
    else if (a.startsWith("--")) flags[a.slice(2)] = true;
  }
  return flags;
}

// A console export → the Playwright storageState shape. Pure: input object → { cookies, origins }.
export function buildStorageState(session) {
  const originUrl = session.origin;
  if (!originUrl) throw new Error("auth: session export is missing `origin` (e.g. https://admin.example.com)");
  const host = new URL(originUrl).hostname;

  const cookies = String(session.cookie || "")
    .split("; ")
    .filter(Boolean)
    .map((pair) => {
      const eq = pair.indexOf("=");
      const name = eq === -1 ? pair : pair.slice(0, eq);
      const value = eq === -1 ? "" : pair.slice(eq + 1);
      return { name, value, domain: host, path: "/" };
    });

  const localStorage = Object.entries(session.localStorage || {}).map(([name, value]) => ({
    name,
    value: String(value),
  }));
  const origins = localStorage.length ? [{ origin: originUrl, localStorage }] : [];

  if (!cookies.length && !localStorage.length) {
    throw new Error("auth: session export has no cookies and no localStorage — nothing to authenticate with");
  }
  return { cookies, origins };
}

export async function run(args) {
  const flags = parseFlags(args);
  const sessionFile = flags.session;
  const outFile = flags.out;
  if (!sessionFile || !outFile) {
    throw new Error("auth: --session=<console-export.json> and --out=<storageState.json> are required");
  }
  let session;
  try {
    session = JSON.parse(readFileSync(sessionFile, "utf8"));
  } catch (err) {
    throw new Error(`auth: cannot read/parse --session=${sessionFile}: ${err?.message ?? err}`);
  }
  const state = buildStorageState(session);
  mkdirSync(dirname(outFile), { recursive: true });
  writeFileSync(outFile, JSON.stringify(state, null, 2), "utf8");
  console.log(
    `[auth] WROTE ${outFile}  cookies=${state.cookies.length}  localStorage=${state.origins[0]?.localStorage.length ?? 0}`,
  );
}

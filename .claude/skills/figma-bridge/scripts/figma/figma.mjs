#!/usr/bin/env node
// figma.mjs — one CLI for the quota-free ClaudeTalkToFigma bridge (relay :3055).
//
// A THIN dispatcher, no business logic: it prints help, runs the relay preflight, then lazily
// `await import('./lib/<cmd>.mjs')` and calls its `run(args)`. The capture family
// (`capture`/`export`/`site-capture`) are the ONLY subcommands whose module imports the heavy deps
// (playwright/esbuild/dom-to-svg), and
// they do so LAZILY inside run() — so dispatching a core subcommand loads zero deps and runs with no
// `npm install` (the load-bearing R5 guarantee; a static capture import at the top of THIS file or any
// core lib/ module would break it — see tests/test_figma_toolkit.sh FT2/FT2b). Do not add such imports.
//
// Node ≥21 ESM, built-in global WebSocket (no `ws` dep).

const SUBCOMMANDS = {
  // core — zero-dep (Node + built-in WebSocket only)
  tokens: "CSS custom-property hex → Figma COLOR variables (--css --prefix --collection)",
  place: "stream one SVG straight into a Figma page (set_svg)",
  rebind: "rebind an SVG's variable references to a Figma collection (--collection)",
  probe: "probe channels → the live channel's pages + fileKey (--all [--base] [--max] verifies <base>_1..N)",
  page: "ensure / rename / set-current a Figma page",
  png: "export a Figma selection → PNG on disk (--all --filter --channel)",
  arrange: "tidy a page's top-level frames into grouped bands (--page --cols --dry-run)",
  recolor: "set solid fills on a frame's direct children by name/regex (--set=sel=hex --white --other)",
  reactions: "wire prototype ON_CLICK→NAVIGATE/URL reactions from a flow-map JSON (--map, write-only)",
  vars: "CSS↔Figma variable drift check (--css --prefix --collection [--strict])",
  snapshot: "save a page's frame positions to JSON (undo net) (--page --out)",
  restore: "move frames back to a saved snapshot (--in=<file>)",
  auth: "build a Playwright storageState from a browser-console export, for `capture --storage-state` (--session --out)",
  // site-to-figma pipeline — palette/build/verify are core (relay only); site-capture needs playwright
  "site-palette": "resolve a project's DS via its Code Connect index → palette cache (--config)",
  "site-build": "assemble screens from a per-project screens JSON → cloned DS instances (--config --theme)",
  "site-verify": "read back a built screen → structural checklist → --png (--config)",
  // capture — optional deps, lazy-imported (needs `npm install --prefix <this dir>`)
  capture: "live page → sharp vector SVG (needs npm install: playwright/esbuild/dom-to-svg)",
  export: "config-driven: capture N targets → validate → distribute set_svg (needs npm install)",
  "site-capture": "site-to-figma: auth + full-page crawl of N routes → PNGs + manifest (needs npm install; --config)",
  lanes: "launch N parallel Figma agents (one file/channel/session each) — starts its own relay",
};

const CORE = ["tokens", "place", "rebind", "probe", "page", "png", "arrange", "recolor", "reactions", "vars", "snapshot", "restore", "auth", "site-palette", "site-build", "site-verify", "lanes"];
const CAPTURE = ["capture", "export", "site-capture"];
// `lanes` starts the relay itself (ensureRelay), so it must bypass the normal assertRelay
// preflight — asserting a relay that isn't up yet would always fail before lanes gets a chance
// to spawn it.
// `auth` is a pure file transform (no relay); `lanes` starts the relay itself. Both skip assertRelay.
const PREFLIGHT_EXEMPT = new Set(["lanes", "auth"]);

function printHelp(out) {
  out("figma.mjs — ClaudeTalkToFigma bridge toolkit (relay ws://localhost:3055)\n");
  out("usage: node figma.mjs <subcommand> [options]\n");
  out("subcommands:");
  for (const name of [...CORE, ...CAPTURE]) {
    out(`  ${name.padEnd(8)} ${SUBCOMMANDS[name]}`);
  }
  out("");
  out(`  core (zero-dep, no install):  ${CORE.join(" ")}`);
  out(`  capture (needs npm install):  ${CAPTURE.join(" ")}`);
  out("");
  out("Prereq: the ClaudeTalkToFigma plugin must be running & joined (Figma Command+P).");
  out("Override the relay URL with FIGMA_WS_URL; the channel with --channel or FIGMA_CHANNEL.");
}

const args = process.argv.slice(2);
const cmd = args[0];
// PO8: `-h`/`--help` anywhere, or no subcommand → print help and exit 0 WITHOUT preflight or import
// (so `tokens --help` never touches :3055 and never needs the subcommand module to exist).
const wantsHelp = args.includes("-h") || args.includes("--help");

if (wantsHelp || !cmd) {
  printHelp(console.log);
  process.exit(0);
}

if (!SUBCOMMANDS[cmd]) {
  console.error(`figma.mjs: unknown subcommand "${cmd}"\n`);
  printHelp(console.error);
  process.exit(2);
}

// RUN path: preflight the relay, then dispatch. All errors surface as the message ONLY (never a raw
// stack) so a wedged relay / dep-missing reads legibly.
const socketUrl = process.env.FIGMA_WS_URL ?? "ws://localhost:3055";
try {
  // `restore` lives in snapshot.mjs as runRestore (the snapshot/restore pair shares one module).
  const mod = await import(`./lib/${cmd === "restore" ? "snapshot" : cmd}.mjs`);
  if (!PREFLIGHT_EXEMPT.has(cmd)) {
    const { assertRelay } = await import("./lib/preflight.mjs");
    await assertRelay(socketUrl);
  }
  await (cmd === "restore" ? mod.runRestore : mod.run)(args.slice(1));
} catch (err) {
  console.error(err?.message ?? String(err));
  process.exit(1);
}

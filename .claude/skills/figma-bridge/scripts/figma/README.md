# figma-bridge toolkit

Last updated: 2026-10-13 20:14

One CLI (`figma.mjs`) for the **quota-free ClaudeTalkToFigma bridge** — a WebSocket relay
(`ws://localhost:3055`) into a running Figma plugin, with **no** API quota (unlike the official
Figma MCP). A thin dispatcher lazily loads one subcommand module per invocation; a shared `lib/`
backbone (`relay-client`, `channel-resolve`, `preflight`) owns the wire protocol once.

## Prerequisites

- **Node ≥21** (built-in global `WebSocket` — no `ws` dependency).
- **The relay live and joined.** In Figma: `Command+P` → run the ClaudeTalkToFigma plugin. The CLI
  auto-discovers the live channel from the relay's `/status` endpoint; override the relay URL with
  `FIGMA_WS_URL`, or pin the channel with `--channel` / `FIGMA_CHANNEL` (the folder name is used only
  when `/status` is unreachable).
  A RUN subcommand against a down relay exits non-zero with a legible `Command+P` hint, never a raw
  `ECONNREFUSED` / socket stack.
- **Capture deps (only for `capture` / `export`):** `npm install --prefix <this dir>` (pulls the
  `optionalDependencies` `playwright` / `esbuild` / `dom-to-svg`). Core subcommands need no install.

## Invoke

```bash
node figma.mjs <subcommand> [flags]      # from this dir
node "${CLAUDE_PROJECT_DIR}/.claude/skills/figma-bridge/scripts/figma/figma.mjs" <subcommand> [flags]   # from a consumer repo
```

`--help` (anywhere) or a bare `figma.mjs` prints help and exits 0 without touching the relay.

## Zero-dep core vs capture split

| Family | Subcommands | Install |
|---|---|---|
| **core** | `tokens` `place` `rebind` `probe` `page` `png` `arrange` `reactions` `snapshot` `restore` `vars` `auth` `lanes` | none — Node + built-in WebSocket only |
| **capture** | `capture` `export` | `npm install --prefix <this dir>` (playwright/esbuild/dom-to-svg) |

`capture`/`export` `await import()` the heavy deps *inside* `run()`, so dispatching a core
subcommand loads zero deps. A capture run with the deps absent exits non-zero with the
`npm install --prefix …` hint (never a raw `MODULE_NOT_FOUND`). No static capture-dep import is
allowed in `figma.mjs` or any core `lib/*.mjs` — it would break the zero-dep guarantee.

## The three pipelines

### 1. Token sync (code → Figma variables)

```bash
node figma.mjs tokens --css=src/styles/theme.css --prefix=--brand- --collection=brand
```

Reads every `--brand-*` custom property whose value is a hex color and writes a Figma COLOR
variable into the `brand` collection. `--dry-run` parses + reports offline (no relay). Channel
flags: `--channel=<id>` (repeatable), `--file-key=<key>` to disambiguate live channels.

### 2. page → svg → figma

```bash
npm install --prefix .                                            # once (capture deps)
node figma.mjs capture --url=http://localhost:3000/pricing --out=out/pricing.svg \
  --strip-images --strip-selectors='#dev-overlay,.toast'
node figma.mjs place --svg=out/pricing.svg --x=0 --y=0 --name=Pricing
```

`capture` renders a live page to a sharp vector SVG (Playwright + dom-to-svg); `place` streams one
SVG into a Figma page via `set_svg`. `capture` flags: `--selector` (one element),
`--strip-images`, `--strip-selectors=<csv>`, `--detect-error-boundary`, `--viewport-width=<px>`
(default 1440), `--max-height=<px>` (truncate + disclose), `--min-text=<n>` (min `<text>` nodes to count as a real
capture, default 5 — lower for low-text visual components), `--inline-remote-images` (opt-in — see
Security), `--storage-state=<file>` (log into a gated page — build the file with `auth`).

**Capturing a gated page** — `capture` runs a fresh, logged-OUT browser, so a login-gated URL
captures the login screen. To capture behind auth, build a Playwright storageState with `auth` from
a browser-console session export, then pass `--storage-state`:

```bash
# In a logged-in tab's DevTools console (copies the export to the clipboard):
#   copy(JSON.stringify({ origin: location.origin, cookie: document.cookie,
#     localStorage: Object.fromEntries(Object.entries(localStorage)) }, null, 2))
# ⚠ session.json AND state.json hold LIVE session tokens — write them OUTSIDE the repo
#   (a tmp dir), never into a tracked path, so `git add` can't commit a secret.
mkdir -p /tmp/figma-auth
# Save the console export to /tmp/figma-auth/session.json, then:
node figma.mjs auth --session=/tmp/figma-auth/session.json --out=/tmp/figma-auth/state.json
node figma.mjs capture --url=https://app.example.com/dashboard --out=out/dash.svg --storage-state=/tmp/figma-auth/state.json
```

`auth` is zero-dep (a pure JSON transform: `{origin, cookie, localStorage}` → Playwright
`{cookies, origins}`). ⚠ httpOnly session cookies never appear in `document.cookie`; a site whose
session lives only in an httpOnly cookie needs a headed-login export instead. Most SPAs stash the
token in localStorage, which the console export carries. `export` is the config-driven batch form: capture N targets → validate (xmllint) →
distribute `set_svg` round-robin across resolved live channels (`--config`, `--only`,
`--capture-only`, `--no-capture`, `--resolve-only`, `--new-page`; per-target/`cfg.inlineRemote`).
See `figma-export.config.example.json`.

> **Security — `capture`/`export` drive a headless browser.** Both navigate a real Chromium to any
> `--url` and fully execute its JavaScript. **Only target pages you trust.** Server-side image
> inlining (`--inline-remote-images` / `inlineRemote`) is **off by default** and, when enabled,
> refuses loopback / link-local / RFC-1918 / IPv6-ULA hosts (SSRF guard) and does not follow
> redirects. Config `target.file` paths that escape `outDir` (`..` / absolute) are rejected.

### 3. rebind bridge (SVG fills → Figma variables)

```bash
node figma.mjs rebind --root=<nodeId> --collection=brand --dry-run   # preview matches
node figma.mjs rebind --root=<nodeId> --collection=brand             # bind
```

Walks the subtree under `--root`; for every node whose SOLID fill equals a variable's value, binds
the fill to that variable. `--strokes` also rebinds strokes; `--dry-run` reports read-only;
`--max=<N>` caps binds (safety, not a failure).

## Other subcommands

- `probe [--channel=<id>]` (repeatable; auto-discovers from the relay `/status` when none given, `FIGMA_CHANNEL` seeds one) → the live channel's pages + fileKey.
- `page --name=<pageName> [--file-key]` — ensure / rename / set-current a page.
- `png [--all --filter=<substr> --scale=N --out=<dir> --channel]` — export selected frames → PNG on disk.
- `lanes [channel=fileKey[@cwd] ...] [--max=N] [--prime=<text>] [--no-spawn]` — fan a single macOS
  Figma launch out over N parallel channels/files, each in its own detached tmux session (also
  reachable via `bin/figma-lanes`). Persistent default: `FIGMA_LANES` / `FIGMA_LANES_MAX` in
  `.claude/worktrees.conf` (env/CLI still wins). `lanes` starts/probes its own relay per lane
  instead of requiring one already up, so it is **preflight-exempt** — the normal "relay not
  responding, run the ClaudeTalkToFigma plugin" dispatcher check is skipped for it.
- `arrange [--page=<name> --delimiter=<s> --cols=N --budget --col-gap --row-gap --band-gap --start-x --start-y --group-sort=name|count|size --sort=name|none --no-glue --include=<s> --exclude=<s> --dry-run]`
  — tidy a page's top-level frames into vertical bands grouped by the name prefix before `--delimiter`
  (default `—`; no match → `misc`). Each band is shelf-packed to `--budget` width, or a fixed `--cols`
  grid. A frame fully contained in another is auto-glued as an overlay and follows its parent (disable
  with `--no-glue`). Reads bounds one `get_node_info depth:0` at a time and streams `move_node`s
  serially, so a bulk read never severs and a write burst never drops the plugin. `--dry-run` prints
  the computed plan without moving anything.
- `snapshot [--page=<name> --out=<file> --channel --file-key]` — save the current page's top-level
  frame positions (`{fileKey,page,channel,savedAt,frames:[{id,name,x,y}]}`) to JSON; an undo net for
  any move command. Default `./figma-snapshot-<page>.json`.
- `restore --in=<file> [--channel --file-key]` — move frames back to a saved snapshot, matched by node
  id (name is a label; absent ids skipped, nonzero exit if none match). Operates on the current page
  (does not switch — the bridge's `set_current_page` is unreliable; ids are file-unique anyway).
- `vars --css=<file> --prefix=<s> --collection=<name> [--strict] [--channel --file-key]` — read-only
  CSS↔Figma variable drift check: `--prefix`-matched CSS props vs the live `--collection`
  (`collections[].variables`, first mode, raw `{r,g,b,a}` only — `VARIABLE_ALIAS` values skipped),
  reporting missing / extra / changed with a ±1/255 color tolerance. `--strict` exits 1 on any drift.
- `reactions --map=<file.json> [--verify --dry-run --channel --file-key]` — wire prototype `ON_CLICK`
  → NAVIGATE / OPEN-URL reactions from a flow-map JSON (the one place the `set_reactions` wire-schema
  lives). Write-only by default; `--verify` does one spaced `get_reactions` read-back per write
  (batched reads WEDGE the plugin — see `../GOTCHAS.md`). Exits non-zero if any write failed.

## Wire protocol

All subcommands talk to Figma through `lib/relay-client.mjs` (the only `new WebSocket(`), framing
reverse-engineered from the relay + plugin:

- **join:** `{type:'join', channel, id}` → server `{type:'system', message:{id, result:'Connected to channel: …'}}`
- **command:** `{type:'message', channel, message:{id, command, params}}` → the relay echoes it back
  to the sender as a `broadcast` (sender `'You'` — ignored); the plugin's reply unicasts as
  `{type:'broadcast', message:{id, result|error}, sender:'User'}`, matched by `id`.

`channel-resolve.mjs` probes candidate channels and, when several are live, requires `--channel`
(or `--file-key`) to disambiguate. `preflight.mjs` asserts the relay is reachable before any RUN
subcommand dispatches.

## See also

`../../SKILL.md` (the figma-bridge skill — triggers + quick invoke) · the `figma-ui` skill's
`docs/workflow/FIGMA-UI.md` (the free arinspunk bridge vs. the quota-metered official Figma MCP).

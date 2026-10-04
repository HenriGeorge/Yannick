# figma-bridge toolkit

Last updated: 2026-10-04 18:23

One CLI (`figma.mjs`) for the **quota-free ClaudeTalkToFigma bridge** — a WebSocket relay
(`ws://localhost:3055`) into a running Figma plugin, with **no** API quota (unlike the official
Figma MCP). A thin dispatcher lazily loads one subcommand module per invocation; a shared `lib/`
backbone (`relay-client`, `channel-resolve`, `preflight`) owns the wire protocol once.

## Prerequisites

- **Node ≥21** (built-in global `WebSocket` — no `ws` dependency).
- **The relay live and joined.** In Figma: `Command+P` → run the ClaudeTalkToFigma plugin → join a
  channel. Override the relay URL with `FIGMA_WS_URL`, the channel with `--channel` / `FIGMA_CHANNEL`.
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
| **core** | `tokens` `place` `rebind` `probe` `page` `png` `lanes` | none — Node + built-in WebSocket only |
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
(default 1440), `--max-height=<px>` (truncate + disclose), `--inline-remote-images` (opt-in — see
Security). `export` is the config-driven batch form: capture N targets → validate (xmllint) →
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

- `probe --channel=<id>` (repeatable; `FIGMA_CHANNEL` seeds one) → the live channel's pages + fileKey.
- `page --name=<pageName> [--file-key]` — ensure / rename / set-current a page.
- `png [--all --filter=<substr> --scale=N --out=<dir> --channel]` — export selected frames → PNG on disk.
- `lanes [channel=fileKey[@cwd] ...] [--max=N] [--prime=<text>] [--no-spawn]` — fan a single macOS
  Figma launch out over N parallel channels/files, each in its own detached tmux session (also
  reachable via `bin/figma-lanes`). Persistent default: `FIGMA_LANES` / `FIGMA_LANES_MAX` in
  `.claude/worktrees.conf` (env/CLI still wins). `lanes` starts/probes its own relay per lane
  instead of requiring one already up, so it is **preflight-exempt** — the normal "relay not
  responding, run the ClaudeTalkToFigma plugin" dispatcher check is skipped for it.

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

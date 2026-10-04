---
name: figma-bridge
description: Use when driving Figma over the quota-free ClaudeTalkToFigma :3055 relay from the CLI — launching the ClaudeTalkToFigma plugin (Command+P) and joining the project-folder channel, diagnosing when the plugin won't connect / is on the wrong channel, working around bridge reads that sever the socket, syncing CSS-custom-property tokens into Figma COLOR variables, placing/capturing a page as SVG into a Figma frame, rebinding an SVG's fills to a Figma variable collection, probing live channels, or exporting a selection to PNG. NOT for the official metered Figma MCP (that's figma-ui) or lifting a website into the repo's design system (that's design-import).
---

# figma-bridge — one CLI for the ClaudeTalkToFigma relay

A single dispatcher (`figma.mjs`) drives the quota-free ClaudeTalkToFigma bridge over its
WebSocket relay (`ws://localhost:3055`) — zero API quota, unlike the official Figma MCP. Core
subcommands are dependency-free; the capture family needs one `npm install`.

## Prerequisite: the relay must be live and joined

The ClaudeTalkToFigma plugin must be running in Figma and **joined to a channel** — open Figma,
`Command+P`, run the **ClaudeTalkToFigma** plugin, join a channel. A RUN subcommand against a down
relay exits non-zero with a legible `Command+P` hint (never a raw socket stack). Override the URL
with `FIGMA_WS_URL`, the channel with `--channel` / `FIGMA_CHANNEL`.

### Launch the plugin (it needs a human gesture)

Figma will not run a plugin from automation without a user gesture, so **the human runs it**: with
the **file open** (not just the Figma app — a bare `figma://` deep link opens the app with *no
window*, and `Command+P` needs a window), bring **Figma to the front**, press `Command+P`, type
`ClaudeTalkToFigma`, and press `Enter`. **The patched panel then auto-joins a channel = the open
file's name (`figma.root.name`) — no typing needed**, provided the Figma file is named exactly the
repo folder (so it matches the CLI's `folderChannel()`). The channel field is only a manual override.

Automating the gesture (`osascript` System Events / `cliclick`) needs macOS **Accessibility** granted
to the terminal + `osascript` + Figma (+ `cliclick`), and still only works when **Figma is frontmost
with a window open** — otherwise `Command+P` lands on whatever app IS frontmost (e.g. Chrome's print
dialog; send `Escape` and re-focus Figma). Prefer just asking the human to run it.

On macOS the **`figma_launch` SessionStart hook automates exactly this gesture** once you've imported
the panel + `touch ~/.local/share/claude-template/ctf-imported` (opt out `FIGMA_AUTOLAUNCH_PLUGIN=0`):
it sends `Escape`→`Cmd+P`→`ClaudeTalkToFigma`→`Enter`, then uses this `probe` as the source of truth
(keystrokes are capped) and screenshots the window. See the `figma_launch` entry in `HOOKS.md`.

**Verify before driving:** `probe` must report `CONNECTED` (below) AND take a PNG screenshot (below)
so you're sure the plugin is joined to the *right* channel and Figma is showing what you expect.

### Finding the channel to join

The channel is a free-text label you type into the plugin panel. One project = one channel: use the
**project folder name**. The `figma_launch` SessionStart hook echoes it as `Bridge channel: <folder>`
at startup (issue #830), and it is the default the CLI resolves when no `--channel` / `FIGMA_CHANNEL`
is set (`folderChannel()` = the main-checkout basename, stable across every worktree). Confirm which
channel is actually live with `probe`:

```bash
node "${CLAUDE_PROJECT_DIR}/.claude/skills/figma-bridge/scripts/figma/figma.mjs" probe            # the folder channel
node "${CLAUDE_PROJECT_DIR}/.claude/skills/figma-bridge/scripts/figma/figma.mjs" probe --channel=<id> --channel=<other>
```

`CONNECTED` = the plugin is joined there (reports its pages + `fileKey`); `NOT_CONNECTED` = nothing
joined — open Figma, `Command+P`, run ClaudeTalkToFigma, and join that channel.

**The patched panel is vendored** at `plugins/claude-template-core/vendor/ctf-plugin/` (see its
`VENDOR.md`). Unlike stock CTF (which joins a *random* channel every connect), it **auto-joins the open
file's name on run** (`figma.root.name`, ahead of the random fallback) — so a project whose Figma file
is named after its repo folder joins the right channel with **no typing**. The channel field remains a
manual override and still persists via `figma.clientStorage`. The `figma_launch` hook mirrors the panel to a stable path
(`~/.local/share/claude-template/ctf-plugin/manifest.json`) and prints it at startup; import it once in
Figma Desktop (**Plugins › Development › Import plugin from manifest**), so the version-keyed plugin
cache never breaks the dev-plugin registration.

### Take a screenshot of the design (permission-free)

To capture what's **on the Figma canvas** — not the desktop-app window (an OS window-grab via
`screencapture` needs macOS *Screen Recording* permission, which the CLI/agent process usually
lacks and silently returns a black frame without) — export the frames as PNG straight through the
relay:

```bash
node "${CLAUDE_PROJECT_DIR}/.claude/skills/figma-bridge/scripts/figma/figma.mjs" png --all --out=<dir>            # every SELECTED frame (select the frames/page in Figma first)
node "${CLAUDE_PROJECT_DIR}/.claude/skills/figma-bridge/scripts/figma/figma.mjs" png --filter=<substr> --scale=2  # only selected frames whose name matches, at 2×
```

The PNGs land on disk; view them with the Read tool. This renders the design content itself, so it
never depends on window-capture OS permissions.

### Bridge read gotchas — don't sever the socket

The bridge disconnects the plugin when a read returns too much data (the documented "too big" limit),
and it does not implement selection. Work within these:

- **Read one frame at a time, `depth:0`.** A single-frame `get_node_info` with `depth:0` is safe and
  returns bounds. A whole-page read or `get_node_info depth:1` returns all child frames at once → too
  big → **severs** the plugin. To lay out / measure a page, read each frame's bounds individually.
- **`get_selection` has no bounds** — it returns only `{id, name, type, visible}`, so compute layout
  from per-frame `get_node_info depth:0`, not from the selection.
- **`set_selection` / `select_nodes` → `Unknown command`** — the bridge can't set the selection, so
  you can't auto-select a block for a canvas shot. Verify a selection by eye (select + zoom-to-fit in
  Figma), or PNG-export by name `--filter=` instead of relying on the current selection.
- After a sever, re-`probe`; with the patched panel the channel is unchanged (it persists), so you
  rejoin the same channel rather than hunting a new random id.

## Invoke (in a consumer repo, via the plugin)

```bash
node "${CLAUDE_PROJECT_DIR}/.claude/skills/figma-bridge/scripts/figma/figma.mjs" <subcommand> [flags]
```

`node <...>/figma.mjs --help` lists everything. Run `<subcommand> --help` — it short-circuits
before touching the relay.

## Subcommands

**Core — zero-dep (Node ≥21 + built-in WebSocket, no install):**

- `tokens` — CSS custom-property hex → Figma COLOR variables. `--css=<file> --prefix=--x- --collection=<name>` (`--dry-run` parses offline).
- `place` — stream one SVG straight into a page. `--svg=<file> [--x --y --name]`.
- `rebind` — rebind an SVG subtree's fills to a variable collection. `--root=<nodeId> [--collection --strokes --dry-run --max=N]`.
- `probe` — probe channels → the live channel's pages + fileKey. `--channel=<id>` (repeatable).
- `page` — ensure / rename / set-current a page. `--name=<pageName> [--file-key]`.
- `png` — export a selection → PNG on disk. `[--all --filter=<substr> --scale=N --out=<dir> --channel]`.
- `lanes` — launch N parallel Figma agents (one file/channel/session each); starts its own relay, so it bypasses the normal preflight. `<lane...> [--no-spawn --max=N]` (lane = `channel=fileKey[@cwd]`); also runnable as `bin/figma-lanes`.

**Capture — optional deps (`playwright`/`esbuild`/`dom-to-svg`), lazy-imported:**

- `capture` — live page → sharp vector SVG. `--url=<url> --out=<file.svg> [--selector --strip-images --strip-selectors=<csv> --viewport-width --max-height]`.
- `export` — config-driven: capture N targets → validate → distribute `set_svg`. `[--config --only --capture-only --no-capture --resolve-only --new-page --channel]`.

## Zero-dep core vs capture split

Only `capture`/`export` need the heavy deps, and they `await import()` them *inside* `run()` — so
core subcommands run with **no** `npm install`. Before using `capture`/`export`:

```bash
npm install --prefix "${CLAUDE_PROJECT_DIR}/.claude/skills/figma-bridge/scripts/figma"
```

A capture run with the deps absent exits non-zero with this exact install hint, never a raw
`MODULE_NOT_FOUND`.

## See also

`scripts/figma/README.md` (full pipelines, flags, wire protocol) · `figma-ui` (per-change
checklist; official metered Figma MCP vs. this free bridge) · `docs/workflow/FIGMA-UI.md` (bridge how-to).

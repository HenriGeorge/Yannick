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
`ClaudeTalkToFigma`, and press `Enter`. **The patched panel then auto-joins a channel whose base is
`<figma.fileKey>_<figma.root.name>` — the immutable file key plus the readable file name — no typing
needed** (an unsaved file with no key falls back to the name alone). The key makes the base
collision-free; name the Figma file exactly the repo folder so the readable suffix matches the CLI's
`folderChannel()`. The channel field is only a manual override.

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

The channel is a free-text label the plugin panel joins — by default the **open Figma file's name**
(e.g. `Resonanz_Records_1`), NOT the repo folder. You rarely need to name it: the CLI now
**auto-discovers the live channel from the relay `/status` endpoint**. Channel precedence is
`FIGMA_CHANNEL` env → explicit `--channel` → `/status` discovery → `folderChannel()` (the folder-name
fallback, used only when the relay is unreachable). So a bare `probe` lists every live channel:

```bash
node "${CLAUDE_PROJECT_DIR}/.claude/skills/figma-bridge/scripts/figma/figma.mjs" probe            # auto-discovers live channels from /status (<FIGMA_FILE_KEY>_<folder> only if the relay is down)
node "${CLAUDE_PROJECT_DIR}/.claude/skills/figma-bridge/scripts/figma/figma.mjs" probe --channel=<id> --channel=<other>
```

`CONNECTED` = the plugin is joined there (reports its pages + `fileKey`); `NOT_CONNECTED` = nothing
joined — open Figma, `Command+P`, run ClaudeTalkToFigma, and join that channel.

**Multi-channel panel (one window, N channels).** The patched panel holds **N channels at once** —
default **5 rows** named `<fileName>_1 … _5`, a **"+ Add channel"** button for more, each row an
independent Connect/Disconnect joined to its own channel. So N agents/sessions can drive ONE open
Figma file through ONE plugin window (each on its own `_N` channel) — you no longer need N Figma
windows for N channels on a single file. The sandbox stays channel-agnostic; the panel routes each
reply back to the originating channel by command id and serializes commands into the one shared
document. **CLI note:** these suffixed `_N` channels no longer need to be named by hand — a bare
`probe` / the default channel resolution auto-discovers them from `/status` (expanding the open file's
`<fileKey>_<fileName>_1 … _5` family); pin a specific one with `--channel=<base>_N` or `FIGMA_CHANNEL=<base>_N`.
Logical write conflicts between concurrent writers are still yours to avoid (disjoint `parentId` — see
`figma-ui`); the queue only prevents API-call interleaving, not subtree collisions.

**The patched panel is vendored** at `plugins/claude-template-core/vendor/ctf-plugin/` (see its
`VENDOR.md`). Unlike stock CTF (which joins a *random* channel every connect), it **auto-joins a
fileKey-based channel on run** (base `<figma.fileKey>_<figma.root.name>`, ahead of the random fallback;
the file key makes it collision-free) — so a project whose Figma file is named after its repo folder
joins the right channel with **no typing** (all 5 rows auto-connect on
launch, each auto-reconnecting with capped backoff if it drops, until you Disconnect). The channel field remains a
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
- `probe` — probe channels (auto-discovered from `/status` when none given) → the live channel's pages + fileKey. `--channel=<id>` (repeatable).
- `probe --all [--base=<name>] [--max=N]` — verify the project's conventional channels
  `<base>_1..N` (N default 5) are ALL reachable and on one file. Base is discovered from the
  relay `/status` endpoint (strip `_N`); override with `--base`, or it falls back to the folder
  name. Exit 0 iff every channel is CONNECTED and shares one fileKey; else exit 1 with a reason.
  Note: checks the CONVENTIONAL `_1..N` set — it cannot read the panel's saved row list, so a
  renamed/custom row set needs `--base`/`--max`. CONNECTED means "a plugin is joined," not "the
  lane is free."
- `page` — ensure / rename / set-current a page. `--name=<pageName> [--file-key]`.
- `png` — export a selection → PNG on disk. `[--all --filter=<substr> --scale=N --out=<dir> --channel]`.
- `lanes` — launch N parallel Figma agents (one file/channel/session each); starts its own relay, so it bypasses the normal preflight. `<lane...> [--no-spawn --max=N]` (lane = `channel=fileKey[@cwd]`); also runnable as `bin/figma-lanes`.

**Capture — optional deps (`playwright`/`esbuild`/`dom-to-svg`), lazy-imported:**

- `capture` — live page → sharp vector SVG. `--url=<url> --out=<file.svg> [--selector --strip-images --strip-selectors=<csv> --viewport-width --max-height --min-text=<n> --inline-remote-images]`.
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

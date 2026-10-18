# vendor/ctf-plugin — the ClaudeTalkToFigma Figma plugin (patched)

Last updated: 2026-10-06 22:40

Vendored subset of **arinspunk/claude-talk-to-figma-mcp** v1.0.0
(https://github.com/arinspunk/claude-talk-to-figma-mcp), MIT (see `LICENSE`). Only the **Figma-plugin
panel** is vendored — the part a human imports into Figma Desktop. The WebSocket relay and the MCP
server are NOT vendored: the template drives the relay from npm
(`claude-talk-to-figma-mcp@latest`, hardcoded `:3055`) via the `figma_launch` SessionStart hook, and
that same-lineage relay is protocol-compatible with this panel.

## Vendored files (from upstream `src/claude_mcp_plugin/`)

- `manifest.json` — the Figma plugin manifest (import this in Figma Desktop)
- `code.js` — the plugin sandbox code
- `ui.html` — the plugin panel UI
- `setcharacters.js` — a text helper used by `code.js`
- `LICENSE` — upstream MIT license

Dropped from upstream: `src/socket.ts` (relay), `src/talk_to_figma_mcp/` (MCP), `images/` (1.2M docs),
tests, and all build tooling — none needed on the Figma-panel side.

## ⚠ HAND-PATCHED — a blind re-vendor WILL clobber this

Upstream generates a **random 8-char channel on every connect**, persists only `serverPort`, and the
panel joins **exactly one channel**. We patched the panel in two waves. The local divergence from
upstream v1.0.0:

### Wave 1 — channel typed once & persisted, auto-join the open file's name
- `ui.html` — a channel field; `onopen` joined the typed/persisted channel (random only as an
  empty-field fallback), persisted via `update-settings`; an `init-settings` handler restored it.
- `code.js` — `state.channel`; `updateSettings()` persists `channel` alongside `serverPort`;
  `initializePlugin()` restores it into the `init-settings` message.
- `figma.on("run")` passes `figma.root.name` (file name = repo folder) as `fileChannel` on an
  `auto-connect` message so a new folder auto-joins its own channel with no typing.

### Wave 2 — MULTI-CHANNEL panel (one window, N channels)
The panel now owns **N WebSocket connections at once**, each joined to its own channel. Default = **5
rows** named `<fileName>_1 … _5`; a **"+ Add channel"** button appends `<fileName>_<next>`; each row
has its own Connect/Disconnect toggle, status line, and a **×** remove. The channel list is persisted
and restored. Why this is safe: the Figma sandbox (`code.js`) is **channel-agnostic** — it runs
`execute-command` and replies by `id` only — so the UI can fan out across channels without the sandbox
knowing. Specifics:

- `ui.html` — **full rewrite** of the panel to a `ClaudeMCPPlugin` that holds `connections[]` (one per
  row), a `pending` `Map<commandId → connection>` that routes each sandbox reply back out the
  originating socket, and a **single serialization queue** (`queue` + `inFlight`) that feeds the
  sandbox ONE `execute-command` at a time (N channels share one Figma document — without this,
  concurrent mutations from different channels could interleave). Default-5 / "+"-add / ×-remove,
  per-row status (muted `idle` at rest, green `connected`, red on error), `clientStorage`-backed
  channel list, dark/light toggle, shared progress bar routed by `commandId`, and a content-measured
  `resize` request. Auto-connect fires for the **first row only** (once) — the rest connect on click,
  to avoid N noisy auto-joins per run.
- `code.js` — `state.channels[]`; `updateSettings()` persists the full `channels` list (+ legacy
  single `channel` = first row); `initializePlugin()` restores `channels` into `init-settings`; a new
  `resize` message type calls `figma.ui.resize` (clamped); `showUI` default height raised to fit 5
  rows.

### Wave 3 — auto-reconnect + auto-connect ALL rows on boot
- `ui.html` — a dropped socket (`onclose`/`onerror` with no prior intentional close) now
  **auto-reconnects** with capped exponential backoff (2s→4s→8s→16s→30s cap, indefinite); a user
  Disconnect/Remove sets `conn.userClosed` first so it stays down. Per-connection state
  `userClosed`/`reconnectTimer`/`retryStep`; a successful reconnect resets the backoff. Boot now
  connects **all** rows (`maybeAutoConnectAll`, renamed from `maybeAutoConnectFirst`), not just the
  first — all 5 default channels go live on launch. No `code.js` change.

### Wave 4 — rebase channels to the OPEN file, not a stale persisted list
- `ui.html` — Figma `clientStorage` is per-plugin-global, so a channel list persisted while working on
  one file (e.g. `Resonanz_Records_1..5`) was being restored on every OTHER file, overriding
  `figma.root.name`. Fixed: `init-settings` now **defers** the boot to the existing 300 ms fallback
  (instead of booting the saved list immediately), and `bootRows` compares the saved list's base
  (`channelBase`, strips a trailing `_<n>`) to the open file's name (`this.fileChannel`, set by
  `auto-connect`): a **match** restores the saved list verbatim; a **mismatch** boots
  `<fileName>_1..5` and discards the stale list; **no file name** (auto-connect never fired) preserves
  the saved list. No `code.js` change (it already posts `figma.root.name`). Covered by
  `tests/test_ctf_plugin_vendor.sh` CT-14/15/16 via the `ctf_vm.js` harness.

### Wave 5 — channel base keyed on `figma.fileKey`, not the mutable file name
- `code.js` — `figma.on("run")` now also posts `fileKey: figma.fileKey` (the immutable 22-char URL
  key, readable because the manifest sets `enablePrivatePluginApi`) on the `auto-connect` message.
- `ui.html` — the `auto-connect` handler builds the base as `<fileKey>_<fileName>` (identity from the
  key, readability from the name); an unsaved file with no key falls back to `<fileName>` (Wave-4
  behavior). `channelBase`/`bootRows` are unchanged — the rebase-on-mismatch now fires on the fileKey
  base, so two files can never collide and a rename never shifts the channel. Covered by CT-17/18/19.
- The CLI `folderChannel()` (`channel-resolve.mjs`) and the `figma_launch` hooks mirror this: the
  OFFLINE default is `<FIGMA_FILE_KEY>_<folder>`; the live `/status` discovery path is name-agnostic.

**Channel-naming note (CLI alignment):** the suffixed `<fileKey>_<fileName>_N` channels are
auto-discovered from the relay's `/status` endpoint (name-agnostic); the CLI's offline default is
`<FIGMA_FILE_KEY>_<folder>`, used only when `/status` is unreachable. To pin one of these channels
explicitly from the CLI or an MCP client, pass `FIGMA_CHANNEL=<base>_N` or `--channel <base>_N` (the
resolver already supports both). One file, many channels is the intended use: N agents/sessions each target one `_N` channel and
all drive the SAME open file through this one plugin window. Logical write conflicts are still the
caller's responsibility (disjoint `parentId` per writer — see the `figma-ui` skill); the serialization
queue only prevents API-call interleaving, not subtree collisions.

**Re-vendor checklist (no upstream auto-sync):** re-copy the 5 files from upstream, then RE-APPLY both
waves above — Wave 1 (channel persistence + `figma.root.name` auto-connect), Wave 2 (the
multi-channel `ui.html` rewrite + the `code.js` `channels`/`resize` plumbing), Wave 3
(auto-reconnect + connect-all-on-boot in `ui.html`), Wave 4 (defer-boot + rebase channels to
the open file in `ui.html`) **and** Wave 5 (`code.js` posts `figma.fileKey`; `ui.html` builds the
`<fileKey>_<fileName>` base). Verify, with a relay on
`:3055`: (a) 5 default rows render named `<file>_1..5` and **all auto-connect** on launch; (b) two
rows connect to distinct channels simultaneously; (c) a command sent on one channel returns on THAT
channel only (no cross-talk); (d) killing the relay drops the rows to "Reconnecting in Ns…" and they
**auto-recover** when it returns; (e) a manual Disconnect stays down (no auto-revive); (f) "+ Add
channel" / × work. Then bump the core plugin version. Do NOT overwrite without re-applying the patches.

## Install into Figma (once per machine)

The `figma_launch` hook mirrors this dir to a **stable** path (`~/.local/share/claude-template/
ctf-plugin/`) and echoes it at startup. In Figma Desktop: **Plugins → Development → Import plugin from
manifest…** → pick that stable `manifest.json`. Then run the plugin (`Command+P` → ClaudeTalkToFigma);
the channel is auto-discovered from the relay, so you only type a name if the relay is unavailable — it
persists across sessions.

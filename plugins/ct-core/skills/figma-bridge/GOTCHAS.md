# figma-bridge — GOTCHAS

Last updated: 2026-10-07 04:14

Hard-won bridge behaviours that cost real time. Read before driving a non-trivial Figma session over
the ClaudeTalkToFigma relay (`:3055`).

> **CANONICAL COPY.** This is the upstream `claude_template` copy of the skill — the one
> `propagate.sh --apply` / `chore(vendor)` re-vendors INTO every consumer repo. A consumer's
> `.claude/skills/figma-bridge/` is a vendored mirror and is overwritten on the next re-vendor, so
> any fix made downstream must be upstreamed HERE or it regresses.

## Which file is live? The plugin mirrors ONE window.

- All channels on `:3055` reflect the Figma **file where the plugin is running / which window is
  focused** — the channel NAME does **not** pin a file. Open two files (e.g. a storefront file and a
  component kit) and the channels flip to whichever one the plugin last ran in.
- A re-launch (`⌘P → ClaudeTalkToFigma`) binds to the **window you run it in**, and the patched panel
  joins channels named after that file (`<file>_1..5`). Run it in the wrong window → wrong file.
- **Always verify by resolving a KNOWN node, not by listing pages.** `probe` lists pages; it can't
  tell you a target node is reachable. Do a `get_node_info` on a frame you intend to touch (e.g. a
  specific screen) — if it times out / "Node not found", you're on the wrong file or wrong page.

## Reads can WEDGE the plugin (dead until re-launch)

- **Batched / looped `get_reactions`, and `scan_text_nodes` on a big frame, WEDGE the plugin.** After
  it severs, EVERY call times out (reads and writes) — ~90s+ with no recovery. Only a plugin
  re-launch revives it.
- Mitigations: prefer **write-only** (the `reactions` subcommand is write-only by default). If you
  must read, do **single, spaced** `get_node_info depth:0` calls — never a loop of `get_reactions`,
  never `scan_text_nodes` on a large subtree. Map node ids once, then write.

## Pages & nodes

- **Reaction WRITES need the target's PAGE to be the ACTIVE page.** `get_node_info`/`scan` resolve
  **cross-page** (async load), but `set_reactions` uses sync `getNodeById` → "Node not found" unless
  that node's page is the open/active one. `set_current_page` is **blocked by the relay**, so you
  cannot switch pages yourself — the human must open the right page (keep everything you wire on ONE
  page where possible).
- **`clone_node` is unusable** over the bridge — it times out even on a single text node. Build pages
  from scratch (`create_frame` + `create_text` + `create_rectangle` work fine and fast), don't clone.
- **`get_node_info` on a page returns only SHALLOW children** (`id/name/type`) — safe, doesn't sever.
  Use it to enumerate/find-by-name (and delete-by-name); never request a deep tree.

## Prototype reactions (the `reactions` subcommand)

- Schema the plugin accepts (reverse-engineered, confirmed): `set_reactions` with
  `{ nodeId, reactions:[{ trigger:{type:"ON_CLICK"}, actions:[ACTION] }] }` — note **`actions`
  (array)**, not `action`; `{action:…}` is rejected ("Please provide actions for the Reaction").
  - NAVIGATE: `{type:"NODE", destinationId, navigation:"NAVIGATE", transition:{type:"SMART_ANIMATE",
    easing:{type:"EASE_IN_AND_OUT"}, duration:0.3}, preserveScrollPosition:false}`
  - OPEN URL: `{type:"URL", url:"https://…"}`
- **Figma rejects self-nav** — a NAVIGATE whose destination is the SAME top-level frame as the source
  errors ("destinations must be a different top-level frame"). Skip a logo→its-own-screen, an
  "Archive" link on the Archive screen, etc.
- **Reactions live on the clickable WRAPPER, not the text node.** When re-pointing by label, resolve
  the parent clickable node (walk up one level), or you leave a duplicate reaction on the wrapper.

## Scroll overflow — not supported

- `set_node_properties {overflowDirection:"VERTICAL"}` (and `VERTICAL_SCROLLING` / `scrollBehavior`)
  return OK but **do not apply / are not echoed** by `get_node_info`. The bridge can't set prototype
  scroll overflow — set it by hand in Figma (Prototype → Scroll behavior).

## See also
`scripts/figma/README.md` · `scripts/figma/lib/reactions.mjs` (the prototype-wiring subcommand) ·
`figma-ui` · `docs/workflow/FIGMA-UI.md`.

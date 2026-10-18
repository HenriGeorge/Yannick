# site-to-figma — runbook

Last updated: 2026-10-13 22:26

Pull any website (gated or public) into Figma over the quota-free ClaudeTalkToFigma `:3055` bridge —
as a flat **snapshot** or a component **rebuild** from a design system. The pipeline is the `site-*`
subcommands of `figma-bridge`'s `figma.mjs`; the per-change checklist is the `site-to-figma` skill.
This runbook is the end-to-end operator guide.

## Config

Copy `plugins/claude-template-core/skills/figma-bridge/scripts/figma/site-to-figma.config.example.json`
to your project root as `site-to-figma.config.json`:

| Field | Meaning |
|---|---|
| `origin` | the site's origin (required, http(s)) |
| `authDomain` | cookie/localStorage domain for the authed check (defaults to the origin host) |
| `channel` | the Figma channel the target file is joined on (or set `FIGMA_CHANNEL`) |
| `canvasPage` | a real Figma page id to build on (NOT a PageDivider) — required for palette/build |
| `pageNamePrefix` | optional prefix for built page names (e.g. `Admin` → `Admin · orders`) |
| `theme` | `light` \| `dark` \| `auto` (default `auto`) |
| `uiDir` | the repo dir holding `*.figma.tsx` Code Connect files (default `components/ui`) |
| `routesFile` | path to a `routes.txt` (one path per line, `#` comments) |
| `screensSpec` | path to the per-project screens JSON (rebuild) |

Everything the run produces lives under the project's gitignored `.work/`.

## Two auth paths

- **Headed login (robust — captures httpOnly cookies):** `node figma.mjs site-capture --login`. A
  Chromium window opens; you log in (Claude never sees the password); Playwright saves the full
  `storageState` to `.work/auth.json` and auto-detects completion.
- **Console export (headless/remote fallback):** in a logged-in tab's DevTools console run
  `copy(JSON.stringify({ origin: location.origin, cookie: document.cookie, localStorage: Object.fromEntries(Object.entries(localStorage)) }))`,
  paste into `.work/site-session.json`, then `node figma.mjs site-capture --from-session` (reuses the
  figma-bridge `auth` transform). Note: httpOnly cookies never appear in `document.cookie` — if the
  site keeps its session in one, use the headed path.

## Pipeline

1. **Capture:** `site-capture [--routes=<f>] [--max=N] [--route=/x]` → full-page PNGs in
   `.work/captures/` + rows in `.work/site-manifest.json`. Records the body background as
   `meta.sampleBg` for `--theme=auto`. Routes come primarily from `routes.txt` (a React SPA may expose
   few `<a>` anchors); anchor scraping only augments it.
2. **Snapshot mode (universal):** export a capture as SVG/PNG and `place` it into the Figma file via
   `figma-bridge`. No DS needed.
3. **Palette (rebuild):** `site-palette <Component...>` → resolves each component via the project's
   Code Connect index (`uiDir/*.figma.tsx`) and clones a real instance into a hidden `__SITE_PALETTE__`
   frame, caching `name → {nodeId, instanceNodeId}` in `.work/palette-cache.json`. No index → fails
   loud (use snapshot, or add Code Connect). Never `get_local_components`.
4. **Build (rebuild):** `site-build <screenId|all> [--theme=light|dark|auto]` → assembles each screen
   from `.work/screens-spec.json` (nested auto-layout + cloned instances + styled/themed frames +
   rect placeholders). Idempotent per screen. `--theme` overrides the config; `auto` uses `meta.sampleBg`.
5. **Verify:** `site-verify <screenId> [--png]` → reads the built frame's placed instances, runs the
   structural checklist, advances the manifest to `verified`, and (with `--png`) exports the frame.

## Screens spec + the nav-item recipe

`.work/screens-spec.json` is `screenId → { route, name, tree }`; the tree is nested
`col`/`row`/`rect`/`text`/`component` nodes. Build a sidebar with the **nav-item recipe** — each item a
`row` of a small `rect` (icon placeholder) + a `text` label — not a bare text node, so the nav shows
the real two-column look. The bridge can't place real icon vectors; exact glyphs would need per-icon DS
components with node-ids (not in the Code Connect index).

## REQUIRED plugin patch

The palette/build path needs three additive patches to the ClaudeTalkToFigma plugin's `code.js`
(re-import the plugin after editing; a restart is required to reload `code.js`):

1. `getNodeInfo` exposes the COMPONENT/COMPONENT_SET `key`.
2. `createComponentInstance` accepts a `componentId` (node-id) and resolves it via `getNodeByIdSafe`
   (O(1)) — bypasses the whole-document scan that hangs on large files.
3. `setAutoLayout` defaults sizing modes to `AUTO` (hug), so fixed-size frames don't clip nested content.

## Operating constraints

- **Figma foregrounded for any write** (palette/build/export). Reads work in the background.
- **One writer per channel** — the relay is a single serialized queue.
- **Never whole-document / whole-page reads** — they block the plugin and drop the channel.
- Rebuilding from a Figma **community** file is impossible (`fileKey:null`, no clonable components):
  duplicate it into your account first, or snapshot.

## Cloud

site-to-figma is **local-only** — it needs a local Figma desktop + the `:3055` bridge, so it is
excluded from the cloud bundle (like `figma-bridge`). The companion shadcn registry mirror and
cheat-sheet skill (F2a/F3) are cloud-safe; this pipeline is not.

## Troubleshooting

- *palette "not in Code Connect index"* → the component has no `*.figma.tsx`; add one (official
  `@figma/code-connect`) or drop it from the screen.
- *writes hang* → Figma isn't foregrounded, or another agent holds the channel.
- *channel wrong/severed* → re-`probe` (`figma.mjs probe --all`); the patched plugin auto-rejoins.
- *`--theme=auto` always light* → capture didn't record `meta.sampleBg` (transparent body bg); pass
  `--theme=dark` explicitly.

## See also

the `site-to-figma` skill (the per-change checklist + the `## Interview`) · the `figma-bridge` skill
(the relay launch ritual, read-sever gotchas, the zero-dep core subcommands) · the `figma-ui` skill +
`FIGMA-UI.md` (official metered MCP vs. this free bridge, Code Connect, token sync).

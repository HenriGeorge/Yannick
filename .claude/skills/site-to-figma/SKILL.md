---
name: site-to-figma
description: Use when pulling a live website (including a login-gated SaaS admin) into Figma — "rebuild <site> in Figma", "capture <url> into Figma", "mirror an admin panel", recreating app screens as Figma frames from a design system, or snapshotting a gated site as reference. Runs over the quota-free ClaudeTalkToFigma :3055 bridge. NOT for reading a Figma design into code (that's figma-ui), lifting a site into the repo's token system (that's design-import), or the low-level bridge primitives (that's figma-bridge).
---

# site-to-figma — pull any website into Figma

Capture a site (gated or public) and either drop it into Figma as a flat **snapshot** (universal,
no design system needed) or **rebuild** its screens from a design system's real component
instances. Config-driven; runs on the `figma-bridge` `:3055` relay. The scripts are `site-*`
subcommands of `figma.mjs` (see figma-bridge).

## When to use

- "rebuild the admin in Figma", "capture this URL into Figma", "mirror this dashboard".
- You have a gated site and want its screens as Figma frames.
- **snapshot** when you only need reference pixels (no DS, any site).
- **rebuild** only when the **target Figma file already holds the DS** AND the project has a Code
  Connect index (`*.figma.tsx`). No index → `site-palette` fails loud; use snapshot instead.
- NOT for cross-file component copying — the bridge cannot clone instances between two Figma files.

## Prerequisites (hard constraints)

- The ClaudeTalkToFigma relay is live and the target file is joined on a channel (see figma-bridge).
- **Figma must be FOREGROUNDED for any bridge write** (palette/build) — reads can run in the
  background, writes hang otherwise. Run a build as one batched foreground session.
- The ClaudeTalkToFigma plugin must be **patched**: `createComponentInstance` accepts a
  `componentId`, `getNodeInfo` exposes the component key, `setAutoLayout` defaults sizing to `AUTO`.
- **Never** `get_local_components` / whole-page reads — they hang and drop the channel on large files.
- **One writer per channel.** Capture auth/output live under the project's gitignored `.work/`.

## Interview (run first, one question at a time — ≥4 AskUserQuestion)

1. **Target + auth** — what URL, and how do you log in (headed browser login, or a console-export
   session)?
2. **Mode** — snapshot (reference pixels) or rebuild (from the DS in the target file)?
3. **Routes source** — a hand-kept `routes.txt`, anchor-scrape, or a single `--route`?
4. **Theme** — `light`, `dark`, or `auto` (derive from the captured background)?
   (If rebuild:) **DS source** — confirm the target file holds the DS and the repo has `*.figma.tsx`.

## Pipeline

Config: a per-project `site-to-figma.config.json` (see `figma-bridge/scripts/figma/site-to-figma.config.example.json`).

| Step | Command | Notes |
|---|---|---|
| Auth | `figma.mjs site-capture --login` (headed) or `--from-session` (console export) | headed captures httpOnly cookies; console export reuses figma-bridge `auth` |
| Capture | `figma.mjs site-capture [--routes=<f>] [--max=N] [--route=/x]` | → `.work/captures/*.png` + `.work/site-manifest.json` (+ `meta.sampleBg` for `--theme=auto`) |
| Palette *(rebuild)* | `figma.mjs site-palette <Component...>` | resolves the project's Code Connect index → `.work/palette-cache.json`; fails loud with no index |
| Build *(rebuild)* | `figma.mjs site-build <screenId\|all> [--theme=light\|dark\|auto]` | assembles screens from `.work/screens-spec.json`; idempotent per screen |
| Verify *(rebuild)* | `figma.mjs site-verify <screenId> [--png]` | reads back instances → structural checklist → status `verified` |
| Snapshot | `figma-bridge` `capture` + `place` | export the captured page as SVG/PNG → `place` into the Figma file |

## Screens spec (rebuild)

`.work/screens-spec.json` maps `screenId → { route, name, tree }`. The tree is nested
`col`/`row`/`rect`/`text`/`component` nodes. For a sidebar, use the **nav-item recipe** — each item is
a `row` of a small `rect` (icon placeholder) + a `text` label — not a bare text node, so the nav gets
the real two-column look (the bridge can't place real icon glyphs; exact icons would need per-icon DS
components with node-ids).

## Cloud

**Local-only.** site-to-figma needs a local Figma desktop + the `:3055` bridge, so it does not run in
a cloud Claude Code session (excluded from the cloud bundle, like figma-bridge).

## Common mistakes

- Rebuilding from a Figma **community** file (`fileKey:null`) — you can't clone its components; duplicate
  it into your account (real fileKey) first, or snapshot instead.
- Running a build with Figma in the background — writes hang. Foreground it.
- Expecting a generic DS fallback — there is none; rebuild needs the DS in the target file.

# site-to-figma runbook

Last updated: 2026-10-19 02:50

## Config

Copy `plugins/ct-core/skills/figma-bridge/scripts/figma/site-to-figma.config.example.json`
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

Everything the run produces lives under the project's gitignored `.work/`. Two auth paths: a
headed login (`site-capture --login`, captures httpOnly cookies) or a console export (below) for
headless/remote.

## Export from the live page

httpOnly cookies never appear in `document.cookie` — if the site keeps its session in one, use
the headed login path instead. Otherwise, in a logged-in tab's DevTools console run:

```js
copy(JSON.stringify({ origin: location.origin, cookie: document.cookie, localStorage: Object.fromEntries(Object.entries(localStorage)) }))
```

Paste the result into `.work/site-session.json`, then run `node figma.mjs site-capture --from-session`.

## Required plugin patch

The palette/build path needs three additive patches to the ClaudeTalkToFigma plugin's `code.js`
(re-import the plugin after editing; a restart is required to reload `code.js`):

1. `getNodeInfo` exposes the COMPONENT/COMPONENT_SET `key`.
2. `createComponentInstance` accepts a `componentId` (node-id) and resolves it via `getNodeByIdSafe`
   (O(1)) — bypasses the whole-document scan that hangs on large files.
3. `setAutoLayout` defaults sizing modes to `AUTO` (hug), so fixed-size frames don't clip nested content.

## Troubleshooting

- *palette "not in Code Connect index"* → the component has no `*.figma.tsx`; add one (official
  `@figma/code-connect`) or drop it from the screen.
- *writes hang* → Figma isn't foregrounded, or another agent holds the channel.
- *channel wrong/severed* → re-`probe` (`figma.mjs probe --all`); the patched plugin auto-rejoins.
- *`--theme=auto` always light* → capture didn't record `meta.sampleBg` (transparent body bg); pass
  `--theme=dark` explicitly.

## See also

the `site-to-figma` skill (../../skills/site-to-figma/SKILL.md) — pipeline, screens-spec/nav-item
recipe, operating constraints, cloud status · `FIGMA-UI.md` (official metered MCP vs. this free
bridge, Code Connect, token sync).

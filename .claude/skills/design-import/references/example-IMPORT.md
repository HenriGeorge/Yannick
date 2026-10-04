# IMPORT.md — AutoCue Workbench → repo design system

**Source:** `AutoCue_Workbench.html` (local file, bundled-export format)
**Run:** `capture.mjs` (file:// branch) → `detect` → `extract-tokens` → component gen
**Date:** logic-trace run (Claude Code-equivalent), not yet run inside the live skill.

## Capture
- Input classified as **file** (local path / `file://`).
- File was a **bundled export**: a thumbnail shell + gzipped JS bundle, with the
  fully-rendered HTML stored verbatim (JSON-encoded) inside
  `<script type="__bundler/template">`.
- **Playwright was NOT needed** — the rendered DOM is already embedded. The capture
  step decodes the template directly. (This is a new third branch beyond
  static-fetch and Playwright; it also closes gap 1, the `file://` failure.)
- Captured: **149,109 chars**, 13 non-data asset refs (Inter + JetBrains Mono woff2,
  referenced by opaque bundler IDs — see *Assets* below).

## Design-system detection
| Signal | Present |
|---|---|
| shadcn triad (`--background/--foreground/--primary`) | no |
| Tailwind utility classes | no |
| component-lib (MUI/Chakra/Ant) | no |
| **bespoke custom-property system** (`--green`, `--surface`, …, inline styles) | **yes** |

**Detected: bespoke.** But the favourable subcase — the source *declares all 33 of its
variables explicitly* in `:root`. Extraction reads real declared values, so this is
**high fidelity**, NOT the `<0.5` "most-frequent-colour-is-primary" guess path the
handoff warns about. Only the cross-system *name* mappings carry uncertainty, not the
*values*.

## Token mapping (source → shadcn)
Values are the source's real hex/rgba. `tokens.css` step 0 should convert these to the
repo's `oklch()` format to match `default_shadcn_theme.css`.

| shadcn token | source var | value | confidence |
|---|---|---|---|
| background | `--bg` | `#fafafa` | 1.0 |
| foreground | `--text` | `#1a1a1a` | 1.0 |
| card | `--surface` | `#ffffff` | 1.0 |
| card-foreground | `--text` | `#1a1a1a` | 0.9 |
| popover | `--glass-bg` | `rgba(255,255,255,.86)` | 0.8 — has alpha, verify |
| primary | `--green` | `#159a05` | 1.0 — default of `accentColor` enum |
| primary-foreground | `--on-ink` | `#fafafa` | 0.9 |
| secondary | `--surface-2` | `#f2f2f2` | 0.9 |
| secondary-foreground | `--ink` | `#0a0a0a` | 0.8 — verify |
| muted | `--surface-2` | `#f2f2f2` | 0.85 |
| muted-foreground | `--muted` | `#737373` | 1.0 |
| accent | `--green-wash` | `rgba(21,154,5,.08)` | 0.8 — verify |
| accent-foreground | `--green-dim` | `#0f6e03` | 0.8 — verify |
| destructive | `--danger` | `#e74c3c` | 1.0 |
| border | `--border` | `#e8e8e8` | 1.0 |
| input | `--border` | `#e8e8e8` | 0.9 |
| ring | `--green-ring` | `rgba(21,154,5,.14)` | 1.0 |
| chart-1..5 | `--cue-a..e` | green/blue/cyan/amber/orange | 0.9 |

**Unmapped (no shadcn slot, kept verbatim):** `--cue-f/g/h` (red/magenta/purple — the
hot-cue palette has 8 colours, shadcn charts only 5), `--warn`, `--warn-amber`,
`--rating`, `--border-hover`, `--muted-soft`, `--ink-hover`. These are carried into
`tokens.css` under their original names.

**Radius:** source has no single radius token — it uses `8px` (buttons/cards) and
`999px` (pills) ad hoc. `--radius: 0.5rem` emitted with `/* verify */`.

**Fonts:** Inter (sans) + JetBrains Mono (mono), preserved as `--font-sans` / `--font-mono`.

## Structure extracted
- **~270 template bindings** (`{{ ... }}`) across 7 views: console, discover, enrich,
  health, nightboard, setbuilder, inspector. These become component props / mapped state.
- **44 `style-hover` rules** → reproduced as framer-motion `whileHover` (motion preserved,
  none invented).
- **4 configurable props** declared with `tsType` in `data-props`:
  `inspectorSide` (`'right'|'left'`), `accentColor` (string, 4 options),
  `rowDensity` (`'comfortable'|'compact'`), `dismissOnOutside` (boolean).
  These map cleanly to a typed component prop interface.

## Components generated
- `WorkbenchHeader.tsx` — sample, the self-contained header bar. Full generation of all
  7 views is runtime judgement work (handoff gap 2) and not attempted in this trace.

## Assets — follow-up needed
The 13 font URLs are **opaque bundler IDs** (e.g. `eae22c41-…`), not real paths. They
resolve only inside the bundle's runtime. For the repo, drop these and load Inter +
JetBrains Mono from the normal source (Google Fonts / `next/font`) — the `@font-face`
`unicode-range` blocks in the capture confirm exactly those two families.

## Honest accuracy notes
- Token **values** are exact (declared vars) → high fidelity.
- Token **name** mappings to shadcn carry the confidences above; everything `<0.85`
  is tagged `/* verify */` in `tokens.css`.
- shadcn has fewer slots than the source has roles (8 cue colours, multiple warn/border
  variants) → some source tokens have no canonical home and are kept as-is.
- Hex→oklch conversion deferred to `tokens.css` step 0 (needs the repo theme + a colour
  lib; not done in this trace to avoid an unverified manual conversion).

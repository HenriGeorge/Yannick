---
name: design-import
description: Import an existing website by URL or local file into the repo's design system. Captures the page (static fetch, Playwright for JS-heavy sites, or inlined bundled-export template), detects its design system (shadcn / tailwind / bespoke), extracts real token values mapped onto the repo's shadcn token names, and emits canonical HTML + React .tsx components (framer-motion) plus an IMPORT.md report. Use when the user wants to lift a website's look into this codebase, or says "import a site/URL".
---

# design-import

Lift an existing site's design into this repo's shadcn-based system, editable in
both Figma (via the html.to.design plugin) and code.

## Inputs
```
/design-import <url|path> [--render=static|playwright|auto] [--name NAME] [--components-only] [--format=oklch|hex]
```
- `<url|path>` — an `http(s)` URL, a `file://` URL, or a local file path.
- `--render` — capture mode for URLs (default `static`). `playwright`/`auto` for
  JS-rendered sites. Ignored for local files (see Capture below).
- `--format` — token value format target (default `oklch`, to match the repo theme).

## Pipeline

### Step 0 — read the repo theme
Read the repo's `default_shadcn_theme.css` (or `globals.css`) so token names and the
value format (`oklch()`) are known. Tokens emitted in later steps conform to it.

### Step 1 — capture  → `captured.html` + `assets.json`
`scripts/capture.mjs <input> --out=<dir>` resolves the input into one fully-rendered
HTML file. Three input classes:
1. **http(s) URL** — `fetch()` (static) or Playwright (`--render=playwright|auto`).
2. **file:// or local path** — read from disk.
3. **bundled export** — a wrapper file (thumbnail shell + gzipped JS bundle) whose
   *rendered* DOM is stored JSON-encoded inside `<script type="__bundler/template">`.
   capture.mjs decodes that template directly. **Playwright is NOT used** here — the
   rendered HTML is already inlined; re-rendering would just re-run the bundle.
   Detected automatically for both local files and fetched pages.

### Step 2 — detect  → `_detect.json`
`scripts/detect.mjs <dir>` classifies the design system and picks a strategy:
- **shadcn** — declares the shadcn token triad as CSS vars → direct var transfer.
- **tailwind-map** — Tailwind utility classes → resolve to palette values via
  `scripts/tw-palette.mjs`, map onto shadcn names.
- **bespoke** — own custom-property system (declared vars → high fidelity) OR ad-hoc
  inline styles (value clustering → low confidence).
- component-lib markup (MUI/Chakra/Ant) is flagged as an **approximate reskin**.

### Step 3 — extract tokens  → `tokens.css` + `_tokens.json`
`scripts/extract-tokens.mjs <dir> --format=oklch` extracts the source's real values
and maps them onto shadcn names. Values below 0.5 confidence are tagged
`/* low confidence — verify */`. If `tailwind-map` resolves zero classes it emits a
loud warning instead of an empty success (no silent failures).

### Step 4 — canonical HTML  *(runtime judgement — no script)*
From `captured.html`, produce `canonical.html`: token-referencing CSS, `data-component`
boundaries, and slot/repeat/action annotations. This is DOM→component judgement work
done by Claude Code at run time, directed by this procedure.

### Step 5 — React components  *(runtime judgement — no script)*
Emit `.tsx` components using the tokens and `framer-motion`. Preserve motion found in
the source (`style-hover` → `whileHover`, keyframe animations → `animate`/`transition`).
**Do not invent motion** where none was detected; flag lossy guesses.

### Step 5.5 — motion + DTCG capture  → `tokens.json` + `motion.json`  *(URL imports; project-gated)*
`getAnimations()` only sees the CSS/WAAPI subset — GSAP tweens, Lenis, and scroll motion are
invisible to a static/CSS scrape, so this step captures them from the **live runtime** as portable
data an import agent can reuse to reconstruct / re-skin / swap the design.

**Only when the project provides a `capture-design` script** (check `package.json` for it — e.g.
design-gallery's `npm run capture-design`; skip this step where it's absent). After the screenshots,
run it against the same URL:

```bash
npm run capture-design -- --url <URL> --slug <slug>
```

It writes into `src/designs/<slug>/`:
- `tokens.json` — DTCG tokens (color/type/spacing/radius/shadow/duration/easing).
- `motion.json` — exact CSS/WAAPI animations (snapshotted at `load` + `networkidle`) + best-effort
  `window.gsap.globalTimeline` / `ScrollTrigger.getAll()` when GSAP is on `window` + an honest
  `uncaptured[]` (canvas/WebGL, tree-shaken GSAP, Lenis). No OSS tool derives motion specs from
  pixels, so `uncaptured[]` is the documented ceiling — never a silent gap.

Use `motion.json` to inform the Step-5 `framer-motion` reconstruction (real durations/easings),
and note in `IMPORT.md` what landed in `uncaptured[]`.

### Step 6 — report  → `IMPORT.md`
Mapping table (shadcn ← source, value, confidence), capture mode used, unmapped source
tokens, asset follow-ups, and honest accuracy notes. See
`references/example-IMPORT.md` for a worked example (the AutoCue Workbench import).

## Honest accuracy notes (carry into IMPORT.md)
- shadcn source = high fidelity (declared vars). Bespoke with declared vars = also high
  fidelity for *values*; only cross-system *names* are uncertain.
- Bespoke with only inline styles = heuristic ("most frequent non-bg/fg = primary") →
  <0.5 confidence, `/* verify */`.
- Tailwind = good (class intent), bounded by `tw-palette.mjs` coverage (common steps
  only; uncommon names like `fuchsia-300` miss and warn).
- component-lib → shadcn is an approximate reskin, not a translation.
- Static fetch misses JS-rendered content → `--render=playwright|auto` for live SPAs.
  (Bundled exports are the exception: rendered DOM is inlined, no render needed.)

## Boundaries
- Artifacts can't import a URL (sandboxed, no cross-origin fetch / no FS). This skill is
  the importer; any prototype artifacts are reference only.
- Figma: inbound URL→Figma is the html.to.design plugin (fed `captured.html`); outbound
  Figma→code is the Figma MCP connector. This skill does neither.
- ElevenLabs UI is a shadcn registry, not scraped: `npx shadcn@latest add https://ui.elevenlabs.io/r/all.json`.

## Layout
```
.claude/skills/design-import/
├── SKILL.md
├── references/
│   └── example-IMPORT.md # worked Step 6 report (AutoCue Workbench import)
└── scripts/
    ├── capture.mjs        # 3 input classes incl. bundled-export
    ├── detect.mjs         # → _detect.json
    ├── extract-tokens.mjs # → tokens.css + _tokens.json
    └── tw-palette.mjs     # Tailwind default palette (oklch)
```
Playwright (only for JS-heavy live sites): `npm i -D playwright && npx playwright install chromium`

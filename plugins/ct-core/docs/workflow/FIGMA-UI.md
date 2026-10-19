# Figma → UI: the how

Last updated: 2026-10-19 02:50

Single home for Figma mechanics inside `rules/design-workflow.md`'s VISUAL/TOKENS → BUILD legs.
`CLAUDE.md` wins; GATE 1 (approved design) and GATE 2 (fresh evidence) are never skipped. Primary
direction is **Figma → code**; the reverse leg (code → Figma mirror) is its own section below.

Three surfaces, by capability, never by preference:

- **arinspunk bridge** (`ClaudeTalkToFigma`, ws `:3055`) — free, unlimited. Write/assemble/read
  structure, literal Variables only (no aliases/modes). Driven by the `figma-bridge` skill.
- **native `figma.variables` plugin** (imported dev plugin, run in-file) — the only verified path
  to full-fidelity Variables (aliases + light/dark modes).
- **official Figma MCP** (`claude_ai_Figma`) — metered. Semantic codegen, token defs, Code Connect.

## Quota-free first

The official MCP's reads are metered (**~6/month on Starter** — verify current metering, it
changes). Spend that quota only on the FINAL, locked design; everything iterative stays free. Policy
sentence: `rules/design-workflow.md`.

| Need | Path | Cost |
| --- | --- | --- |
| Iterate on a design IN Figma (frames/layout/text) | **claude-in-chrome** `window.figma` (logged-in tab) | 0 |
| Screenshot the live app | **Chrome DevTools MCP** @ `127.0.0.1:PORT` | 0 |
| Port a design that already exists as code | serve + render the export | 0 |
| Bootstrap a running site → editable layers | `html.to.design` plugin | 0 |
| Semantic codegen from the FINAL design | official MCP `get_design_context` | metered |
| Token definitions from the FINAL design | official MCP `get_variable_defs` | metered |
| Component ↔ code mapping | official MCP Code Connect suite | metered |
| Push code/designs INTO Figma | official MCP `use_figma` / generate-design | seat-dependent |

## Pipeline

| Stage | Design-workflow leg | Skill / agent |
| --- | --- | --- |
| EXPLORE | pre-SHAPE ideation | Figma Make (manual) — ideation, not codegen |
| SHAPE + CRITIQUE | SHAPE + PRESSURE-TEST | `design-an-interface` (Design-It-Twice) → `grilling` / `grill-me-socratic` as the critic |
| ASSEMBLE | VISUAL/TOKENS | claude-in-chrome `window.figma` (quota-free): frames, auto-layout, instances, type |
| LOCK | GATE 1 approval | shape + tokens + key states concrete enough to build without guessing |
| TOKENS+CODEGEN | VISUAL/TOKENS → BUILD | official MCP metered reads: `get_variable_defs`, `get_design_context`, Code Connect |
| COVER | COVER (test-first) | `test-designer` → coverage, then `playwright-tester` writes a failing `e2e/*.spec.ts` → run alone → RED |
| PORT → BUILD | BUILD | implementer teammate turns the COVER red spec green; swap raw Tailwind for design-system tokens |
| POLISH+VERIFY | POLISH + REVIEW | `ui-aliveness-audit` (reduced-motion-gated) → GATE 2: drive the live site, screenshot as evidence |

The design → preview → sign-off validation loop (dev-only `/preview` route, probe Figma bounds
before placing a capture, re-verify no overlap) is the `figma-ui` skill's per-change checklist —
follow it there, not duplicated here.

## Variables and tokens

`window.figma` from a logged-in **page tab** is free and reliable for frames, layout, auto-layout
and text — but **not** for Variables: `figma.variables` needs the plugin sandbox, which a page tab
does not have. Treat any page-tab Variables read as unverified.

Full-fidelity Variables (aliases + light/dark modes) come only from a **native `figma.variables`
plugin run in-file** (import the plugin once, run it). It creates OKLCH→sRGB primitives plus
aliased semantics (`semantic/primary` as a real `VARIABLE_ALIAS` → its primitive), not flat colors.
Gotchas:

- `documentAccess: dynamic-page` → the sync `getLocalVariableCollections()` / `getLocalVariables()`
  **throw**; use the async variants and `await` them.
- Run in a **fresh draft** — re-running into a file with a same-named collection merges into it.
- Verify by spot-checking an anchor value from inside the file (plugin or `window.figma`), not via
  the official MCP's `get_node_info`, which can strip `boundVariables`.

**Code → Figma token bridge** (`web-scaffold/` projects): `scripts/build-tokens.ts` turns
`theme.css`/`globals.css` into `tokens.json` (OKLCH→sRGB + aliased light/dark semantics), consumed
by the native plugin above. A `tokens:verify` step diffs live Figma Variables against `tokens.json`
and fails loud on drift. On Starter, Figma holds light mode only — dark stays in `tokens.json` until
`FIGMA_INCLUDE_DARK=1` on a paid plan.

## Code Connect

One-time setup; after it, `get_design_context` emits your actual components instead of guessing —
try this before any design-brief tuning. Full runbook: `CODE-CONNECT.md` (this dir). Publish/view/
MCP-read are paid (Figma Org/Enterprise + Dev seat); `parse`/`dry-run` are free.

## Reverse leg — code → Figma

When code is canonical and Figma should mirror it: tokens are free and automatable (the bridge
above); a component **library** is not — no tool turns a code library into a maintainable,
variant-structured Figma library automatically. Author it once by hand, keep it 1:1 via Code
Connect, never wholesale-regenerate per push. Pushing a rendered page/component into Figma (official
MCP `use_figma` / generate-design) produces a flat snapshot with no library link — a mockup, not a
system. Writing a shared component library also needs a Figma Full seat (write outside drafts).
Full mechanics: `SITE-TO-FIGMA.md` and the `site-to-figma` skill.

## Project wiring

One project = one Figma file (named after the repo folder; key in `FIGMA_FILE_KEY` in
`.claude/worktrees.conf`) = one default talk-to-figma channel. `FIGMA_LAUNCH=1` lets the
`figma_launch` SessionStart hook open Figma and bring the bridge up; `FIGMA_AUTOLAUNCH_PLUGIN`
(default on) also auto-runs the plugin on macOS once imported. `FIGMA_FILE_FINGERPRINT` pins the
expected file's key so a wrong-file load at launch WARNs instead of silently screenshotting the
wrong design. Channel mechanics, reconnection, multi-channel rows, and the fingerprint-probe command
all live in the `figma-bridge` skill — not duplicated here.

## See also

`rules/design-workflow.md` (parent pipeline + quota policy) · `verify-workflow.md` (GATE 2) ·
`agent-delegation.md` · the `local-browser-testing` plugin skill · the `figma-ui` skill (per-change
checklist, the validation loop) · the `figma-bridge` skill (relay launch + channel mechanics) ·
`CODE-CONNECT.md` · the `site-to-figma` skill + `SITE-TO-FIGMA.md`.

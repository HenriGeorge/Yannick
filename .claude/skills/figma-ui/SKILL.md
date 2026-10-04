---
name: figma-ui
description: Use when working with Figma on a UI change — reading a Figma design into code, pushing a rendered preview into Figma for design sign-off, wiring Code Connect, choosing between the free arinspunk bridge and the quota-metered official Figma MCP, or coordinating parallel agents on the Figma bridge.
---

# Figma → UI — per-change checklist (Figma MCP integration)

> Origin: rules/figma-ui.md — moved by rules-triage Phase B / plugin phase 2.

Self-contained (the full _how_ + diagrams live in `../../docs/workflow/FIGMA-UI.md`).
GATE 1/GATE 2 (`WORKFLOW.md`) apply; `CLAUDE.md` wins.

## Pick the bridge by capability (not preference)

- **Write / assemble / read structure / write _literal_ Variables** → **arinspunk bridge**
  (`ClaudeTalkToFigma`, ws `:3055`) — free, unlimited. Relay `set_variable` is **literals-only**
  (no aliases / no modes — verified).
- **Aliases + light/dark Variables** → a **native `figma.variables` plugin run in-file** (imported dev
  plugin, plugin sandbox). ⚠️ `window.figma` from a plain page tab is **unverified** — don't assume it.
- **Semantic codegen / token defs / Code Connect** → **official MCP** (`claude_ai_Figma`) — the only
  three things worth the **metered reads (~6/mo Starter; verify current metering)**. Spend them **only
  on the final, locked design**. Everything else: free path (`FIGMA-UI.md` quota table).

## Reading a design INTO code

1. `get_design_context` for the exact node(s) first.
2. Large/truncated → `get_metadata` for the node map, re-fetch only needed nodes (saves context + reads).
3. `get_screenshot` for the visual reference.
4. Only with BOTH context + screenshot: pull assets, then implement.
5. Output is React+Tailwind = a **representation, NOT final style**. Replace utilities with our shadcn
   tokens; reuse `src/components/ui`; respect our routing/state/data patterns.
6. A returned localhost asset URL → use it directly; do NOT add icon packages or placeholders.
7. Strive for 1:1 visual parity; on conflict prefer design-system tokens, adjust minimally.
8. Validate against the Figma screenshot AND drive the live site (GATE 2) before "done".

## Code Connect first (try it — high leverage, unverified here)

`get_code_connect_suggestions` → review → `send_code_connect_mappings`. Reportedly makes codegen emit
your real components instead of guessing — confirm it actually references `src/components/ui` before
relying on it. Capture the agreed design-system conventions into this skill yourself (there is
no `create_design_system_rules` MCP call).

## Parallel crew on the bridge (if used)

Server-side queue makes parallel agents safe, with two hard rules:

- `set_current_page` is **blocked** in parallel mode.
- Every `create_*`/`set_*` **must pass an explicit `parentId`**. One writer per channel; researchers
  read-only. Connect: `Connect to Figma, channel <repo-folder-name>` (`join_channel`) — the project's
  stable channel = the repo folder name, derived automatically by the toolkit (no manual
  `export FIGMA_CHANNEL` needed). Once the plugin is opened, the patched panel **auto-joins the open
  file's name** as the channel — no typing — so it lands on the folder channel provided you **name the
  Figma file exactly the repo folder basename** (what `create_new_file` does at bootstrap); the panel
  field is only a manual override, never a random id. The project's Figma file is `FIGMA_FILE_KEY` in
  `.claude/worktrees.conf` (one project = one file = one channel). Vendored + patched at
  `vendor/ctf-plugin/`, imported once from the hook's stable-path mirror — see the `figma-bridge` skill
  for install + the `figma.root.name` auto-join details.

## Pushing a preview INTO Figma for sign-off (#104 · #106)

GATE-1 approves a RENDERED design, not a build instruction (#69). To sign off a NEW design beside an
existing baseline — build a dev-only `/preview` route, verify it live (screenshot desktop + mobile), then:

- **Probe before placing (#106):** `get_node_info` every frame's bounds and place in VERIFIED-empty space
  (a new column past max-right, or a verified gap) — NEVER a naive `x = baseline_width + gap` (it collides
  in a tiled file). Re-verify no overlap; loop on collision.
- **Editable frame, not just a PNG (#104):** push an EDITABLE frame (`svg-to-figma`) at those empty coords
  beside the baseline, and **EXCLUDE dev-only chrome** (DEV PREVIEW bar / STATES gallery) from the capture.
  Present the inline screenshot + the editable frame + a delta list.
- Wire into the live route **only after** the user approves those pixels.
- **Codify coverage:** after wiring, guard against the design→live gap with the web-scaffold
  `figma:presence` check — every approved design-frame section heading must render on the live route
  (headings dumped via `figma:sections`). See `web-scaffold/docs/TESTING.md`.

## See also

`design-workflow.md` · `WORKFLOW.md` (the two gates) · `../../docs/workflow/FIGMA-UI.md` (full how + mermaid diagrams + reverse leg).

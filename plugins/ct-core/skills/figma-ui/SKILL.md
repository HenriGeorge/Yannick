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

> **Why writes still go to the bridge, not the official MCP (verified 2026-10-11).** Figma's docs do
> say "tools that write to Figma files … are exempt from the rate limits" — but the *named* exempt
> tools are only `create_new_file`, `add_code_connect_map`, `whoami`. The assembly/token/recolor writes
> the bridge does run through `use_figma`, which is **NOT** on the official exempt list (third-party
> claims it is — unconfirmed), so routing them to the official MCP risks the read quota. `create_new_file`
> (bootstrap) and `add_code_connect_map` (Code Connect) already go to the official MCP. Net: the split
> above is correct — keep bulk writes on the arinspunk bridge. (Caveat: a third-party source says
> write-to-canvas may become usage-based *paid* post-beta — unconfirmed, not in Figma's rate-limit docs.)
> Source: developers.figma.com/docs/figma-mcp-server/rate-limits-access/

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

**Token-cheap REST alternative (reads only, free):** when the bridge/MCP returns a huge tree you pay
tokens for, `figma-bridge/scripts/figma/figma_digest.py --file-key <k> [--ids …] [--images …]` fetches
the file via the Figma REST API and writes a few-KB `digest.json` ({id: name/type/box/fills/text}) +
optional node PNG/SVG renders — so you read the digest + image paths, not the MB tree. Needs a
`File content:read` PAT in `FIGMA_ACCESS_TOKEN` (or `FIGMA_TOKEN`). It never requests `geometry=paths`
(the vector data that bloats the response).

## Code Connect first (try it — highest-leverage lever)

Code Connect is the single highest-value thing to set up before any codegen: **without it the model
GUESSES at components; with it, generated code references your real `src/components/ui`** (Figma's own
MCP guide states this outright). Try it before spending metered reads on anything else.

- **MCP path:** `get_code_connect_suggestions` → review → `send_code_connect_mappings`. Confirm it
  actually references `src/components/ui` before relying on it. Capture the agreed design-system
  conventions into this skill yourself (there is no `create_design_system_rules` MCP call).
- **CLI path:** the web profile scaffolds **`bin/code-connect.sh`** (a dependency-free wrapper over
  the `figma connect` CLI: `parse` / `dry` offline, `create` / `publish` / `repoint`, 429-backoff,
  token from gitignored `.env.local`) + a `figma.config.json` stub. Full runbook: the
  `ct-core` plugin's `docs/workflow/CODE-CONNECT.md`.

**⚠ Use the project-pinned CLI, not a global one — they can be a MAJOR version apart.** `bin/code-connect.sh`
runs the scaffolded project's **LOCAL** `node_modules/.bin/figma` (the `@figma/code-connect` version
pinned in that project's `package.json`). A `npm i -g @figma/code-connect@latest` can install a MAJOR
version ahead of the pin, with different parser / `figma.config.json` behavior (a consumer repo on
2026-10-11 hit a local **v1.x** vs global **v2.x** split). For a project's mappings always go through the
wrapper (or `node_modules/.bin/figma`) so behavior matches the pin; a globally-installed `figma` is for
ad-hoc `figma connect parse`/`create` outside a repo only, and the wrapper hard-fails loud if the local
install is missing rather than silently falling back to the global one — so a green global
`figma --version` is NOT evidence the project tooling works. Check the project's `package.json` for the
actual pinned version.

**⚠ `publish` needs a paid Figma Org/Enterprise + Dev seat** (parse / dry-run are free) — adopt as a
scoped per-project exception, not by default.

## Parallel crew on the bridge (if used)

Server-side queue makes parallel agents safe, with two hard rules:

- `set_current_page` is **blocked** in parallel mode.
- Every `create_*`/`set_*` **must pass an explicit `parentId`**. One writer per channel; researchers
  read-only — a **safe default, not a hard limit** (see "Multiple writers on ONE file" below for safe
  concurrent writers). Connect: `Connect to Figma, channel <base>` (`join_channel`) — the project's
  stable channel base = `<FIGMA_FILE_KEY>_<folder>` (the immutable file key + folder name), derived
  automatically by the toolkit (no manual `export FIGMA_CHANNEL` needed; the live `/status` path is
  name-agnostic). Once the plugin is opened, the patched panel **auto-joins a base of
  `<figma.fileKey>_<figma.root.name>`** — the immutable file key plus readable name, no typing — so the
  key makes the base collision-free; **name the Figma file exactly the repo folder basename** (what
  `create_new_file` does at bootstrap) so the readable suffix matches. The panel field is only a manual
  override, never a random id. The project's Figma file is `FIGMA_FILE_KEY` in `.claude/worktrees.conf`
  (one project = one file = one channel). Vendored + patched at `vendor/ctf-plugin/`, imported once from
  the hook's stable-path mirror — see the `figma-bridge` skill for install + the fileKey-based channel details.

### Multiple writers on ONE file (same channel)

"One writer per channel" is the **safe default, not a hard limit** — N agents CAN edit one file at once,
**but only if no two ever touch the same node subtree.** The relay queue serializes individual calls so
they don't corrupt each other, but it gives you **no transaction**: one writer's read-modify-write on a
node can interleave with another's. Disjointness is what makes concurrent writing safe.

- **Partition by disjoint parent nodes.** A coordinator assigns each writer its own page/frame/parent up
  front; no two writers share a parent subtree. (Same rule as a plan's `## Parallelization` — disjoint
  files there, disjoint Figma parents here.)
- **Every write passes an explicit `parentId`** (already a hard rule, and this is why): without it a
  `create_*` appends to the **current page**, which all agents share → a race. With `parentId` each write
  targets a specific node in the writer's own partition.
- **`set_current_page` stays blocked** — the current-page cursor is shared, so one agent moving it
  reorders every other agent's implicit target. Writers coordinate by `parentId`, never by page.
- **Keep each agent's reads AND writes inside its own partition** — a writer reading a node another is
  mutating is the same race; the disjoint-parent rule only holds if nobody reaches across.
- **Can't make the partitions disjoint?** (e.g. all three restyle the same component set) — do NOT run
  concurrent writers: serialize through **one** writer, or split into separate files and use `lanes`
  (one writer each — see `figma-bridge`), then reconcile.

Setup: one Figma window on the file (plugin on the file's channel) → N `claude` sessions all
`join_channel <file-name>` → a coordinator hands out disjoint parents → each writer passes `parentId` on
every `create_*`/`set_*`. Extra agents that only read (scan/export) need no partition — they're the
read-only researchers.

**Alternative transport — one window, N channels.** The vendored panel now holds **N channels at once**
(default 5 rows `<fileKey>_<fileName>_1..5`, + to add — see `figma-bridge`). So the N writers above can each join a
distinct `_N` channel on the SAME open file through ONE plugin window, instead of all sharing one channel
or opening N windows. The disjoint-`parentId` rule is unchanged — multiple channels isolate the command
streams, not the document, so two writers on different channels still race if they touch the same subtree.
Target a `_N` channel from the CLI with `--channel=<base>_N` / `FIGMA_CHANNEL=<base>_N` (base = `<fileKey>_<fileName>`).

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

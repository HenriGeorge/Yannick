---
name: context-floor-audit
description: Audit a project's session context floor — MCP servers, skill descriptions, CLAUDE.md size. Triggers on "audit my session context", "cut my context floor", "trim CLAUDE.md", "unused MCPs".
---

# context-floor-audit

Last updated: 2026-08-10

## Overview

Scans this project's baseline ("floor") context load — the MCP servers declared in `.mcp.json` /
`.claude/settings.json`, every `**/SKILL.md`'s frontmatter `description` length, and `CLAUDE.md`'s
line count — and proposes trims. **Recommend-only**: this skill never disconnects an MCP server,
never edits `CLAUDE.md`, and never edits a skill directly. Every approved description change hands
off to `writing-skills`.

## When to use

- The session feels heavy before you've typed a word — check what's actually pre-loading.
- Before a periodic context-budget review.
- After adding several MCP servers or skills and wanting a batch sanity check.

**Not for:** general skill quality/staleness (`skill-audit`), linting descriptions for triggering
accuracy (#113), or removing an MCP server without human verification of actual usage.

## Workflow

1. Run the deterministic scan (defaults to the project root; add `--root <dir>` to point
   elsewhere):

   ```bash
   python3 skills/context-floor-audit/scripts/scan.py --json
   ```

   Omit `--json` for a plain-text table instead.

2. Judge from the scan output — read the JSON, don't re-derive it by hand:
   - **`mcp_servers`**: a server never referenced by any skill or rule in the repo is a
     **candidate-unused — a suggestion to VERIFY, never a fact.** Static scan can't see runtime
     usage (a server invoked ad hoc, from memory, or by a human directly). Recommend which to
     consider removing; never disconnect one yourself.
   - **`skills[].desc_chars`**: any description over ~200 chars → propose a shorter one that still
     triggers correctly.
   - **`claude_md_lines`**: over ~200 → propose trimming toward "a directory, not documentation" —
     pointers to `docs/` rather than inlined detail.

3. Present a review table to the human, **one row per recommendation** (server / skill / CLAUDE.md),
   each flagged with what changes and why. Recommend-only throughout:
   - Never disconnects an MCP server.
   - Never edits `CLAUDE.md` directly.
   - Approved skill-description changes hand off to `writing-skills` (never a raw
     `Edit` on a `SKILL.md` from inside this skill).

4. For each row the human declines or defers, just don't act on it — the scan is re-runnable and
   cheap; there's no state file to manage (unlike `skill-audit`'s decline tracking).

## Quick reference

| Signal | Threshold | Proposal |
|---|---|---|
| MCP server unreferenced by any skill/rule | any | candidate-unused — ask the human to verify before removing |
| `desc_chars` | > ~200 | propose a shorter description, hand off to `writing-skills` |
| `claude_md_lines` | > ~200 | propose trimming toward pointers, not inlined docs |

## Common mistakes

- **Treating "unreferenced" as "unused."** The scan only sees what's on disk in this repo — a
  server can be used directly by a human, from another project, or from memory. Always phrase this
  as a candidate to verify, never as a fact, and never disconnect based on the scan alone.
- **Editing `CLAUDE.md` or a skill directly from inside this skill.** Both are hand-offs: a trimmed
  `CLAUDE.md` still needs human approval of the specific cut; an approved skill description still
  routes through `writing-skills`.
- **Re-running the scan expecting it to remember prior declines.** It doesn't track state — every
  run re-surfaces every signal above threshold. That's intentional (cheap, stateless), but don't be
  surprised a previously-declined row reappears.

## Gotchas

- MCP usage isn't knowable from disk — "unused" is a candidate to verify, never auto-remove. A
  server the scan can't find referenced by any skill/rule may still be used interactively or by a
  process outside this repo.
- `scan.py` excludes any path with a `plugins` path segment when counting skills (same convention
  as `skill-audit`) — a plugin's bundled skill won't show up in the `skills` list, and that's by
  design, not a bug.
- An empty or absent `CLAUDE.md` reports `claude_md_lines: 0` — don't read that as "nothing to
  trim" if the project actually documents itself elsewhere; it just means this particular file is
  already minimal.

## Verdict

Scan ran and printed a table (or valid JSON) with zero uncaught errors, and every recommendation
above threshold got a row in the review table → PASS. A traceback, or a signal over threshold with
no corresponding row → FAIL, treat as a bug in `scripts/scan.py` or this skill, not in the project
being audited.

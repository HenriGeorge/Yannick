---
name: audit-claude-code
description: Use when the user runs `/audit-claude-code [skills|hooks|rules|context|security|runtime|all] [--fix]`, or asks to audit their Claude Code / `.claude/` setup — a stale rule, an untriggerable skill, a tool that keeps failing at runtime, or the single highest-value fix across all of them. It is the detect half of the self-improvement loop; `/improve-skills` and `/improve` apply.
argument-hint: "[skills|context|security|runtime|all] [--fix]"
disable-model-invocation: true
---

# audit-claude-code

## Overview

One orchestrator that audits the whole `.claude/` ecosystem across axes, merges every finding into
ONE ranked action list, and (`--fix`) routes each finding to the executor that already applies it —
human-gated per fix, never auto-applying. v1 axes: **skills · context · security · runtime**
(hooks · rules are v2). It DISPATCHES existing audits + two native checks; it never reimplements
what works and never edits a file itself.

## Interview

ONLY when invoked bare — no axis AND no `--fix` — confirm scope before running; ask one question at a
time via AskUserQuestion (≥4): which axes to run; report-only or `--fix`; the failure window for the
runtime axis; whether to append a ledger row. If ANY argument is present, SKIP the interview entirely
and run with the given args.

## The common finding shape

Every axis — native scripts AND the reused audits (translated in this step) — yields findings as:
`{axis, severity(high|medium|low), summary, blast_radius(template|repo), runtime_corroborated(bool), executor(improve-skills|improve|none)}`.

## Workflow

1. **Dispatch the requested axes** (default `all`):
   - **runtime** — `python3 .../scripts/runtime_miner.py --events .claude/telemetry/tool-events.jsonl --json`
   - **skills** — `python3 .../scripts/triggerability.py --root <skills-root> --json`, PLUS run
     `skill-audit` (and cross-ref `model-routing-audit`); translate its `--json` rows to the common shape.
   - **context** — run `context-floor-audit` (`scan.py --json`); translate to the common shape.
   - **security** — run `security-review` **scoped to the `.claude/` surface only** (`settings.json`,
     `hooks/`, `skills/`, `.mcp.json`) — the axis question is "can the `.claude/` surface be abused",
     NOT a full-codebase scan (that stays the separate `/security-review`). Translate its verdict to the common shape.

   **Reused-axis → common-shape translation rules** (deterministic, so ranking is stable):
   - `security-review` tiers: Critical→`high`, High→`high`, Medium→`medium`, Informational→`low`;
     `PASS`→no finding; `WAIVED`→no finding (note it in the report).
   - `skill-audit` rows: each flagged concern → one `medium` (`missing_gotchas`/`missing_verdict`/
     `script_candidate`/`askuserquestion`) finding, `executor:"improve-skills"`.
   - `context-floor-audit`: an over-budget MCP set or oversized `CLAUDE.md` → `medium`; an over-long
     skill description → `low`; `executor:"improve"`.
   - Default `blast_radius:"repo"` unless the finding is about a template-shipped asset (a plugin
     skill / a shipped hook / a scaffolded rule) → `"template"`. `runtime_corroborated:false` for
     every non-runtime axis.
2. **Rank** — concatenate every axis's common-shape findings into one JSON array; pipe to
   `python3 .../scripts/rank.py --json`. This is the single prioritized list.
3. **Report** — render the ranked table (`rank | axis | severity | finding | -> suggested executor`).
4. **Ledger** — append one dated row to `docs/audit-claude-code-log.md`:
   `date | skills | context | security | runtime | top-action | Δ vs last` (per-axis cell = `PASS` or `N findings`).
5. **`--fix` (human-gated, per finding)** — for each finding, ask the human to approve. On approval:
   route a **skills** finding (`executor:"improve-skills"`) to `/improve-skills`; route a
   **rule/hook/doc** finding (`executor:"improve"`) to `/improve`, whose proposal sink is
   `.claude/improvements/<YYYY-MM-DD-slug>.md`; a finding with `executor:"none"` (e.g. runtime) is
   **reported, not routed** (no v1 executor). ZERO approvals ⇒ ZERO edits (`git status` stays clean).
   NEVER auto-apply; NEVER edit a file directly.

## Credits

The native skills-**triggerability** lint borrows its idea from okjpg/skill-audit
(cross-LLM trigger reliability), reimplemented native and zero-dependency (no live GPT/Gemini calls,
no inherited dependency — R5). Sources credited per the design spec (G2).

## Gotchas

- A fresh repo with an empty `tool-events.jsonl` yields NO runtime findings — correct, not a defect.
- There is no permission-denied `kind` in telemetry today; the runtime axis is failure-rate + thrash
  + latency + loop-hotspot (the `kind=="loop"` rows the loop_detector already writes), NOT denial.
- v1 routes ONLY skills (an executor exists); everything else is reported, never silently "fixed".
- Never claim to fix what it can't route.

## Verdict

Report the ranked list + the ledger Δ. `--fix` succeeds when every approved finding reached its
executor and `git status` shows no direct edits by this skill.

---
name: improve
description: Use when the user runs `/improve [session|history|config]`, or asks to mine recurring lessons/telemetry into concrete enforcement-asset changes — turning `docs/lessons.md` `Seen ≥3x` signals and `.claude/telemetry/tool-events.jsonl` thrashing/failure data into routed, human-gated proposals for rules, hooks, CLAUDE.md, and docs. Also fires when recurring lessons keep rotting in the log because nothing promotes them.
argument-hint: "[session|history|config]"
---

# improve

## Overview

`/dev-reflect` harvests lessons and *recommends* promotion (`Seen ≥3x` → "graduate OUT to a
hook/rule/CLAUDE.md"), but **nothing executes it** — recurring lessons rot in the log. `/improve`
is the miner that closes that loop: it clusters recurring `docs/lessons.md` signals + telemetry into
`.claude/improvements/*.md` proposal drafts, each routed by **two axes** (asset-type × ownership), and
audits whether prior promotions actually landed.

**Core principle — Level-2, never auto-apply.** A proposal is a PR-able *draft*. `/improve` NEVER
edits a rule / hook / CLAUDE.md / doc. Zero human approvals → zero asset edits. Automate the
reversible (writing a draft); gate the irreversible (editing an enforcement asset) behind a human.

**Scope carve-out.** `/improve` owns **rule · hook · CLAUDE.md · doc** targets only. A **skill**-typed
signal is NOT written as a `.claude/improvements/` stub (its sibling `/improve-skills` never reads that
dir) — it is handed off as a `/dev-reflect` "Process improvements" `Skill/command` row, the channel
`/improve-skills` already consumes. Config-health is already owned elsewhere — do not re-implement it:
CLAUDE.md size / skill-desc length → `context-floor-audit`; skill structure/model → `skill-audit`;
model-pin leaks → `model-routing-audit`; lesson harvest → `/dev-reflect`.

## When to use

- The user runs `/improve` (optionally `session` / `history` / `config` to hint scope).
- Recurring lessons (`Seen ≥3x`, or an `#issue` appearing ≥3×) keep being re-learned with no fix landing.
- After a burst of thrashing/failures you want corroborated against telemetry and turned into a fix.

**Not for:** editing the asset yourself (that is the human's Level-2 gate); skill-body improvements
(`/improve-skills`); config-health scans (the owned skills above).

## Interview

Choice-taking skill → run this BEFORE mining. Ask **one `AskUserQuestion` at a time**, in order;
each has a recommended default. Skip a question only if the invocation argument already answers it
(e.g. `/improve config` pins scope).

1. **Scope** — what to mine? (a) *this session*'s new lessons only · (b) *history* — the whole
   `docs/lessons.md` backlog · (c) *config* — drift-audit prior promotions only. **Default: history.**
2. **Sources** — (a) *lessons only* · (b) *lessons + telemetry* (`tool-events.jsonl` corroboration).
   **Default: lessons + telemetry** (higher-confidence proposals).
3. **Apply-batch size** — how many proposals to draft this run (1 / 3 / all clustered). Bounds the
   review load. **Default: 3.**
4. **Proposal output** — (a) *local file only* in `.claude/improvements/` for review · (b) *offer-PR*
   (stage the source edit + print the propagation command for the human to run). **Default: local file.**

## Workflow

```
Gather → Drift-audit → Consolidate → Route (asset-type × ownership) → Write proposal → STOP (human gate)
```

### 1. Gather
Read `docs/lessons.md`; cluster signals recurring `Seen ≥3x` (or an `#issue` appearing ≥3×). If
sources include telemetry, read `.claude/telemetry/tool-events.jsonl` for thrashing/failure
corroboration (retry_count, non-zero exits on the same file/tool). **Also mine the
self-improvement-loop capture sinks** (all under `.claude/telemetry/`, gitignored, metadata-first):

**Read telemetry across ALL worktrees, not just this checkout (#787).** The sinks are
`CLAUDE_PROJECT_DIR`-scoped, so every worktree writes its own `.claude/telemetry/` — and delegated
BUILD work runs in worktrees, where the majority of friction data lands. Reading only the primary
checkout orphaned ~90% of `failures.jsonl` in the measured case. Enumerate the sinks across the whole
repo and **merge the rows before clustering**, keeping each per-worktree file intact:

```bash
# repo-level common dir; its parent holds the primary checkout + .claude/worktrees/*
common=$(git rev-parse --git-common-dir); root=$(cd "$common/.." && pwd)
# every worktree's telemetry (primary + .claude/worktrees/*), one sink kind at a time
find "$root" -path '*/.claude/telemetry/failures.jsonl' -print0 | xargs -0 cat 2>/dev/null
# (equivalently, walk `git worktree list --porcelain` for each worktree path)
```

Apply the same union to `tool-events.jsonl`, `iterations.jsonl`, `hook-events.jsonl` below.
- `iterations.jsonl` — attempts-to-green per task. A cluster of high-`attempts` tasks on the same
  surface is a friction signal (e.g. "the API client keeps needing 4+ tries after a schema change").
- `failures.jsonl` — classified failures (`cmd_fail`/`test_fail`/`lint_fail`/`type_fail`/`blocked`/
  `repeated_edit`). A recurring `kind`+`file` pair is a candidate rule/skill.
- `hook-events.jsonl` — hook decisions. Two derived signals worth a proposal: a gate that **blocks
  repeatedly**, and a **bypass-token** (`WORKFLOW:no-*`) used ≥3× — the "gate routed around under
  pressure" signal.

**Defensive parse:** skip any unparseable line, never fabricate a signal.

**Skip already-promoted lessons.** A lesson whose entry already carries a promotion record — an
inline `→ promoted to <asset>` on its headline or `**Seen**` line, OR a standalone
`**Promoted**: → <asset>` line — has already graduated; do NOT re-cluster it as a fresh candidate.
Both forms occur in `docs/lessons.md`; matching only `→ promoted to` re-surfaces an already-landed
lesson as a proposal for work that is done (the exact miss that generated a redundant spec). Verify
each surviving candidate's LIVE target state here at Gather (grep the asset), not later at build.

### 2. Drift audit (did prior promotions land?)
For each promotion record in `docs/lessons.md` — an inline `→ promoted to <asset> YYYY-MM-DD` stub
OR a standalone `**Promoted**: → <asset> (YYYY-MM-DD)` line (both forms occur) — grep the named
asset for the promised text → mark **Verified** (present) / **Drifted** (changed) / **Missing** (absent).
Re-surface Drifted/Missing as fresh proposals — the stub is the only durable landed-record, since
`.claude/improvements/*.md` is gitignored/ephemeral.

**Verify against the promised TEXT — READ the matched line, never trust a count.** A `**Verified**`
verdict MUST quote the asset line that carries the promised behavior (`file:line`). A match *count*
(`grep -c`) or a broad `a\|b\|c` OR-pattern is NOT verification: a count of 1 can be an unrelated
sentence that happens to share a word. Grep for the SPECIFIC promised string and read what matched —
mis-verifying "landed" silently drops a genuine unlanded promotion (generalizes lesson #397: verify
the premise, not the label).

### 3 + 4. Consolidate + two-axis route
Per candidate, decide BOTH axes:

**Axis 1 — asset-type:**

| Signal shape | Target |
|---|---|
| Procedure gap (a repeatable how-to that was missed) | **skill** → write a `/dev-reflect` Process-improvements `Skill/command` row (NOT a stub) |
| Convention gap (a judgment rule agents should follow) | **rule** |
| Deterministic miss (a tool-call-checkable guard) | **hook** |

**Axis 2 — ownership:** call `claude-template classify-ownership <target-repo-relative-path>` → one of
`UPSTREAM` / `REPO-LOCAL` / `SHARED-GLOBAL` / `ASK`. Never re-implement the cmp/path rule — this
binary is the single source of truth (shared with `propagate.sh`). Record the propagation recipe:

| Bucket | Recipe (staged edit + the exact follow-up) |
|---|---|
| **UPSTREAM** (template-owned) | edit the canonical source; copy-model asset (hooks/rules) → stage + flag `propagate.sh --apply`; plugin-native asset (docs/agents/skills/commands) → bump the plugin version |
| **REPO-LOCAL** (bespoke/additive) | modify here only — fully automatable (still Level-2 gated) |
| **SHARED-GLOBAL** (`~/.claude/`) | edit canonical `~/.claude/`; if HAND_RECONCILED, also hand-mirror the repo snapshot + regen `.reconciled.sha256`. The LIVE side is outside the repo → **FLAG for human hand-mirror**, cannot auto-apply |
| **ASK** (new / ambiguous) | inline run → stop and ask the human; offline/nightly run → tag the proposal `needs-human-routing` and NEVER route or apply |

**The honest boundary:** classification is deterministic; *action* is fully automatable only for
REPO-LOCAL. UPSTREAM and SHARED-GLOBAL both end in a human-run propagation step — the deliverable is
the staged edit + the exact command, never a silent cross-layer write.

### 5. Write the proposal
For rule/hook/CLAUDE.md/doc targets, write `.claude/improvements/<YYYY-MM-DD-slug>.md` with four sections:

```
## Observed
<the recurring pattern, in one line>

## Evidence
- lessons.md: <line refs / headlines>  (Seen Nx)
- telemetry: <retry_count / exit / file, if used>

## Proposed change
- asset-type: <skill|rule|hook>  ·  ownership: <UPSTREAM|REPO-LOCAL|SHARED-GLOBAL|ASK>
- recipe: <the exact staged-edit + propagation command from the table>

## Confidence: <High|Med|Low>
```

**Confidence (recurrence-based, no numeric false precision):** High = `Seen ≥3` + telemetry
corroboration · Med = `Seen 2` · Low = one-off / inferred.

**Idempotence — overwrite-by-slug.** Key the file by topic slug. On a re-run, **skip a slug whose
recurrence count has not grown** — so this inline miner and a later nightly Ollama miner can't pile
up duplicates for one signal.

### 6. STOP — hand to the human
Leave the local file(s) for Level-2 review. If the Interview chose *offer-PR*, additionally stage the
source edit and print the propagation command — but still do not apply. Skill-typed signals: confirm
the `/dev-reflect` Process-improvements row is written, not a stub.

## Common mistakes

- **Auto-editing the asset.** The proposal is a draft; the human's approval is the gate. Never `Edit`
  a rule/hook/CLAUDE.md as part of `/improve`.
- **Writing a skill-typed signal as a `.claude/improvements/` stub.** `/improve-skills` never reads
  that dir — the signal would have no consumer. Route it to the `/dev-reflect` row instead.
- **Re-implementing the ownership rule** instead of calling `claude-template classify-ownership` — two sources
  of truth for "template-owned" will drift.
- **Silently patching an UPSTREAM asset locally** — the next `propagate --apply` clobbers it. Edit the
  canonical source and flag the propagation step.
- **Fabricating a signal from an unparseable line.** Skip it. A proposal must trace to real evidence.
- **Trusting `grep -c` / a fuzzy pattern for a drift verdict.** A match count can't tell a real landing
  from an unrelated hit — read the matched line and cite `file:line` before marking a promotion Verified.
- **Asking "new/ambiguous" in an offline run.** No human is present — tag `needs-human-routing` and
  leave it for the review gate.

## Red flags — STOP

- About to `Edit`/`Write` a rule, hook, CLAUDE.md, or doc target → that is the human's job, not `/improve`'s.
- About to write more than the Interview's apply-batch size → re-confirm.
- A proposal with no lessons/telemetry line references → you invented it; drop it.

## Verify

- The skill loads (frontmatter parses; `name: improve`).
- `skill_nudge` does NOT WARN — the `## Interview` block satisfies the choice-taking-skill convention.
- No rule/hook/CLAUDE.md was edited by a run with zero human approvals.

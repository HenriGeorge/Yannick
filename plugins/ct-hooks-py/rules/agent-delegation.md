# Agent Delegation

Last updated: 2026-10-19 21:27

Delegate to a subagent for **substantial** work; do trivial things inline. Reviewers/auditors hold no
locks: dispatch the whole panel CONCURRENTLY in one message and keep working while it runs.

**Why a FRESH reviewer, not self-review:** the author — and the coordinator who steered the work —
shares the blind spot that produced it. Route every non-trivial diff/design to an independent
reviewer, and prefer **distinct lenses** (correctness + silent-failure + security): two lenses
converging on the same spot is a far stronger merge-blocker than one lens alone.

## Roles → which agent (concepts; use the real global agents)

- **researcher** — a tight, cited answer without loading 40 files: `web-researcher` (web/docs),
  `codebase-explorer` or `Explore` (in-repo). Terse, `file:line`, read-only.
- **auditor** — the P5 REVIEW panel over a diff, **dispatched only through `/pr-open`** (a
  hand-dispatched panel skips docs-impact and the round bookkeeping, so it is not a panel),
  **CONCURRENTLY in ONE message**. The canonical fact source for marker form, verdict vocab and
  bypass tokens is the enforcement/gate-roster reference's "PR-gate merge axes (canonical)" section;
  what shapes dispatch:
  - **Lenses and what they own.** `code-reviewer` (required; owns the code-review verdict) ·
    `silent-failure-hunter` (may escalate) · `security-reviewer` (owns the separate security
    verdict `PASS`/`FINDINGS`/`WAIVED`; `pr_gate` fails CLOSED without a fresh `PASS@head`, bypass
    `WORKFLOW:no-security`) · `test-quality-reviewer` (owns the separate test-quality verdict —
    plan-named acceptance tests green at head AND ≥1 mutation-proven able to fail; `pr_gate` fails
    CLOSED without `test-quality:PASS@head`, bypass `WORKFLOW:no-test-quality`) · advisory
    `docs-impact-agent` (tier ≥ 1 when the diff touches a documented surface; dropped on a
    tests/config-only diff). A fourth, non-panel axis `suite:PASS@head` (full suite green at the
    final synced head) is machine-asserted the same way (bypass `WORKFLOW:no-suite`). **Opt-in
    advisory (`/pr-open --deep`)** `code-simplifier` + `comment-analyzer` — same comment, no own
    marker, NOT in the default panel.
  - **Risk tiers** (`claude-template pr-tier` decides; `/pr-open --full` forces tier 2): tier 0
    docs-only → `code-reviewer` only, security + test-quality `WAIVED reason=docs-only` (re-verified
    by `pr_gate`); tier 1 → code + security + test-quality (+ docs-impact) — prose prompt-code
    sub-case swaps test-quality for docs-impact with `WAIVED reason=no-testable-behavior`;
    prose-dominant sub-case (≤ 20 non-gated code lines) drops only `silent-failure-hunter`; tier 2
    → all gating lenses. Gated paths (`hooks/`, `hook-wiring/`, `.github/`, a `_gate.` path,
    `settings`, `hooks.json`, `auth`, and every `bin/` script except those listed in
    `bin/lib/ungated-paths.txt`) never take a tier-1 route. `bin/` is gated by **role**, not
    wholesale: the exemption file is deny-by-default, so a new `bin/` script is gated until it is
    listed deliberately.
  - **Fix rounds (R6).** A fix round does not re-dispatch the `Open:` lenses as a panel.
    `code-reviewer` reviews the fix delta every round; every other `Open:` lens is closed by proof:
    a test shown RED on the pre-fix code and GREEN after the fix, recorded as finding → test →
    RED/GREEN in the PR comment. Exception: a fix to a security finding in secrets or supply-chain
    code gets one `security-reviewer` re-check; once `Open:` is `none`, `security-reviewer` and `test-quality-reviewer` re-review the delta diff and post a normal verdict at the new head —
    unless the delta touches a gated path or a lens answers `NEEDS-FULL`, which forces a full-diff
    re-run. Never carry a verdict forward. Tests follow the same shape: a single local full-suite run under `bin/test-lock` at the current head is the PR's one full suite; targeted files for a
    contained fix-round delta (a test-runner or setup-script change always gets a full run). Several
    PRs in flight → the merge queue in `workflow.md`.
  - **Panel sizing by risk (R7):** low-risk work (docs, manifests, probes, test registration) gets
    `code-reviewer` only, plus `test-quality-reviewer` when it adds real assertions; the full panel
    is for secrets, hooks, CI, merge gates and third-party code ingestion. Related train members are reviewed in one panel dispatch with a verdict per member, not one panel each; the integration
    PR's final `/pr-open` reviews only the **integration delta** (merge resolution + release step),
    escalating to the full-diff panel only when that delta touches a gated path.
  - **Read-only agents.** All panel agents run with `tools: Read, Grep, Glob` — so the **dispatcher
    pastes the diff (or changed-file list) into each spawn prompt**, and **points each reviewer at
    the worktree tree, not the primary checkout**: put the worktree-absolute repo root in the prompt
    ("Read/Grep/Glob ONLY under this root") and name the primary checkout as a stale tree never to
    read; for a small diff paste the changed files inline. A finding that reduces to "I couldn't
    locate the change" is this drift — re-dispatch, don't act on it. Panel agents run with `omitClaudeMd: true`, `effort: medium` and a turn cap (`maxTurns: 25`; `docs-impact-agent` 40 — a
    capped run returns a partial report, which `/pr-open` treats as no verdict).
  - **Gating lenses need embedded evidence.** For `security-reviewer` / `test-quality-reviewer`
    the dispatcher RUNS and embeds what a read-only agent cannot produce: the green-at-head suite
    run plus, for test-quality, a mutation RED→restore transcript that flips a **plan-named** test by
    mutating the covered **source under test**. A `FINDINGS` returned only for missing evidence is
    the cue to gather it and re-dispatch. Any verdict marker posted by hand MUST be wrapped
    `<!-- prefix:VERDICT@<full-40char-headRefOid> -->` (`gh pr view <n> --json headRefOid`) — a bare
    line or a short sha fails the gate CLOSED. If the panel changes code, re-run VERIFY before merge.
- **test-designer** — coverage map (flow/state diagrams + checklist) BEFORE tests: `test-designer`.
- **skill-author** — creating or editing a skill? Follow `skill-creator`'s checklist through
  `writing-skills`: scripts for deterministic steps · a running `## Gotchas` list · a pass/fail
  verify step · a min-viable `model:` for grunt work · `AskUserQuestion` for clarifying Qs.
  `model:`/`context:`/`effort:` are Claude-Code-only frontmatter — not for skills uploaded via the
  Agent-Skills spec. `/skill-audit` = cost/structure hygiene (plugin index in a plugin-load
  project); `/skill-reinvent <skill>` = strategy re-derivation. Both advisory, both apply through
  `writing-skills`.
- **test-writer** — real tests in the repo's framework: `playwright-tester` / `frontend-testing` (vitest) / pytest. Each test must be able to fail.
- **browser-tester** — run tests against the *running* app on the worktree's port
  (`playwright-tester` + `local-browser-testing`). Test-auth contract: `BASE_URL=http://localhost:$PORT`,
  creds in git-ignored `.env.test` (+ `TEST_AUTH_MODE`), a seeded user via `npm run seed:test`.
  Hold the per-repo lock (`bin/test-lock --wait -- <cmd>`). Missing `.env.test` → fail loud; never
  test unauthenticated. A builder/fix round runs the affected slice; the full suite stays the
  one-per-PR gate, never replaced by a subset.

## Fork ≠ free — construct a focused prompt, don't re-send session state

A subagent processes whatever context it's given from scratch, and its RETURN re-enters your
context. Keep returns small (a distilled summary + a report-file path, a few thousand tokens). No
hook can see or shrink the spawn prompt or the return — the delegator owns this:

- **Construct EXACTLY what the subagent needs** — "review these 3 files for X," not the session's
  back-and-forth. Pair with `dispatching-parallel-agents` for the fan-out shape.
- **Delegating a DELETE/RENAME refactor? Name the P6 doc pass explicitly** — repoint every **live**
  doc/skill/`plugin.json` off the deleted name (historical `docs/superpowers/{specs,plans}` stay) and
  `grep`-clean-verify before opening the PR.
- **Ask for a summary back, not a dump.**

## Gating agents write durable results (idle-safe)

An agent whose return GATES the next step (a reviewer, a decision-driving researcher) is dispatched
idle-safe — a hung agent must never freeze the leader:

- **Durable result:** give it a unique report-file path (`<scratchpad>/agent-<label>.md`); it writes
  incrementally and returns ONLY a one-line summary + that path.
- **Leader liveness:** HUNG = ≥2 consecutive idle notifications AND the report-file's mtime
  unchanged since the last check (a growing file = still working).
- **On hung:** `TaskStop` it, read the partial report, re-ask AT MOST once; then do the work inline
  or re-dispatch ONE fresh agent. Never re-ask a hung agent more than once.
- **Scope:** gating agents only; fire-and-forget advisory agents are exempt.

Honest limit: no hook can observe a dispatched Agent's liveness. This is a convention, not a mechanism.

## Model routing (pinned exact IDs · bare aliases banned)

**Every agent pins an EXACT model ID** in its `model:` frontmatter — the single source of truth;
this table must match it (`tests/test_model_routing.sh` MR-07 fails on drift). Session default:
`claude-opus-4-8`.

| Model | Agents | Why |
|---|---|---|
| `claude-sonnet-5-5` | `crew-coordinator`, `crew-implementer`, `critical-thinking`, `code-reviewer`, `security-reviewer`, `test-quality-reviewer`, `test-designer`, `silent-failure-hunter`, `pr-test-analyzer`, `type-design-analyzer`, `playwright-tester`, `api-architect`, `frontend-perf`, `postgresql-dba`, `react19-commander`, `search-ai-optimization`, `tech-debt-planner`, `tech-writer`, `ux-designer` | The roles that decompose/implement work and the substantive review/diagnosis lenses: correctness review, baseline security review, meaningful-coverage validation, edge-case/regression test design, failure-path tracing, test-vs-change assessment, API-boundary/type-invariant analysis, and browser-failure diagnosis. Quality matters enough here to need judgment past Haiku, but not so much that every run should default to Opus — escalate a single difficult finding rather than routing the whole role there. |
| `claude-haiku-5-5` | `codebase-explorer`, `web-researcher`, `code-simplifier`, `comment-analyzer`, `docs-impact-agent` | Bounded, mechanical work: file discovery and bounded code tracing, focused fact-gathering (escalate synthesis when needed), bounded simplification/duplication detection, stale-or-misleading-comment detection, and likely-doc-impact identification. |
| `claude-opus-4-8` | `gpui-researcher` | GPUI API/convention research against the live crate and Zed source; pinned at the session default and kept there. |

Light work outside agents (pre-classified trivial edits) goes to `claude-haiku-5-5`. Issue
triage in `github-solve-issues` Stage 1 defaults to a **preference chain** (`stage1-triage.py` against
`ollama list`): `deepseek-v4-pro:cloud` (metered via the Ollama cloud sub) → `phi4` (free local) →
`claude-haiku-5-5` (last resort, no Ollama). `TRIAGE_OLLAMA_MODEL` forces one model;
`TRIAGE_CLASSIFY_CMD` any command. Details: `wiki/concepts/model-routing.md`.

**Escalation is the caller's call, on observable signals.** A Haiku agent cannot switch models; when
it reports a blocker, the dispatcher may re-dispatch ONE stronger agent type for that question only.
Trigger on an unresolved question the agent reported back, a repeated failed attempt, or two lenses
disagreeing — never on a model's self-reported confidence.

⚠ **Bare aliases are banned.** Never use `opus` / `sonnet` / `haiku` / `fable` in a `model:`
frontmatter field or a `--model` flag — an alias floats to the newest generation. **This also covers
the Agent/Task tool's runtime `model:` param — and there OMITTING it is the ONLY safe form**: that
param's enum accepts only bare aliases, so never pass it; choose the model by choosing the agent
type. (The `pre_tool_use` guard blocks a bare alias on that param; it OVERRIDES any skill that says
"always specify the model".)

## When to delegate (the model judges)

- **Substantial research** (multi-file / multi-source) → a researcher subagent. A one-off lookup →
  inline `WebSearch`. `/deep-research` is the heavyweight — genuinely deep, multi-source questions.
- **Before a commit or PR**, or a risky diff → an auditor.
- **A net-new feature with real flows/state** → test-designer → (human review) → test-writer →
  browser-tester. Skip the pipeline for trivial changes.

## How to delegate (prefer in-process)

- **Default to in-process subagents (Agent/Task tool)** — results return into your transcript. Never
  spawn a separate `claude` in a tmux window for a sub-task.
- **Forming a crew — one mode: in-process teammates** via the Agent tool, coordinated with
  `SendMessage`; the `teammate_idle` hook keeps a teammate working while it owns tasks. **Reap a
  teammate that idles with NO remaining tasks** — `TaskStop` it to free the slot rather than leaving
  it idle (the `teammate_idle` hook only keeps a task-owning teammate working; it cannot terminate,
  so an idle non-owner is the leader's to stop). Keep only the teammates that still own live work.
  Count writers, not agents: read-only auditors/researchers need no worktree; every extra implementer
  gets its OWN native worktree (Agent `isolation: worktree`), one writer per worktree. **A plan batch is concurrent by default** — when `## Parallelization` lists a batch with ≥2 tasks, dispatch one
  implementer per task AT THE SAME TIME, each in its own worktree on its own branch off the plan
  branch; merge each back with a merge commit and review the batch in ONE reviewer dispatch with a
  verdict per member. Exceptions: tasks whose `Files:` overlap, and the task that writes the hooks
  fingerprint or bumps versions — last and alone.
- **Test cadence in every implementer brief:** touched test files during BUILD and fix rounds; a full suite per PR for a tier-2 PR only, as a single local run under `bin/test-lock` at the final synced
  head (there is no CI). Keep full-suite runs to a few per session.
- **Builder brief — every implementer dispatch carries this checklist**, self-checked before "ready":
  - a fail-open or degraded path is visible on **stdout** (a hook's `systemMessage`), not only stderr;
  - every new test is shown failing **before** the fix (red-first);
  - the repo's deterministic doc checks (docs-drift / inventory-count tests) are in the targeted run;
  - a builder's targeted run includes every test that reads a doc it edits — find them with
    `grep -rln '<doc path>' tests/`;
  - docs that describe the changed behaviour are updated in the same PR;
  - a stale-base block means sync, don't bypass: commit in-progress work (`git add <files> && git
    commit -m "wip: mid-round sync state"`) → `git merge origin/main` → continue. **Never `git stash`
    for a mid-round sync** — the stash stack is global and strands files under a concurrent writer.
    The rebase-check bypass token is honoured ONLY on a merge commit;
  - on a **tier-2** PR, the builder runs its own tier-2 self-check (`silent-failure-hunter` +
    `security-reviewer` on `origin/main...HEAD`, findings fixed, targeted tests re-run) before
    opening the PR, and names each lens's verdict + finding count under `## Self-check` in the PR
    body (tier 0/1 skip this).
- **Status cadence.** A coordinator reports to the user only on a state change — merged, blocked /
  needs a decision, or a full suite red.
- **A plan that will be fanned out declares its parallel batches:** a plan with ≥2 tasks carries a
  **Mermaid task DAG** (edges = depends-on) and a machine-parseable `## Parallelization` callout
  listing batches by task id (`- Batch 1: T1, T3` / `- Batch 2: T2`). Same-batch tasks MUST own
  **disjoint files** in their `Files:` blocks; tasks left out of every batch are sequential. The
  `parallel_gate` hook enforces this at plan-commit time (BLOCK on overlap or a missing callout;
  bypass `WORKFLOW:no-parallel`).

# Agent Delegation

Last updated: 2026-10-05 23:40

Delegate to a subagent for **substantial** work; do trivial things inline. The runner
(native worktrees + the hook layer) is the guaranteed win — roles are opt-in leverage, not ceremony. Reviewers/auditors hold no locks: dispatch the whole panel CONCURRENTLY in one message and keep working while it runs.

**Why a FRESH reviewer, not self-review:** the author — and the coordinator who steered the work —
shares the blind spot that produced it, so self-review structurally can't catch what a fresh set of
eyes will. Route every non-trivial diff/design to an independent reviewer, and prefer **distinct
lenses** (correctness + silent-failure + security): two lenses converging on the same spot is a far
stronger merge-blocker than one lens alone.

## Roles → which agent (concepts; use the real global agents)
- **researcher** — a tight, cited answer without loading 40 files: `web-researcher` (web/docs),
  `codebase-explorer` or `Explore` (in-repo). Terse, `file:line`, read-only.
- **auditor** — the P5 REVIEW panel over a diff, dispatched **CONCURRENTLY — in ONE
  message**: **required** `code-reviewer` (owns the code-review verdict) + `silent-failure-hunter`
  (error-handling/fallbacks; may escalate) + `security-reviewer` (owns the SEPARATE security verdict
  `PASS`/`FINDINGS`/`WAIVED` — the `pr_gate` merge check fails CLOSED without a fresh `PASS@head`
  marker, bypass `WORKFLOW:no-security`) + `test-quality-reviewer` (owns the SEPARATE test-quality
  verdict `PASS`/`FINDINGS`/`WAIVED` — verifies the plan-named acceptance tests are green at head AND
  ≥1 is mutation-proven able to fail; `pr_gate` fails CLOSED without a fresh `test-quality:PASS@head`
  marker, bypass `WORKFLOW:no-test-quality` — Deliverable L); a fourth, non-panel axis —
  `suite:PASS@head` (full-suite green at the final synced head, active only where CI is absent) —
  is machine-asserted the same way: `pr_gate` fails CLOSED without it, bypass `WORKFLOW:no-suite`;
  **advisory** `code-simplifier`
  (behavior-preserving cleanups) + `comment-analyzer` (comment rot) — findings in the same single
  comment, never their own marker. That is the full (tier-2) roster: `/pr-open` **risk-tiers** the
  panel via `claude-template pr-tier` — tier 0 docs-only → `code-reviewer` only, with security and
  test-quality posted as `WAIVED@<head> reason=docs-only` (which `pr_gate` re-verifies against the
  PR's real file list); tier 1 low-risk → `code-reviewer` + `security-reviewer` +
  `test-quality-reviewer` — or, for the **prose prompt-code** sub-case (prose-only `.md` under
  a plugin's `commands`/`agents`/`rules` or top-level `rules/`), `code-reviewer` + `security-reviewer`
  + `docs-impact-agent` with `test-quality` posted `WAIVED reason=no-testable-behavior`
  (`pr_gate` re-verifies it, test-quality axis only); tier 2 logic → everything above. At tier ≥ 1 the advisory
  `docs-impact-agent` runs in the same round-1 message. `/pr-open --full` forces tier 2. **A panel is
  dispatched only through `/pr-open`** — a hand-dispatched panel skips docs-impact and the round
  bookkeeping, so it is not a panel. Fix rounds re-review via `/pr-open` too: its comment's `Open:`
  line names the lenses with unresolved findings, and the delta round re-dispatches only those
  (plus `code-reviewer`). The head-bound gating lenses (security, test-quality) re-run on the **full
  PR diff** once `Open:` is `none`, before their markers are posted — never carry a verdict forward.
  **Integration-train members** (see `workflow.md`) are the one exception: with no PR of their own,
  the coordinator applies the same `/pr-open` contract (tier, docs-impact, `Open:` / `Fix rounds:`,
  recorded per member as a comment on the integration draft PR under a `train-member:` marker —
  never `pr-open:tier`, which would turn the train's review into a delta) to the branch diff. `/pr-open`
  itself then runs its normal panel on the whole integration PR, plus fix rounds until clean — it
  never stamps the member reviews onto the integration head.
  Reviews the diff, tries to break it. All six panel agents are **read-only** (`tools: Read, Grep, Glob` — no
  shell/Edit/Write), so the **dispatcher pastes the diff (or the changed-file list) into each
  reviewer's spawn prompt** — a reviewer can no longer run `git diff` itself, nor push/merge.
  **Point each reviewer at the worktree tree, not the primary checkout.** Because the agents are
  read-only, their neighbor Read/Grep/Glob resolve against whatever checkout they land in — so a
  reviewer dispatched for a worktree PR will silently read the **primary checkout** (parked on the
  default branch, NOT this PR's head) and emit false "change not found" / stale-content findings. The
  dispatcher MUST put in each reviewer's prompt the **worktree-absolute repo root** ("Read/Grep/Glob
  ONLY under this root") and the primary checkout's path named as a **different, possibly-stale tree
  that must never be read**; for a small diff, paste the full changed-file content inline (the only
  drift-proof option). A reviewer finding that reduces to "I couldn't locate the change" is this
  drift, not a defect — re-dispatch with the worktree root rather than acting on it. The advisory auditors (`docs-impact-agent`,
  `pr-test-analyzer`, `type-design-analyzer`) are read-only on the same contract.
  **For a GATING reviewer (`security-reviewer` / `test-quality-reviewer`), the dispatcher also RUNS
  and embeds the executable evidence the read-only agent cannot produce itself** — the green-at-head
  suite run plus, for test-quality, a mutation RED→restore transcript that flips a **plan-named** test
  by mutating the covered **source under test** (a mutation to a data input or the live artifact proves
  the pipeline, not the tests — that's a GATE-2 exercise, not a test-quality proof) — so the
  reviewer can issue `PASS@head` without shell access. A `FINDINGS` returned only because the agent
  couldn't self-generate that evidence is the dispatcher's cue to gather it and re-dispatch, not a
  real defect. When the dispatcher posts ANY `pr_gate` verdict marker by hand
  (`code-review` / `security-review` / `test-quality`) rather than via `/pr-open`, it MUST wrap each
  one `<!-- prefix:VERDICT@<full-40char-headRefOid> -->` — a bare text line OR a short/abbreviated
  sha both fail the merge gate CLOSED (get the sha with `gh pr view <n> --json headRefOid -q
  .headRefOid`, never an abbreviation). If the panel changes code, re-run VERIFY
  before merge. **Fix-round re-reviews (R6):** A fix round does not re-dispatch the `Open:` lenses as a panel. `code-reviewer` still reviews the fix delta every round — it owns the head-bound verdict — and every other `Open:` lens (`silent-failure-hunter`, `code-simplifier`, `comment-analyzer`) is closed by proof instead of re-dispatch: a test shown RED on the pre-fix code and GREEN after the fix, recorded as finding → test → RED/GREEN counts in the PR comment. **Exception:** a fix to a security finding in secrets or supply-chain code (env/secret handling, vendoring or cloning third-party code, auth) still gets one `security-reviewer` re-check of that fix. And once `Open:` is `none`, `security-reviewer` and `test-quality-reviewer` re-review the delta diff and post a normal verdict at the new head — unless the delta touches a **gated path** (`hooks/`, `bin/`, `.github/`, `hook-wiring/`, a path matching `_gate.`, `settings`, `hooks.json`, or `auth`), which forces a full-diff re-run instead (either lens may also answer `NEEDS-FULL` to force it). Tests follow the same shape: a single local full-suite run under `bin/test-lock` at the current head is the PR's one full suite, targeted test files for a contained fix-round delta (a test-runner or setup-script change
  always gets a full run). With several PRs in flight that full suite runs by slot — see the
  "Parallel PRs → merge queue" bullet in `workflow.md`.
  **Panel sizing by risk (R7):** low-risk work (docs, manifests, probes, test registration) gets `code-reviewer` only, plus `test-quality-reviewer` when it adds real assertions; the full panel is for secrets, hooks, CI, merge gates and third-party code ingestion. Related train members are reviewed in one panel dispatch with a verdict per member, not one panel each; the integration PR's final `/pr-open` still runs the full tier panel as the backstop.
- **test-designer** — coverage map (flow/state diagrams + checklist) BEFORE tests: `test-designer`.
- **skill-author** — creating or editing a skill? Follow the **skill-quality checklist** in
  `skill-creator` — scripts for deterministic steps · a running gotchas list · a pass/fail verify
  step · minimum-viable-model + `context:fork` · **AskUserQuestion** for clarifying Qs (one at a time).
  A skill SHOULD (advisory, no hard gate): declare a min-viable `model:` when its work is
  grunt/deterministic rather than judgment-heavy, prefer a script over prose for any fixed
  procedure, keep a running `## Gotchas` section, and end with an explicit pass/fail verdict step
  where the skill has a real success/failure outcome. `model:`/`context:`/`effort:` are
  Claude-Code-only frontmatter — don't add them to a skill meant to be uploaded via the
  Agent-Skills spec (claude.ai / Skills API), which hard-fails on unrecognized fields. Re-check
  this periodically with `/skill-audit` — it scans `.claude/skills/**/SKILL.md` and
  proposes per-skill rows for a human to approve/decline; it never auto-applies. Two complementary
  review axes, no overlap: `skill-audit` = cost/structure hygiene (a deterministic scan);
  `/skill-reinvent <skill-name>` = strategy (blind-rederives a skill's approach from scratch and
  diffs it against the current method — surfaces a stale approach a structural scan can't catch).
  Both advisory-only, both apply through `writing-skills`.
- **test-writer** — real tests in the repo's framework: `playwright-tester` / the `frontend-testing`
  + `vitest-best-practices` skills / pytest. Each test must be able to fail.
- **browser-tester** — run tests against the *running* app on the worktree's port: `playwright-tester`
  + the `webapp-testing` skill. Test-auth contract = three inputs: `BASE_URL=http://localhost:$PORT`
  (runner-exported), creds in git-ignored `.env.test` (+ `TEST_AUTH_MODE`), and a seeded user via
  `npm run seed:test` (idempotent, Admin-API, localhost-only). **Hold the per-repo test lock**: run the
  suite via `bin/test-lock -- <cmd>` so two automated runs can't collide on the shared DB
  (a contended run prints the holder and exits 75 — use `bin/test-lock --wait -- <cmd>` to queue FIFO
  instead of retrying). Missing `.env.test` → fail loud; never test unauthenticated.
  A builder/fix round runs the **affected slice** for speed (the runner's affected-selection mode if it has one, otherwise the touched test files); the
  full suite stays the one-full-suite-per-PR gate (a single local run under `bin/test-lock`), never replaced by a subset.

## Fork ≠ free — construct a focused prompt, don't re-send session state

Spawning a subagent isn't a discount: the subagent processes whatever context it's given from
scratch, and its RETURN re-enters the primary session's own context (the `context_nudge`
hook WARNs when a subagent's return exceeds ~4k estimated tokens). No hook can
see or shrink the SPAWN prompt itself, so this is a discipline the delegator owns, not something
machine-enforced:

- **Construct EXACTLY what the subagent needs** — "review these 3 files for X," not the whole
  session's back-and-forth re-sent as context. Pair with `dispatching-parallel-agents`
  for the fan-out shape once the prompt itself is scoped tight.
- **Delegating a DELETE/RENAME refactor? Name the P6 doc pass explicitly.** A subagent told only
  "delete X, repoint the consumers" treats docs as out of scope and leaves live docs, the sanctioned
  skills, and `plugin.json` descriptions pointing at the deleted name — an actively-wrong instruction a
  reviewer then flags as CHANGES. Instruct it to repoint every **live** doc/skill/`plugin.json`
  off the deleted name (leaving historical `docs/superpowers/{specs,plans}` as point-in-time records) AND
  to `grep`-clean-verify before opening its PR.
- **Ask for a summary back, not a dump.** A subagent's job is to do the wide/deep work in its OWN
  context and return the distilled result — not to hand the primary session everything it read.
  `context_nudge` flags an oversized return after the fact; the cheaper fix is prompting for a
  summary up front.

## Gating agents write durable results (idle-safe)

An agent whose return GATES the next step (a reviewer whose verdict unblocks a merge, a researcher whose
answer drives a decision) is dispatched idle-safe — a hung agent must never freeze the leader:

- **Durable result:** give it a unique report-file path (`<scratchpad>/agent-<label>.md`); it writes its
  result there incrementally and returns ONLY a one-line summary + that path. A mid-hang agent still leaves
  a readable partial.
- **Leader liveness:** treat the agent as HUNG when ≥2 consecutive idle notifications arrive AND the
  report-file's mtime has not changed since the last check (a growing file = still working — keep waiting).
- **On hung:** `TaskStop` it, read the partial report, re-ask AT MOST once; if still nothing, fall back — do
  the work inline or re-dispatch ONE fresh agent. Never re-ask a hung agent more than once.
- **Scope:** gating agents only; fire-and-forget advisory agents you don't block on are exempt.

Honest limit: no hook can enforce this — a tool-call guard can't observe a dispatched Agent's liveness. This
is a convention, not a mechanism.

## Model routing (pinned exact IDs · bare aliases banned)
**Every agent pins an EXACT model ID** in its `model:` frontmatter — the frontmatter is the single
source of truth, and this table must match it (`tests/test_model_routing.sh` MR-07 fails on drift).
Session default: `claude-opus-4-8`.

| Model | Agents | Why |
|---|---|---|
| `claude-sonnet-5` | `crew-coordinator`, `crew-implementer`, `critical-thinking` | The roles that steer and build. Sonnet is fast and 2–3× cheaper for everyday agentic coding, and every build it produces is still checked by the tests, the mutation proof and the Opus 4.8 review panel. |
| `claude-opus-4-8` | `code-reviewer`, `silent-failure-hunter`, `security-reviewer`, `type-design-analyzer`, `playwright-tester`, `test-designer`, `test-quality-reviewer`, `pr-test-analyzer`, `code-simplifier`, `web-researcher` | Review, test and research work that runs many times per PR and is cross-checked by the other lenses, the suite and the mutation proof. |
| `claude-haiku-4-5-20251001` | `codebase-explorer`, `comment-analyzer`, `docs-impact-agent` | Light read-only / mechanical. |

Light work outside agents (issue triage in `github-solve-issues` Stage 1, pre-classified trivial
edits) also goes to `claude-haiku-4-5-20251001`.

⚠ **Bare aliases are banned.** Never use `opus` / `sonnet` / `haiku` / `fable` in a `model:`
frontmatter field or a `--model` flag — an alias floats to the newest generation, so the model
changes under you without a diff. Enforced by `tests/test_model_routing.sh`. **This ban also covers the
Agent/Task tool's runtime `model:` param (the third leak surface, alongside frontmatter and `--model`)
— and there OMITTING it is the ONLY safe form: that param's enum accepts only the bare aliases and
rejects exact IDs, so passing ANY value is a floating alias. Never pass it; leave `model` unset so the
agent def's pinned ID wins, and choose the model by choosing the agent type.** (The `pre_tool_use`
guard blocks a bare alias on that param; it OVERRIDES any skill that says "always specify the model".)

## When to delegate (the model judges)
- **Substantial research** (multi-file / multi-source) → a researcher subagent. A **one-off lookup
  → inline `WebSearch`** — don't spawn an agent for a single web query.
- **`/deep-research` is the HEAVYWEIGHT** — reserve it for genuinely deep, multi-source,
  fact-checked questions. A how-to / single-topic question → one `web-researcher` subagent or inline.
- **Before a commit or PR**, or a risky diff → an auditor.
- **A net-new feature with real flows/state** → test-designer → (human review) → test-writer →
  browser-tester. Skip the pipeline for trivial changes.

## How to delegate (prefer in-process)
- **Test cadence in every implementer brief.** Say it in the spawn prompt: run only the touched
  test files during BUILD and fix rounds; a full suite per PR for a tier-2 PR (tier-0/1 gates on
  the affected slice), as a single local run under
  `bin/test-lock` at the final synced head (there is no CI). A delegated build that re-runs the full locked suite per fix
  queues every other worktree behind it (`suite_overrun_nudge` WARNs past 3 runs/session).
- **Default to in-process subagents (Agent/Task tool):** their result returns into your transcript
  (so it's visible over `/rc`), no extra tmux pane, no experimental flag. Do **not** spawn a separate
  `claude` in a tmux window for a sub-task.
- **Forming a crew — one mode: in-process teammates.** Spawn named teammates via the **Agent
  tool** (a per-session implicit team forms on first spawn; coordinate with `SendMessage`; results
  return to the leader's transcript). The `teammate_idle` hook (TeammateIdle event) keeps a
  teammate working while it still owns tasks. **Scaling past one implementer:** count writers, not
  agents — read-only auditors/researchers need no worktree; every extra implementer gets its OWN
  native worktree (Agent `isolation: worktree` — the `worktree_create` hook provisions
  fetch·env·PORT·setup), one writer per worktree.
- **Builder brief — every implementer dispatch carries this checklist**, and the implementer
  self-checks it before reporting ready:
  - a fail-open or degraded path is visible on **stdout** (a hook's `systemMessage`), not only on
    stderr, which an exit-0 hook never shows;
  - a change to a twinned unit (e.g. a py + node hook pair) lands in **both** twins, and every new
    test runs on both and is shown failing **before** the fix;
  - the repo's deterministic doc checks (docs-drift / inventory-count tests) are part of the
    targeted run;
  - a builder's targeted run includes every test that reads a doc it edits — find them with
    `grep -rln '<doc path>' tests/`;
  - docs that describe the changed behaviour are updated in the same PR;
  - a stale-base block means sync, don't bypass: `git stash push -u -m <tag>` → `git merge
    origin/main` (one sync commit, no bypass) → `git stash apply <sha>` → commit normally. The
    rebase-check bypass token is honoured ONLY on a merge commit, never on a normal commit; when
    unsure, ask the coordinator.
  - on a **tier-2** PR, the builder runs its own tier-2 self-check (`silent-failure-hunter` +
    `security-reviewer` on `origin/main...HEAD`, findings fixed, targeted tests re-run) before
    opening the PR, and names each lens's verdict + finding count under a `## Self-check` section
    in the PR body (R1; tier 0/1 skip this).
- **Status cadence.** A coordinator reports to the user only on a state change — merged, blocked or
  needs a decision, or a full suite red; an agent hand-back that changes nothing user-visible gets no
  reply turn of its own.
- **A plan that will be fanned out declares its parallel batches.** Worktree isolation prevents
  runtime overwrites, but the *plan* must still say which task groups may run at once so a coordinator
  fans out safely and merges stay clean. A plan with ≥2 tasks carries a **Mermaid task DAG** (edges =
  depends-on) and a machine-parseable **`## Parallelization`** callout listing batches by task id:

  ```
  ## Parallelization
  - Batch 1: T1, T3
  - Batch 2: T2
  ```

  Tasks in the same batch MUST own **disjoint files** — two same-batch tasks must not share any file
  path in their **Files:** blocks (Create/Modify/Add/Delete/Edit/Test or bare path bullets).
  Tasks left out of every batch are sequential. The `parallel_gate` hook enforces
  this at plan-commit time (BLOCK on overlap or a missing callout; bypass `WORKFLOW:no-parallel`);
  `parallel_nudge` WARNs at write time, incl. the plan-mode path a commit gate can't reach. Cross-plan
  overlap is out of scope — two concurrent plans each run in their own worktree, so collisions surface
  at merge, not runtime.

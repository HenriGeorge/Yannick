# Enforcement — what is hard-gated

Last updated: 2026-10-19 08:45

The canonical Design→Code→Prove workflow (`rules/workflow.md` Adherence) is rule-mandated end to
end, but only part of it is machine-enforced — a hook can't detect "did you run skill X," only
whether a **durable artifact** X produces exists or a **tool-event** appears. Enforcement is
tiered: **BLOCK** where a clean artifact exists and false positives are rare, **WARN** (a
non-blocking notice) where the trigger is fuzzy but the discipline still matters. Every BLOCK gate
carries a `WORKFLOW:no-*` bypass token for the genuinely-trivial case; WARN gates are advisory-only
(no bypass needed — they never block).

> [`../FIELD-GUIDE.md`](../FIELD-GUIDE.md)'s "The gate lane" section maps this to the two proof
> modes — command-verified gates (code) + rendered-pixel approval (design) — the "how we decide
> done" framing this roster sits under.

Per-hook mechanics (wiring, module layout, classification detail, test parity) live in
[`HOOKS.md`](HOOKS.md) — this doc states policy only: what is gated, BLOCK vs WARN, the bypass
token, and the PR merge axes.

## Gate roster

The review panel size per PR (tier 0/1/2) is decided by `bin/pr-tier` from the changed paths; the
merge-time axes below apply at every tier unless waived.

| Gate (workflow step enforced) | Hook/guard | Event | BLOCK/WARN | Bypass |
|---|---|---|---|---|
| grill-me (design+plan pressure-test) | `grill` | PreToolUse (`git commit`) | BLOCK | `WORKFLOW:no-grill` |
| plan-time interview (GATE-1 Q&A record) | `plan_interview` | PreToolUse (`git commit`) | WARN (#1427 — was BLOCK; 135 of 136 fires were bypassed, so it now injects the note on the allow path) | `WORKFLOW:no-interview` (or `WORKFLOW:lane-medium`) silences the note |
| design-before-code (spec/plan exists) | `pr_gate` (create check) | PreToolUse (`gh pr create`) | BLOCK | `WORKFLOW:no-design` |
| declare parallel batches | `parallel` | PreToolUse (`git commit`) | BLOCK | `WORKFLOW:no-parallel` |
| test-driven-development (red-first) | `tdd` | PreToolUse (`git commit`) | BLOCK | `WORKFLOW:no-tdd` |
| GATE-0 stale-base (behind + overlap) | `stale_base` | PreToolUse (`git commit`) | BLOCK | `WORKFLOW:no-rebase-check` (merge-only) |
| isolate-then-prime first action | `session_prime` | PreToolUse (`Edit`/`Write`/`NotebookEdit`, `git commit`/`push`, `gh pr create`/`merge`) | BLOCK — a docs-only mutation is exempt (#1427: an `Edit`/`Write` of a tier-0 `.md` or `docs/lessons*.md`, or a single-segment `git commit -m` (no `-a`/`--include`/pathspec/`-C`, nothing chained before or after) whose staged set is all such paths; `push`/`gh pr` still gate) | `WORKFLOW:no-worktree` · `WORKFLOW:no-prime` · `PRIME_GATE=0` |
| no leftover artifacts (merge markers / commit-blocking sentinel / `.DS_Store`) | `nocommit_guard` | PreToolUse (`git commit`) | BLOCK | `WORKFLOW:no-nocommit` |
| conventional commits (H2 grammar) | `conventional_commit` | PreToolUse (`git commit`) | BLOCK | none (fix the message; only `-m` subjects are inspected) |
| destructive-op guard (H7) | `danger` | PreToolUse (`Bash`\|`PowerShell`) | BLOCK | `CT_ALLOW_DANGER=1` |
| protected-branch guard (H8, no direct commit/push to main) | `protected_branch` | PreToolUse (`Bash`) | BLOCK | `CT_ALLOW_PROTECTED=1` |
| secret scan — staged diff (H3) | `secret_scan` | PreToolUse (`git commit`) | BLOCK | `CT_ALLOW_SECRETS=1` |
| secret-file staging by name (H10) | `secret_file` | PreToolUse (`git add`/`commit`) | BLOCK | `CT_ALLOW_SECRET_FILE=1` |
| secret-read guard (H11) | `secret_read` | PreToolUse (`Read`, `Bash`) | BLOCK | `CT_ALLOW_SECRET_READ=1` |
| read-only paths (`rm -rf` / Write/Edit) | `readonly` | PreToolUse (`Bash`, `Write`/`Edit`) | BLOCK | none |
| shared-checkout guard (R8) | `shared_checkout` | PreToolUse (`Bash`) | BLOCK | `CT_ALLOW_SHARED=1` |
| plugin-source / plugin-cache edit guards | `vendor_owned` / `template_owned` / `plugin_cache` | PreToolUse (`Write`/`Edit`/`NotebookEdit` + `git commit`) | BLOCK | `CT_ALLOW_TEMPLATE_EDIT=1` / `CT_ALLOW_PLUGIN_EDIT=1` |
| model allow-list (pinned IDs only) | `model` | PreToolUse (`Agent`/`Task` dispatch) | BLOCK | none (architectural) |
| suite serialization (per-repo lock) | `test_lock` | PreToolUse (`Bash`) | BLOCK | run via `bin/test-lock --wait -- <cmd>` |
| PR-merge safety (CI / mergeable / head-match) | `pr_gate` (merge checks) | PreToolUse (`gh pr merge`) | BLOCK | `WORKFLOW:force-merge` |
| PR-merge marker axes (review / security / test-quality / suite) | `pr_gate` (merge checks) | PreToolUse (`gh pr merge`) | BLOCK | `WORKFLOW:no-review` / `no-security` / `no-test-quality` / `no-suite` / `lane-medium` — see merge axes below |
| rules-load + concurrent-session checks | `session_start` / `rules_refresh` | SessionStart | WARN | — |
| worktree provisioning (fetch · env carry-in · PORT · setup) | `worktree_create` | WorktreeCreate | WARN (provision) | — |
| worktree teardown backup | `worktree_remove` | WorktreeRemove | non-gating | — |
| teammate keep-working nudge | `teammate_idle` | TeammateIdle | WARN (inject) | — |

## BLOCK vs WARN

- **BLOCK** — the hook emits `hookSpecificOutput.permissionDecision: "deny"` (plus the legacy
  `decision: "block"` field) with a stderr reason, and `exit 2`. Stop hooks block via the JSON
  `decision` field alone, with `exit 0`.
- **WARN** — the hook prints `{"systemMessage": "..."}` with no `decision` field and always
  `exit 0` — it injects context but never blocks.
- **Fail-open, always.** Malformed stdin, a missing transcript, `git`/`gh` offline or
  unauthenticated, or any unexpected exception → silent `exit 0`, never a block. A gate must never
  wedge a legitimate session over its own bug or a flaky external command.
- Command-detection mechanics (global-flag tolerance, command-vs-mention, quote/heredoc handling)
  are hook internals — see [`HOOKS.md`](HOOKS.md) and [`hook-wiring/README.md`](hook-wiring/README.md).

## Known limitations

- **`_resolve_trunk` can return `None` on a non-standard trunk with no tracking signal at all** —
  no `origin/HEAD`, no `main`/`master`, no upstream (`@{u}`), no `init.defaultBranch`. The
  design-before-code check (`pr_gate.py:247`) then fails OPEN on an unknown trunk. Accepted
  residual: no further signal short of asking the operator.
- **H12 (rules-load check) only flags MISSING/IGNORED imports it can see.** `rules_refresh`
  (`session_start.py:279`) re-checks the MISSING case on every `startup` even when heal is skipped
  (dirty tree, non-plugin import), but it still reads `CLAUDE.md`'s own `@import` lines — a rule
  loaded a different way (not via `@.claude/rules/*.md`) is outside its scan.
- **The auto-review-on-pr merge gate is Bash-only.** It fires on `gh pr merge` run as a shell
  command; a merge via the GitHub web UI or app bypasses every `pr_gate` check — no PreToolUse hook
  can intercept an action that never runs as a local tool call. A branch-protection rule on the
  GitHub side is the complement, out of scope here.
- **Marker gates prove PRESENCE + head-binding, not authorship.** A `code-review:APPROVE@<sha>` (or
  attended `WAIVED`) can be self-posted by the PR author — no author-binding is enforced.
- **H2/H8/H7 are command-STRING heuristics, not a shell parser.** A quoted subcommand
  (`git "commit" -m …`) still hides from H2; `bash -c "…"` / `eval "…"` wrapper forms go
  undetected by design (the price of killing prose false-positives). H7's destructive-op strip closes the quoted/escaped case for the
  working-tree destroyers; an unnamed git global option taking a separate argument can still slip
  past its shape-match.

## PR-gate merge axes (canonical)

This is the single canonical home for the `pr_gate` merge-check facts (`gh pr merge`). Every other
doc that touches this topic (`rules/workflow.md`, `rules/verify-workflow.md`,
`rules/agent-delegation.md`, `docs/MANUAL.md`) states a one-line summary and links
here — this section is the source of truth a drift test (`tests/test_pr_gate_docs_truth.sh`)
checks against `pr_gate.py` directly, so it must stay verbatim-accurate.

- **Marker form.** Every axis marker is an HTML comment:
  `<!-- <prefix>:<VERDICT>@<40-hex-headRefOid> -->` — a bare (non-comment) marker line, or one with
  no sha or an abbreviated sha, is rejected (the gate asks for the exact form to post).
- **Prefixes + accepted verdicts.**
  - `code-review` → needs `APPROVE` (a genuine human GitHub review, `state: APPROVED`, on the
    current head also satisfies it).
  - `security-review` / `test-quality` / `suite` → each needs `PASS` **or** `WAIVED`. A `WAIVED`
    with NO `reason=` is accepted as an attended human risk-acceptance (honored on goodwill, not
    machine-checked). When a `reason=` IS present it IS machine-validated: `reason=docs-only` (any
    axis) and test-quality's `reason=no-testable-behavior` are checked against the PR's actual
    changed files and will themselves BLOCK if the files don't match; any other `reason=` value
    blocks as unrecognized.
- **`suite` axis scope.** Evaluated only where CI is **not** required — where CI is required, the
  CI axis itself owns regression and `suite` stays inert.
- **Fail-open / fail-closed split.** The WHOLE gate fails **open** (nothing checked, but visibly —
  a stdout `systemMessage`) when `gh pr view` can't read the PR at all. Once the PR IS readable,
  the code-review, security and test-quality axes fail **closed** on a missing/invalid marker
  (code-review's only looseness is an alternate satisfaction path — a native GitHub APPROVED
  review at the current head also counts); the `suite` axis fails **closed** the same way where
  CI is not required. The mergeable check fails open by absence. CI fails open by absence only
  where CI is not required; where the base requires it (or the requirement is undeterminable) an
  empty/missing `tests` check fails **CLOSED** (opt out with `REQUIRE_CI=0`). The head-match check
  fails **CLOSED** when `--match-head-commit` is missing or mismatched. CI, mergeable and
  head-match are all bypassable via `WORKFLOW:force-merge`.
- **Bypass tokens.** `WORKFLOW:force-merge` (CI/mergeable/head-match) · `WORKFLOW:no-review`
  (code-review — **not** `no-code-review`) · `WORKFLOW:no-security` · `WORKFLOW:no-test-quality` ·
  `WORKFLOW:no-suite` — each axis needs its own token; none substitutes for another.
  `WORKFLOW:lane-medium` is the **medium-lane** alias — ONE token that waives all four marker axes
  (code-review + security + test-quality + suite) at once, so a medium-lane PR merges without the
  full panel. It does **not** waive CI / mergeable / head-match (those stay under
  `WORKFLOW:force-merge`). Commit-side it also implies `WORKFLOW:no-interview` (silences the
  `plan_interview` note).
- **Head binding.** `--match-head-commit <40-hex-headRefOid>` is required on the merge command
  itself, closing the review→merge race (a push between review and merge invalidates a marker from
  an older sha).
- **`grill` is commit-time**, not part of `pr_gate`'s merge check — it blocks committing a
  spec/plan/ADR with an empty `## Grill findings` section; the plan-mode path (outside any project
  git repo) is not reachable by this commit-time block.

## See also

[`HOOKS.md`](HOOKS.md) (per-hook wiring, module layout, classification detail) ·
[`hook-wiring/README.md`](hook-wiring/README.md) (the enforcement-vs-instruction boundary) ·
`rules/workflow.md` Adherence (the commitments this roster machine-checks a subset of) ·
`tests/test_grill_gate.sh` / `tests/test_pr_gate.sh` (the behavior tests) ·
`tests/test_hook_wiring_merge.sh` (wiring parity) · `verify-adversarial` (the on-demand
adversarial re-check — not a gate).

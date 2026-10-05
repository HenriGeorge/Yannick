# Engineering conventions (R4–R10)

Last updated: 2026-10-05 13:03

Three baseline engineering habits that don't fit `workflow.md`'s phase spine but apply at every
phase where they're relevant. None of these are deterministically checkable at a tool call (see
the hook layer's rules-vs-hooks boundary test) — they're judgment calls a careful agent makes, not something a
hook can hard-block.

## R4 — Prefer editing over creating

Before writing a new file, check whether an existing one already owns this concern. A second
`utils.ts`, a parallel `types/` directory, a duplicate config file — these fragment a codebase and
create "which one is canonical?" confusion for the next person (human or agent) who touches it.

- Grep/glob for existing files that plausibly already cover the thing you're about to write before
  creating a new one. `context-map` (this repo's file-discovery skill) is the tool for this.
- Extending an existing module's surface (a new exported function, a new case in a switch, a new
  route in an existing router file) beats a new file that duplicates the module's purpose.
- A genuinely new concern *does* warrant a new file — this isn't "never create," it's "check
  first." The tell: if you're about to write something that could plausibly have gone in a file
  you already have open, look there first.
- Never create documentation files unless the user explicitly asked for one (`CLAUDE.md` project
  instructions already state this for `*.md`/README files specifically — this generalizes it: the
  same "did they ask for this artifact" check applies to code files too).

## R5 — Justify new dependencies

A new package is a standing cost: supply-chain surface, a version to keep patched, a transitive
tree the next audit has to reason about, and (for a template like this repo) a dependency every
scaffolded project inherits.

- Before adding a dependency, check whether the standard library or an already-present dependency
  already does this. A one-off string-manipulation helper doesn't need a package; a well-tested
  crypto primitive almost always should use one rather than hand-rolling it — the tradeoff runs
  BOTH directions, weigh it, don't default to either extreme.
- State the reason in the commit/PR, not just the dependency name — "why this one, why now" beats
  a bare `package.json` diff. A reviewer (human or `code-reviewer`) shouldn't have to guess.
- Prefer a dependency that's actively maintained, has a reasonable install-size footprint for what
  it's used for, and doesn't itself pull in a large transitive tree for a small piece of
  functionality.
- This project (`claude_template`) in particular: `setup.sh`/hooks are deliberately dependency-free
  (stdlib-only Python, Node core modules only) — see the `# dependencies = []` header on the
  runtime hooks (`hooks/*.py`) — because every scaffolded project inherits whatever the template hooks need.
  A new hook dependency isn't a "just this once," it's a cost on every future scaffold.
  - RTK is the deliberate exception, and consistent with this rule: it defaults **ON** at scaffold
    yet adds **no hook/runtime dependency** — it's an external CLI the
    user installs separately, instruction-based (a `CLAUDE.md` prefix block, no `PreToolUse` hook),
    telemetry OFF, and the H1–H10 guards still fire on its `rtk `-prefixed forms
    (`tests/test_rtk_guard_safety.sh`). A missing `rtk` binary degrades gracefully. So the
    "every scaffold inherits the cost" concern doesn't bite: the template ships zero new code for it.
    Auto-rewrite is available **opt-in** via rtk's own `-g` hook (`RTK_HOOK=1` at scaffold) — still
    not a template-authored hook; the default stays instruction-only because rtk's rewrite collides
    with the worktree-isolation git guard (see the `claude-template-core` plugin's `docs/RTK.md`
    and the rtk-rewrite guard-collision lessons in `docs/lessons.md`). A `rtk_nudge`
    PostToolUse hook makes the instruction-mode prefix habit stick (WARNs when a known-RTK command
    runs raw; stands down under `.rtk/hook-mode`).

## R6 — Security basics

Baseline hygiene that applies regardless of stack or profile:

- **No secrets in code — enforced by H3 (staged-diff secret scan) + H10 (secret-file staging).** Use
  env vars / a secrets manager / a gitignored `.env`; the hooks are a
  backstop, not a substitute for not writing the secret.
- **Validate/sanitize external input.** Anything crossing a trust boundary — a request body, a
  query param, a file upload, an env var sourced from outside your own deploy config — gets
  validated before use, not trusted implicitly. This includes output encoding at the point of use
  (SQL params, not string-concatenated queries; HTML-escaped interpolation, not raw string
  insertion) — see `/security-review` for the deeper pass.
- **Least-privilege tokens.** A token/credential should carry the minimum scope the task needs —
  a read-only DB user for a reporting job, not the admin credential; a repo-scoped GitHub token,
  not an org-wide one. When creating a new credential, ask "what's the narrowest scope that still
  works" before reaching for the broadest one that's convenient.

## R7 — Avoid unnecessary work (Ponytail)

Do what was asked; resist the pull to do more. Before adding, ask "was this requested, and does
it serve the current goal?" Concrete failure modes to stop yourself on:

- Building features/options nobody asked for; speculative abstraction for a second use case that
  doesn't exist yet; gold-plating a working solution.
- Refactoring beyond the change's scope; adding a new dep or file when an existing one suffices
  (that's R4/R5 — this is the general habit behind them).
- Patching only the one callsite the ticket names instead of the shared root. Fix the root cause
  across **ALL sibling callsites** — `grep` every caller first; one guard in the shared function is
  a smaller diff than a guard in each caller, and **two modules computing "the same" constant is a
  latent bug, not two independent facts** — grep before trusting either.

Ship the smallest thing that fully satisfies the request. Pairs with `lean-output.md` (Caveman) —
Ponytail cuts unnecessary *work*, Caveman cuts unnecessary *words*. See also: brainstorming's
"YAGNI ruthlessly."

Two self-checks that keep this honest:
- **The overcomplication check:** before calling a change done, ask *"would a senior engineer say
  this is overcomplicated?"* If yes, rewrite it smaller — if 200 lines could be 50, it's the 50.
- **Make success verifiable, per step:** for a multi-step task, state a brief numbered plan where
  each step carries its own check — `1. <step> → verify: <check>`. Strong, checkable criteria let
  you loop to done independently; a weak "make it work" forces constant re-clarification.

## R8 — Cross-repo git uses `git -C <abs-path>`, never a leading `cd`

A leading `cd <path>` in a compound command mis-resolves under the auto-mode classifier — the git
that follows can silently target the invoking checkout (`claude_template@main`) instead of the intended
repo, a near-miss that has rewritten the wrong tree. Address a repo by absolute path:
`git -C /abs/path <cmd>`, one repo per command. Never `cd X && git …` for cross-repo/worktree work.

In a **worktree-isolated session** the harness refuses any `git`/`gh`/`bash` command it can't verify
stays inside the worktree — a compound/chained op, an env-prefixed git, or a `gh` whose BODY text
contains a literal `git …` string. Form each as a **single, plain, unchained** command run from the
worktree, and move any `gh` PR/issue body to a file (`Write` + `--body-file`) instead of an inline
heredoc. Splitting a refused compound into separate plain commands is the fix, not a bypass.

## R9 — Git hygiene for agent commits (chains, gates, squash-merge)

Deterministic commit-hook and merge behaviours that repeatedly bite agents. None are the code's
fault — they're how `git` + the gates actually behave.

- **A chained `git add && git commit` fails as a UNIT.** A commit rejected by a gate/hook (grill,
  interview, conventional-grammar) leaves the `add` done but **nothing committed** — deliverables sit
  uncommitted under a false "done". Two consequences:
  - **Use a single-line `-m`.** A multiline `-m` body trips the commit-msg conventional-grammar guard
    and kills the whole chain. Put a `WORKFLOW:no-*` bypass token in a **trailing `# comment`** on the
    commit command, never as a `gh`/git argument.
  - **When a commit gate reads the STAGED INDEX** (the grill/interview gates do), run `git add` as a
    **separate command BEFORE** `git commit` — a one-liner is evaluated by the PreToolUse gate before
    its own `add` has run, so the gate sees the pre-add blob and blocks on stale content.
- **Verify "merged/done" by CONTENT, not ancestry.** Squash-merge **severs commit ancestry**, so
  `git merge-base --is-ancestor <sha> origin/main` reports false for work that DID land. Confirm with
  `git log origin/main` showing the squash commit (or grep the merged content). A `git push` to an
  **already-merged branch succeeds silently** — "pushed to PR #N" is not evidence it reached `main`.
- **Before rebuilding a KEPT local branch, confirm the whole branch isn't already merged.** A branch
  you re-enter may have landed entirely (squash-merged under a different SHA) while its local commits
  linger — building on it redoes merged work (GATE-0). Check by CONTENT (`git log origin/main`, or
  `bin/pr-merge-recover` which verifies MERGED before cleaning up), never `--is-ancestor` (squash
  severs it). Fresh worktrees branched from `origin/main` sidestep this entirely — prefer them.

## R10 — Comment doctrine: WHY, not WHAT

A comment earns its place by explaining what the code can't say for itself — the *why* (the reason, the
constraint, the non-obvious tradeoff), never a restatement of *what* the line does. Keep every comment
accurate as the code changes, or delete it: a stale comment is worse than none, because the next reader
trusts it. No narration (`// loop over items`), no commented-out code left as a graveyard, no banner
noise. The test: if deleting the comment loses no information a competent reader couldn't get from the
code itself, it shouldn't exist. (`comment-analyzer` is the review-time backstop; this is the authoring
rule.)

## See also

the hook layer's enforcement-vs-instruction boundary (R6's secrets point is partially
backstopped by H3/H10, but the rule itself is the judgment call, the hook is the safety net) ·
the GATE-2 rule (its silent-failure check overlaps R6's "validate external input" — a swallowed
error on unvalidated input is a related failure mode) · `/security-review` (the deeper security
pass this rule is a baseline for, not a replacement for).

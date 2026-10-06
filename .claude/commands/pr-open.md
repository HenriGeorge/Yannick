---
description: Open a PR AND auto-run the P5 review panel (docs-impact included at tier ≥ 1) on the diff, then post one comment + the code-review verdict marker the merge-gate reads. The orchestration a hook cannot do.
argument-hint: [--full] [PR title] (blank title = derive from the branch's commits)
allowed-tools: Task, Bash(git status:*), Bash(git fetch:*), Bash(git rev-list:*), Bash(git log:*), Bash(git diff:*), Bash(git branch:*), Bash(git push:*), Bash(git merge-base:*), Bash(claude-template docs-drift:*), Bash(claude-template pr-tier:*), Bash(gh pr create:*), Bash(gh pr view:*), Bash(gh pr diff:*), Bash(gh pr comment:*)
---

# /pr-open — create the PR and dispatch the review panel (docs-impact included)

**Arguments (optional):** $ARGUMENTS — `--full` forces the full (tier-2) panel; the rest is the title.

**Why this command exists.** A PreToolUse hook is a deterministic guard — it *cannot invoke an agent
or skill* (the `claude-template-core` plugin (`docs/workflow/ENFORCEMENT.md`), `hooks/grill_nudge.py`). So the P5 REVIEW panel
(docs-impact included) is rule-mandated but model-driven, and gets skipped. `pr_gate.py` can only *nudge* at
create and *block* at merge. **This command IS the orchestration layer**: a slash command CAN spawn
agents, so it makes the panel + docs-impact fire on every PR — and writes the verdict marker that
`pr_gate`'s merge-block reads (`hooks/pr_gate.py` `_axis_status`), so a clean review clears the gate with no
manual `WORKFLOW:` token.

Run the phases in order. Never skip the tier's panel, and never pick a tier by eye — use `pr-tier`.
**This command is the only way to dispatch a review panel.** A hand-dispatched panel skips
docs-impact and the round bookkeeping below, so it is not a panel.

## Phase 0 — GATE-0 preflight
1. `git fetch origin` · confirm current branch ≠ `main`/`master`.
2. Tree clean (`git status --porcelain` empty) — if not, stop and tell the user to commit/stash.
3. Behind-count vs `origin/main` (`git rev-list --count HEAD..origin/main`); if behind, **sync** —
   this PR branch is pushed, so `git merge origin/main` (one merge commit; never a force-push, never
   `git pull`/`reset --hard`) — and re-run the test files the sync touched; the PR's one full
   suite runs at the final synced head (step 5).
4. Push the branch (`git push -u origin HEAD`) if it has unpushed commits.
5. **The full suite is local, tier-2 only (R4).** Run a full suite per PR for a tier-2 PR (logic / gated paths), at the final synced head. There is no CI: a single local full-suite run under `bin/test-lock` at the final synced head is the PR's one full suite — a partial/affected subset, or a run on any other sha, does not count. Run it once under the lock (`bin/test-lock --wait [--timeout N] -- <test cmd>`, which queues FIFO) and read the count. For a **tier-0/1** PR the affected slice (plus the smoke floor) is the per-PR gate — no full run required unless the change touches the test runner or setup/install scripts (then a full run is mandatory regardless of tier)
   yourself. Fix rounds after that re-run only the touched test files, unless they change the test
   runner or setup scripts. The panel (Phase 2) still runs regardless; this is
   the delegator's own fresh-evidence gate — the review panel's highest catch-rate is on exactly these small delegated/self-authored
   diffs the author's diff-read rubber-stamps (lessons #374/#396).

## Phase 1 — Create (or reuse) the PR
- Strip `--full` from `$ARGUMENTS`; the rest is the title.
- If the branch already has an open PR (`gh pr view --json number` succeeds), **reuse it** and skip
  `gh pr create`. This is the re-review path after a fix-up push.
- Otherwise `gh pr create` with the title (or derive a conventional title from the commits when
  blank), body summarizing the change + test evidence. This respects `pr_gate`'s create-BLOCK (a
  `feat/*` branch needs a spec/plan committed).
- Capture the PR number and the diff (`gh pr diff <n>`).

## Phase 1a — Tier-2 self-check (R1, builder-side — WARN only, never a block)
- Before a tier-2 PR is opened, the builder should have run `silent-failure-hunter` and
  `security-reviewer` on its own diff (`origin/main...HEAD`), fixed what they found, and re-run its
  targeted tests — the PR body then **runs its own tier-2 self-check** and carries a
  `## Self-check` section: one line per lens with its verdict and finding count (e.g.
  `silent-failure-hunter: PASS (2 fixed)`).
- **Tier 0/1 PRs skip the self-check** — never warn on those.
- If a tier-2 PR body **lacks `## Self-check`**, **WARN** (do not block) and name it in the PR
  comment. The round-1 panel (Phase 2) still runs in full regardless — the self-check only makes
  round 1 a confirmation, it is never a substitute for it.

## Phase 1b — Pick the review tier (deterministic, never by eye)
1. Whole PR: `claude-template pr-tier [--full] origin/main`. If its output has a second line
   `SPLIT: <files> files / <lines> lines > 30 / 1500` (R2 — generated files from
   `bin/lib/generated-paths.txt` never count), **surface it** to the user: split the PR into
   smaller ones, or, if it stays as one PR, write a `Size: <reason>` line in the PR body. Never a
   block.
2. If that says `tier=0`, use it. Otherwise, if the PR already has a `<!-- pr-open:tier=<N>@<sha> -->`
   comment from an earlier run AND `git merge-base --is-ancestor <sha> HEAD` succeeds (no force-push),
   re-run as a **delta**: `claude-template pr-tier --delta-from <sha>`. The delta is never tier 0 and
   is tier 2 only if it touches a tier-2 path or is large. Only a comment **this command posted on
   this PR** counts: integration-train member reviews are recorded with a `train-member:` marker,
   never `pr-open:tier`, so the first `/pr-open` on a train PR is always a full round 1.

   **Fix round (R6) — no panel re-dispatch on `Open:`.** A fix round does not re-dispatch the `Open:` lenses as a panel. Instead:
   - `code-reviewer` reviews the fix delta every round — it owns the head-bound verdict, and is
     always dispatched.
   - For every other lens still named on the previous comment's `Open:` line
     (`silent-failure-hunter`, `code-simplifier`, `comment-analyzer`), prove the finding fixed with
     a test shown RED on the pre-fix code and GREEN after the fix, instead of re-dispatching that
     lens. Record `finding → test → RED/GREEN` counts per lens in the PR comment.
   - **Exception:** a fix to a security finding in secrets or supply-chain code (env/secret
     handling, vendoring or cloning third-party code, auth) gets one `security-reviewer` re-check
     of that specific fix.
   - `Open:` missing, unparseable, or naming an unknown agent, or the previous tier marker unparseable → this isn't a confirmed fix round, so dispatch the full delta-tier panel. Only an explicit `Open: none` narrows the round to `code-reviewer` alone. (A force-push already fails the ancestor check above → full run.)
   - The delta tier is higher than the previous comment's tier → dispatch the full delta-tier panel.
   - A delta touching a **gated path** (`hooks/`, `bin/`, `.github/`, `hook-wiring/`, a path matching `_gate.`, `settings`, `hooks.json`, or `auth`) forces the full-diff treatment below instead of a delta review — any reviewing lens may also answer `NEEDS-FULL` itself to force it.
   - `docs-impact-agent` re-runs when the delta changes code or docs.

   **Gating lenses close the round (R3).** `security-reviewer` and `test-quality-reviewer` markers
   are bound to the head, so a lens skipped above has no verdict at this head. Once the round's
   results leave `Open: none`, each dispatches on the **delta diff**
   (`claude-template pr-tier --delta-from <sha>`'s interdiff) — unless the delta touches a gated
   path or the lens answered `NEEDS-FULL`, in which case it reviews the **full PR diff**
   (`origin/main...HEAD`) instead — and posts a normal verdict at the new head before Phase 4.
   **Give each delta-reviewing lens the full PR file list plus its own round-1 report**, so it can
   judge whether the delta is safe in context. While `Open:` is not `none`, those markers are
   omitted (the gate keeps blocking). Never copy an earlier verdict onto a new sha.

   **Mutation proof (test-quality).** A docs-only delta keeps the earlier mutation proof, re-cited
   with its head sha, plus the plan-named tests green at the new head. Any other delta needs a fresh mutation proof.
3. A non-zero exit or unparseable output means **tier 2**. Never pick a smaller panel on error.
4. Print `Tier <N> — <reason> — panel: <agents>` to the user, and put the same line in the PR comment.

| Tier | Dispatch (one message, concurrently) | security / test-quality markers |
|---|---|---|
| 0 docs-only | `code-reviewer` | `WAIVED@<headRefOid> reason=docs-only` (both) |
| 1 prose prompt-code (#1073 — pr-tier emits a `WAIVE: test-quality` line) | `code-reviewer` + `security-reviewer` + `docs-impact-agent` (NO `test-quality-reviewer`) | security from the reviewer; `test-quality:WAIVED@<headRefOid> reason=no-testable-behavior` |
| 1 low-risk (incl. a large markdown-only diff, #999) | `code-reviewer` + `security-reviewer` + `test-quality-reviewer` + `docs-impact-agent` | from the reviewers |
| 2 logic | the full Phase 2 panel + Phase 3 `docs-impact-agent` | from the reviewers |

**Prose prompt-code sub-case (#1073).** When `pr-tier`'s output carries a second line
`WAIVE: test-quality reason=no-testable-behavior` (prose-only `.md` under a plugin's
`commands/`/`agents/`/`rules/` or top-level `rules/` — prompt-code with no testable behavior), dispatch
the tier-1 panel **minus `test-quality-reviewer`** and post
`<!-- test-quality:WAIVED@<headRefOid> reason=no-testable-behavior -->` in its place. Security review
still runs (prompt-code can carry an injection/secret surface). `pr_gate` re-verifies the waiver against
the real file list — it holds only when every changed path is prose markdown — so never write
`reason=no-testable-behavior` by hand on a PR that touches code or a version-bump manifest.

`pr_gate` re-checks every `reason=docs-only` waiver against the PR's real file list. If one lands on a
PR that touches anything other than docs-only markdown, the merge blocks and the message names the
path. Never write `reason=docs-only` by hand on a tier-1 or tier-2 PR. `--full` always forces tier 2.
A docs-only **rename** still gets blocked: the gate sees it as `RENAMED`, and can't see the old path. So run `/pr-open --full` for any PR that renames or moves a file.

## Phase 2 — Dispatch the tier's panel CONCURRENTLY (one message, parallel agents)
Dispatch the agents the tier names. The full list below is the **tier-2** panel.
Spawn them on the PR diff **in a single message** (they hold no locks — run them together):
- **`code-reviewer`** (required — owns the code-review verdict word)
- **`silent-failure-hunter`** (required — may escalate)
- **`security-reviewer`** (required — owns the SEPARATE security verdict `PASS`/`FINDINGS`/`WAIVED`; the merge-gate fails CLOSED without a fresh `PASS`)
- **`test-quality-reviewer`** (required — owns the SEPARATE test-quality verdict `PASS`/`FINDINGS`/`WAIVED`; verifies the plan-named acceptance tests are green at head AND ≥1 is mutation-proven able to fail; the merge-gate fails CLOSED without a fresh `PASS`)
- **`code-simplifier`** (advisory)
- **`comment-analyzer`** (advisory; on a docs-only diff it reports "no applicable findings")

Scope each agent to the diff (`git diff origin/main...HEAD` or `gh pr diff <n>`), not the whole repo.
Ask each for a terse findings list, not a file dump. **Do NOT pass a `model:` param** — the agent
def's exact pinned ID wins (agent-delegation rule).

**Point every reviewer at the WORKTREE tree, never the primary checkout.** The panel agents are
read-only (Read/Grep/Glob, no shell), so their neighbor-reads resolve against whatever checkout they
land in — and a reviewer dispatched for a PR whose branch lives in a worktree will silently
Read/Grep/Glob the **primary checkout** (which sits on `origin/main`, NOT this PR's head) and report
false "change not found" / stale-content findings. When the PR branch is in a worktree (the usual
case), put in each reviewer's prompt: (1) the **worktree-absolute repo root**, with "Read/Grep/Glob
ONLY under this root"; (2) the primary checkout's absolute path, named as a **different, possibly-stale
tree — never read it**; and (3) for a small diff, the **full changed-file content pasted inline**, so
no neighbor read is needed at all (the only drift-proof option — use it whenever the diff is small
enough). A reviewer finding that reduces to "I couldn't find the change" is this drift, not a defect:
re-dispatch with the worktree root, don't act on it.

## Phase 3 — Dispatch docs-impact — tier ≥ 1, in the same message as the panel (tier 0 keeps only the `docs-drift` pre-pass)
- **Deterministic pre-pass (this repo):** run `claude-template docs-drift --since "$(git merge-base origin/main HEAD)"`
  — it reports, scoped to THIS diff only, doc→code stale-refs (a doc citing a `bin/x` or `<name>_gate`
  removed in this PR) and code surfaces added without a doc mention. **Advisory / non-blocking** — fold
  any findings into the docs section of the one comment below; it never sets a verdict marker. Skip it
  in a scaffolded project (it targets this template's own bash/py/plugin layout).
- Spawn **`docs-impact-agent`** on the same diff: which docs did this change make STALE? Missing entries
  for new user-facing features? It's advisory (never edits) — collect its findings. It also flags stale
  **Mermaid diagrams** (a `mermaid` block depicting a flow the change altered).

## Phase 4 — Synthesize → one comment + the verdict marker
- Post **exactly one** PR comment (`gh pr comment <n>`) collecting the panel + docs-impact findings.
  The **verdict word comes from `code-reviewer` alone** (the advisory agents don't set it).
- Include **four** machine markers, each on its own line, so the merge-gate can read them — three
  per-round (code-review, security-review, test-quality) plus the fourth `suite` marker posted only
  where CI is absent and only at the final synced head (see below):
  - `<!-- code-review:APPROVE@<headRefOid> -->` (or `CHANGES` / `COMMENT`). APPROVE only when
    code-reviewer approved AND silent-failure-hunter did not escalate. `<headRefOid>` is the PR's
    CURRENT head sha, the full 40 chars, captured with `gh pr view <n> --json headRefOid`. The gate
    requires APPROVE with `@sha` == the current head. A bare marker (no `@sha`), an abbreviated sha,
    or a sha from an older commit all block.
  - `<!-- security-review:<VERDICT>@<headRefOid> -->` where `<VERDICT>` ∈ `PASS`/`FINDINGS`/`WAIVED`
    comes from **`security-reviewer` alone**, and `<headRefOid>` is the PR's CURRENT head sha,
    captured with `gh pr view <n> --json headRefOid`. The gate requires `PASS` (or attended `WAIVED`)
    with `@sha` == the current head — a later push invalidates the marker and forces a re-review.
  - `<!-- test-quality:PASS@<headRefOid> -->` (or `FINDINGS` / `WAIVED`) where the verdict comes from
    **`test-quality-reviewer` alone**, and `<headRefOid>` is the same PR CURRENT head sha from
    `gh pr view <n> --json headRefOid`. The gate requires `PASS` (or attended `WAIVED`) with `@sha` ==
    the current head — a later push invalidates the marker and forces a re-review, exactly like security.
  - **Tier 0 only** — no security or test-quality reviewer runs, so post exactly these two lines instead:
    - `<!-- security-review:WAIVED@<headRefOid> reason=docs-only -->`
    - `<!-- test-quality:WAIVED@<headRefOid> reason=docs-only -->`

    The gate accepts them only after it confirms every changed path is docs-only markdown.
  - **Prose prompt-code tier 1 (#1073) only** — `test-quality-reviewer` does not run (prose has no
    testable behavior), so post this line in place of a test-quality verdict (security still comes from
    the reviewer):
    - `<!-- test-quality:WAIVED@<headRefOid> reason=no-testable-behavior -->`

    The gate accepts it only after it confirms every changed path is prose markdown (docs, or
    prompt-code `.md` under `commands/`/`agents/`/`rules/`).
  - **Every tier** also posts `<!-- pr-open:tier=<N>@<headRefOid> -->`. It is advisory (Phase 1b's
    delta re-review reads it); the merge gate ignores it.
- **A fourth marker — `suite` — posts ONLY at the final synced head, not per fix-round push.** Where
  CI is absent, `pr_gate` also gates on a `suite` axis: once the merge-queue slot's one full-suite run
  (tier-2 full suite; tier-0/1 the affected-slice run that is that PR's required gate) is green at the
  **final synced head**, post `<!-- suite:PASS@<headRefOid> -->`; for a docs-only tier-0 PR post
  `<!-- suite:WAIVED@<headRefOid> reason=docs-only -->` instead. `<headRefOid>` is the PR's CURRENT
  head sha, the full 40 chars, captured with `gh pr view <n> --json headRefOid -q .headRefOid` — never
  abbreviated. Do not post this marker on an intermediate fix-round push; it belongs only to the sha
  the full suite actually ran against.
- **Fail loud on a missing required verdict — a missing verdict is NEVER a clean verdict.** If ANY
  REQUIRED agent **the tier dispatched** (`code-reviewer`, `silent-failure-hunter`, `security-reviewer`,
  `test-quality-reviewer`) errors, times out, or
  returns no findings at all, do **NOT** write the clean verdict for that axis. For code-review write
  `<!-- code-review:CHANGES@<headRefOid> -->` (or omit it); for security write
  `<!-- security-review:FINDINGS@<headRefOid> -->` (or omit the security marker entirely); for
  test-quality write `<!-- test-quality:FINDINGS@<headRefOid> -->` (or omit the test-quality marker
  entirely) — **never
  `PASS`** — so the fail-closed merge-gate keeps blocking. Name the agent that failed to return, in both
  the PR comment and your report. An advisory agent's silence is fine ("no applicable findings"); a
  required agent's silence is the opposite — treat it as an unfinished review, never as an approval.
  The same holds for a required axis **no agent reviewed at this head** (a gating lens a delta round
  skipped): omit its marker — never carry an earlier verdict forward to a new sha.
- Include two round-bookkeeping lines in the same comment:
  - `Open: <lens>, …` — every lens (the exact agent name, e.g. `silent-failure-hunter`) whose findings
    are still unresolved, **plus any required lens that errored, timed out or returned nothing**, or
    `Open: none`. `docs-impact-agent` is advisory and never goes on `Open:`; its findings are fixed in
    the next push. The next delta round reads this line (Phase 1b).
  - `Fix rounds: <N> (<lens>: <count>, …)` — `<N>` is the number of delta rounds so far (read the
    previous comment's line and add one; the first round is `Fix rounds: 0`; if an earlier `pr-open`
    comment exists but carries no such line, write `Fix rounds: unknown`), and each `<count>` is how
    many rounds that lens had findings. `/improve` mines these to see which lens drives fix rounds.
- **If the panel changed code** (e.g. you applied a fix), re-run VERIFY before merge and re-review.
- **One consolidated fix round (R5).** A fix round is dispatched only once every lens dispatched in the current round has returned AND the local full suite has concluded green on that head. A finding that arrives after the fix round was sent goes into the next round, never as a mid-round message to the builder.

## Phase 5 — Report
Give the user: the PR URL, the tier and its reason, the panel verdict, the security verdict, the test-quality verdict, any
docs-impact staleness (with fixes), and whether `gh pr merge` will now pass ALL THREE of the
review-BLOCK, the fail-closed security-BLOCK, and the fail-closed test-quality-BLOCK. Note any advisory
findings deferred to follow-up issues. On a delta round, name the lenses that did not see this delta. All four markers are bound to the head commit, so any later
push re-blocks the merge until `/pr-open` runs again on the new head; the `suite` marker is posted
only at the final synced head, not per fix-round push.

---

**Not a substitute for GATE-2.** This runs REVIEW (P5, docs-impact included); P6 DOCUMENT = the builder applies the docs-impact findings in the next push. The tests/typecheck/lint
(VERIFY/P4) must already be green *before* you open the PR — this command reviews a verified change, it
does not verify it.

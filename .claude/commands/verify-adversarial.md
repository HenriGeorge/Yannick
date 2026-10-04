---
description: Adversarial validation of the last change — assume the summary is wrong, prove every claim independently. Report-only, never fixes.
argument-hint: [ref, PR#, or path scope] (blank = last change — uncommitted diff, else HEAD vs origin/main merge-base)
allowed-tools: Read, Grep, Glob, Edit, Bash(bin/test-lock:*), Bash(git diff:*), Bash(git status:*), Bash(git log:*), Bash(git merge-base:*), Bash(git checkout -- *), Bash(cp:*), Bash(gh pr diff:*), Bash(gh pr view:*)
---

# Verify Adversarial

**Scope**: $ARGUMENTS

**Stance**: You are NOT the author's ally. Assume the change summary is wrong until this run
independently proves it right. Nothing carried over from the building session counts as evidence —
every claim gets fresh proof gathered here.

**Contract**: report-only. This command NEVER fixes what it finds, never commits, never edits
source — with exactly two permitted writes: the temporary mutation in Phase 4 (restored before
reporting) and unticking unproven checkboxes in Phase 5.

---

## Phase 0: DETECT STACK + SCOPE THE CHANGE

Resolve the test command, first rung that matches wins:

1. `TEST_CMD="…"` in `.claude/worktrees.conf` (the fleet's machine-readable source)
2. A `Test:` command in `CLAUDE.local.md`, then `CLAUDE.md` — **skip `{{TEST_CMD}}`-style
   unsubstituted placeholders**
3. Stack detection (as `/validate`): `pyproject.toml` → `uv run pytest` · `package.json` →
   `npm test` · `Cargo.toml` → `cargo test` · `go.mod` → `go test ./...`

If no rung resolves, record it and mark Phases 2 and 4 SKIPPED — do not guess a runner.

Resolve the change under review:

| Input | Diff |
|-------|------|
| (blank) | uncommitted diff if present, else `git diff $(git merge-base HEAD origin/main)..HEAD` |
| ref/branch | that ref against its merge-base with `origin/main` |
| PR# | `gh pr diff <n>` |
| path | last change restricted to that path |

Also collect the change's stated claims: the summary/plan/spec it shipped with (PR body, plan doc,
HANDOFF entry, commit messages). These are the claims under attack.

## Phase 1: SCOPE CHECK — every touched file maps to a requirement

For each file in the diff, name the requirement/claim that needed it. Flag:

- **Orphan edits** — touched files no stated requirement explains (scope creep, accident, or an
  unstated behavior change)
- **Ghost requirements** — stated requirements with NO corresponding change (claimed but not built)

## Phase 2: COLD SUITE RUN

Run the full suite fresh — never trust a pass-count quoted from the building session or HANDOFF.
This IS the PR's one full suite per PR: run it at the final synced head, and if the repo's CI check
is green for exactly that head, read its log instead of re-running locally:

```
bin/test-lock --wait --timeout 900 -- <TEST_CMD>
```

All suite and test runs in every phase go through `bin/test-lock --wait --timeout 900 -- ` (the
repo's `test_lock_enforce` hook denies bare runners; the lock spans all worktrees; `--wait` queues
FIFO behind a held lock). If the wait times out (exit 75), record the printed holder in the verdict
as SKIPPED(lock held by <holder>) and move on — never hand-roll a retry loop, never bypass.

Record: exact command, pass/fail/skip counts, duration, exit code.

## Phase 3: FALSE-TEST SWEEP

Read every test the change added or modified. A test is SUSPECT if any of:

- **No real assertion** — it runs code but asserts nothing, or asserts a tautology
  (`assert true`, asserting a value against itself)
- **Mock-only** — every collaborator is mocked and the assertion only checks mock wiring
  (that a mock was called), proving configuration, not behavior
- **Mocked SUT** — the system under test itself is patched/stubbed, so the test can never
  observe real behavior
- **Skipped/xfail** — marked skip, xfail, todo, or conditionally skipped in the environment the
  suite actually ran in (a "passing" suite that skipped the new tests proved nothing)
- **Expected-value copied from output** — the expectation reads like a captured actual (long
  opaque literals, snapshot updated in the same change, suspicious precision). Check: does the
  expected value trace to the requirement, or only to what the code emitted?

## Phase 4: MUTATION CHECK — can these tests actually fail?

For each added/modified test that survived Phase 3, verify it detects breakage of the code it
claims to cover:

1. **Dirty-file guard first**: check `git status --porcelain -- <file>` for the source file you
   are about to break. If it is clean, restore later with `git checkout -- <file>`. If it is
   dirty or untracked, `cp` it to the scratchpad first and restore by copying back —
   **never checkout over uncommitted work**.
2. Introduce ONE minimal breaking edit in the covered code path (invert a condition, off-by-one a
   boundary, drop a return).
3. Re-run JUST the covering test: `bin/test-lock --wait --timeout 900 -- <single-test invocation>` (not the full suite).
4. **Expect RED for the RIGHT reason.** Read the output, don't just read the exit code:
   - Test fails on its **assertion** → it genuinely covers the code: PASS.
   - Test still passes → it cannot fail: FAIL (a false test shipped as proof).
   - Exit 75 (lock contended) → NOT evidence either way: SKIPPED(lock held by <holder>), same
     rule as Phase 2 — never score a run that didn't happen.
   - Import/collection/syntax error rather than an assertion failure → NOT evidence the test
     detects the breakage: pick a different minimal mutation and retry once, else SKIPPED(bad
     mutation).
5. Restore immediately, explicit path only: `git checkout -- <file>` (or copy back from the
   scratchpad per step 1). NEVER a bare-dot checkout/restore — the repo's danger guard (H7)
   denies whole-tree forms, and explicit paths are the contract even where no guard runs.
6. Confirm restoration: `git status --porcelain -- <file>` matches its pre-mutation state, and
   `git diff -- <file>` shows no leftover mutation. **If confirmation fails, HALT loudly**: stop
   the phase, report exactly which file still carries the mutation and the restore command that
   failed, and mark the run BROKEN(restore failed — working tree dirty) — never continue to a
   clean-looking verdict over a corrupted tree.

Budget: if the change added many tests, mutate the highest-risk subset (new behavior > edge-case
tweaks) and record which were not mutation-checked.

## Phase 5: CHECKBOX AUDIT

Scan the change's plan/tasks artifacts (`docs/superpowers/plans/**`, TASKS/TODO/HANDOFF files
touched by the change, PR-body checklists you can edit) for `[x]` items. For each, ask: did THIS
run see evidence for it? If not, untick it (`[x]` → `[ ]`) and list it in the report. Unticking is
honest bookkeeping, not a fix — leave the underlying work alone.

## Phase 6: VERDICT

```markdown
## Adversarial verification — <change ref>

| Phase | Verdict | Evidence |
|-------|---------|----------|
| Scope check | PASS/FAIL | orphan edits / ghost requirements, file list |
| Cold suite | PASS/FAIL/SKIPPED(reason) | command + counts + exit code |
| False-test sweep | PASS/SUSPECT | per-test findings |
| Mutation check | PASS/FAIL/SKIPPED(reason) | per-test RED/no-RED + restore confirmed |
| Checkbox audit | CLEAN/UNTICKED(n) | list of unticked items |

**Verdict: VERIFIED / UNPROVEN / BROKEN**
```

- **VERIFIED** — every phase PASS/CLEAN with shown evidence.
- **UNPROVEN** — no hard failure, but SUSPECT tests, skipped phases, or unticked checkboxes mean
  the change's claims are not fully backed.
- **BROKEN** — cold suite fails, a mutation survived (a test that can't fail), or a ghost
  requirement (claimed-but-absent behavior).

Report findings only. Fixes are the author's next move, driven by this table — not this command's.

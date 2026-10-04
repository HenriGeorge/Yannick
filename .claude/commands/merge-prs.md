---
description: Review and merge open PRs — show status, checks, conflicts, and offer to merge clean ones
---

# Merge PRs

Review all open PRs and help merge the ones that are ready.

---

## Phase 1: LIST OPEN PRs

```bash
gh pr list --state open --json number,title,headRefName,author,createdAt,mergeable,statusCheckRollup,reviewDecision --limit 20
```

---

## Phase 2: ASSESS EACH PR

For each open PR, determine:

| Check | How |
|-------|-----|
| CI passing | `statusCheckRollup` field |
| No conflicts | `mergeable` field |
| Has approvals | `reviewDecision` field |
| Branch up to date | Compare base with head |

Categorize each PR:
- **Ready to merge**: CI green, no conflicts, approved or self-authored
- **Needs rebase**: Has conflicts with main
- **CI failing**: Tests or lint failing
- **Needs review**: No approval yet

---

## Phase 2.5: REVIEW (mandatory for every Ready-to-merge PR)

`pr_gate`'s merge-gate BLOCKS `gh pr merge` unless the PR's `code-review:APPROVE`,
`security-review:PASS` and `test-quality:PASS` markers are all bound to the PR's CURRENT head commit
(full 40-char sha) — or `WAIVED reason=docs-only` at tier 0 — or a genuine human GitHub `APPROVED`
review made on that same head commit. This phase is what produces those markers, so Phase 4 doesn't
hit the gate for a Ready PR you're about to merge.

For each PR categorized **Ready to merge** in Phase 2 (a PR that can't merge yet doesn't need
reviewing now — re-review it the next time this command runs and it's Ready):

1. For each Ready PR without current head-bound markers, run `/pr-open` on its branch (tier panel +
   markers). **Never hand-dispatch reviewers** — `/pr-open` dispatches the risk-tiered panel (plus
   `docs-impact-agent` at tier ≥ 1) concurrently in one message, runs fix rounds on its `Open:`
   lenses, and posts the head-bound `code-review` / `security-review` / `test-quality` verdict
   markers once `Open:` is `none`; a hand-rolled panel skips docs-impact and the round bookkeeping,
   so it is not a panel.
2. Carry the verdict into Phase 3's table (add a **Review** column) so the human sees it before
   confirming which PRs to merge.

A `CHANGES`/`BLOCKERS` verdict does NOT block Phase 3 from listing the PR — it blocks Phase 4's
`gh pr merge` (via `pr_gate`) until a fix-round lands and a NEW marker comment with `APPROVE`
supersedes it (the gate reads the latest marker by timestamp; no manual cleanup needed).

---

## Phase 3: PRESENT

```markdown
## Open PRs ({N})

### Ready to Merge
| PR | Title | Branch | Age | Review |
|----|-------|--------|-----|--------|
| #{N} | {title} | {branch} | {days}d | {APPROVE\|CHANGES\|BLOCKERS} |

### Needs Rebase ({N})
| PR | Title | Conflict |
|----|-------|----------|
| #{N} | {title} | {conflict details} |

### CI Failing ({N})
| PR | Title | Failure |
|----|-------|---------|
| #{N} | {title} | {failure summary} |

### Needs Review ({N})
| PR | Title |
|----|-------|
| #{N} | {title} |
```

---

## Phase 4: MERGE (with confirmation)

**Ask user which PRs to merge before proceeding.**

Order the approved list so the PR with the **largest docs diff goes last** — it's the most likely
conflict source for its siblings, so merging it first would dirty the rest of the batch.

For each approved PR, **re-query `mergeStateStatus` immediately before merging** — `CLEAN` is pairwise
with the *current* `main`, and an earlier merge in this batch may have invalidated it:

```bash
state=$(gh pr view {number} --json mergeStateStatus --jq .mergeStateStatus)
if [ "$state" != "CLEAN" ]; then
  echo "PR #{number} is now $state (not CLEAN) — batch merge invalidated it. Stopping; rebase needed."
  # stop here and report — do NOT attempt the merge (a failed gh pr merge is a wasted, opaque round-trip)
fi
```

If `CLEAN`, merge in **two separate commands** — `pr_gate` reads the raw text of the `gh pr merge`
command and cannot expand a shell variable, so `--match-head-commit "$head_sha"` is itself BLOCKED
(it sees the literal 9 characters `$head_sha`, not a sha). Read the sha first, then paste the
**literal 40-character value** into the merge command as plain text:

```bash
# (a) read-only — its own command. Also carries headRefName, to pick --merge vs --squash below.
gh pr view {number} --json headRefOid,headRefName --jq '"\(.headRefOid) \(.headRefName)"'
```

```bash
# (b) the merge — its own command, run only after reading (a)'s output. Replace <sha> below with
# the 40-character headRefOid printed by (a), typed in literally — never a variable reference.
# An integration-train PR (head branch train/*) keeps each member revertable: --merge, never --squash.
gh pr merge {number} --squash --delete-branch --match-head-commit <sha>
# train/* head branch instead:
gh pr merge {number} --merge --delete-branch --match-head-commit <sha>
```

```bash
git fetch origin   # refresh origin/main before the next PR's re-query
```

After the batch, pull main to stay current:

```bash
git pull origin main
```

---

## RULES

- Always ask before merging — never auto-merge
- Use `--squash` by default (cleaner history) — EXCEPT an integration-train PR (`train/*`), which merges with `--merge` so each member stays revertable
- Delete branch after merge (`--delete-branch`)
- If a PR is behind, offer to sync it in the PR's worktree: `gh pr checkout {N} && git merge origin/main` (one merge commit; never a force-push), then a normal `git push`
- Never force-merge PRs with failing CI
- Pull main after merging to stay current
- `CLEAN` is **pairwise** with current `main` — a property of (PR, main), not of the PR — so a batch
  invalidates it as it goes: each merge can dirty a later same-surface PR. Re-query `mergeStateStatus`
  before EACH merge (Phase 4), and merge the largest-docs-diff PR last.
- Review every Ready-to-merge PR in Phase 2.5 BEFORE presenting it as mergeable — don't skip
  straight to Phase 4 on a PR that hasn't had a verdict posted. `pr_gate` will block the merge
  anyway if you try; reviewing first avoids a failed `gh pr merge` round-trip.
- Never post an `APPROVE` marker you don't mean — if `code-reviewer` finds real issues, post
  `CHANGES`/`BLOCKERS` and say so; a marker posted just to unblock the gate defeats the entire
  point of this phase.

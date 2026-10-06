---
name: github-solve-issues
description: Use when the user says "triage the issues", "label/categorize the github issues", "sort the issues", "solve issue(s) N…", "solve the issues", or wants to burn down the open-issue backlog. Labels EVERY open issue by category, then by default dispatches a Claude Code agent per issue to open a PR (human merges); a parameter narrows the set or stops at labeling.
---

# github-solve-issues

Two stages: **Stage 1 labels every open issue by category**, **Stage 2 solves them** by dispatching
Claude Code agents (one isolated worktree per issue → PR; a human always merges).

**Defaults (changed 2026-08-10):**
- **Solve is the default, and the default set is EVERY open issue.** No arguments → label all, then
  solve all. A parameter (below) narrows the set or stops at labeling.
- **The solver is Claude Code** (this session's model, via `dispatch-agents-branches` / the Agent
  tool), not a local model. **Labeling also runs on Claude** — a cheap model (Haiku) via the `kimi`
  helper below. `--local` is the only path that uses free Ollama (opt-in).
- ⚠ **Cost — this runs on Claude (paid).** Default = **1 issue per run**; solve the rest only in
  explicit waves of ≤3, and **confirm with the human before each wave**, stating the rough token
  spend first. Never fire the whole backlog unattended. (`--local` is the free fallback.)
- **Never auto-merge.** Every fix lands as a PR for human review — that human merge IS the GATE-1
  safety net now that design-heavy issues are solved by default too.

## Usage / arguments (a parameter narrows the solve-all default)

| Invocation | Behavior |
|---|---|
| *(no args)* | Label ALL open issues, then **solve ALL** of them (Claude Code) → one PR each. |
| `N [N…]` (e.g. `188 189 172`) | Skip triage; **solve exactly those**. `gh issue view` each first; still open a PR each. |
| `--triage-only` (alias `--label-only`) | Stage 1 only — label every issue, **no solving**. |
| `--category <c>[,c…]` | After labeling, solve only issues in those categories. |
| `--exclude <N>[,N…]` | Solve all open issues EXCEPT these. |
| `--local` | Use the free local model (kimi helper below) as the solver instead of Claude Code. |

Always `gh issue view <n>` a design-heavy issue before solving and **note it in the report** — the
agent still drafts a PR (the human merge gate catches an unviable draft), but the human is warned.

## Preflight
- `gh auth status` OK; you're in the target repo (`gh repo view`).
- Default engine is Claude — confirm the `claude` CLI runs (`claude --version`). **Only `--local`** needs Ollama up: `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:11434/ | grep -q 200`, else fall back to Claude and say so (don't silently stop).

---

## Stage 1 — Triage & label (coverage-guaranteed)

The old failure this stage fixes: issues left **unlabeled** and inconsistent categories. The
deterministic loop — ensure labels → fetch → classify in batches → parse (retry once) → apply →
**bounded** coverage-gate — now lives in a script, so Claude spends its tokens on the judgment, not on
re-deriving the mechanics:

```bash
# dry-run first (classifies + prints the table; creates no labels, edits no issues):
python3 ~/.claude/skills/github-solve-issues/scripts/stage1-triage.py --dry-run
# then apply for real (default classifier = the pinned-Haiku kimi path above):
python3 ~/.claude/skills/github-solve-issues/scripts/stage1-triage.py --json
```

What the script guarantees: **every open issue ends with exactly one `category:*` label**, or it
exits **non-zero** listing the stragglers it could not clear (it re-classifies stragglers **at most
twice** — never the old unbounded loop). It prints the `#n | title | category | confidence | reason`
table (`--json` also emits the rows).

**Your judgment stays here — the script never makes these calls:**
- **Stragglers that survive the bounded loop** (non-zero exit): escalate exactly those numbers to a
  **Claude Code** classification (the Agent tool, `classify-prompt.md` as the prompt) — a stronger
  model than the cheap batch classifier — then re-run. Don't just re-run the same weak path forever.
- **`confidence < 0.6` rows** (flagged in the table): eyeball them; labels are human-overridable.
  Especially confirm no design-heavy issue landed in `mechanical`.
- **The category scheme itself** (`classify-prompt.md`): whether these six categories still fit the
  repo is a design call, not the script's.

### Flags Stage 1 raises (human-review only — NEVER auto-close/merge)
Two mechanical, flag-only detectors run inside the Stage-1 script. They add a `triage:*` label and a
report line; **the script never calls `gh issue close` / `gh pr merge`** — a human stays the gate.
- **`triage:likely-solved`** — an open issue closed by a PR that was **merged to the default branch
  (main)**. Detector uses GitHub's own closing-link graph (`closedByPullRequestsReferences`) +
  `gh pr view` for the base-branch/merge check — no Claude judgment pass. On a hit it reports
  `solved-by #PR` and **excludes the issue from Stage 2's DEFAULT solve set** — a DEFAULT, not a lock:
  an explicit `N` argument still solves it. *Known limits:* a merged-then-**reverted** closing PR still
  links (the human review before close catches it); only the **default** branch counts (a merge to a
  release/feature branch does NOT flag — it isn't shipped yet).
- **`triage:likely-dup`** — the batch classifier judged this issue a duplicate of another **in the same
  batch** (the additive `dup_of` field). Reported as a group; the human dedups at the "confirm before
  each wave" gate. *Known limit:* duplicates spanning different batches are not compared (batch-local,
  ~zero added cost).

**GATE-2 for Stage 1:** show `gh issue list --state open --json number,labels` proving 100% coverage
(the script's exit code already asserts it); spot-check ≥3 rows.

---

## Stage 2 — Solve (default: every open issue; Claude Code; PRs only)

1. **Select the set** by the argument rules above (default = every open issue **EXCEPT those flagged
   `triage:likely-solved`**, which are already fixed on the default branch — a DEFAULT exclusion, not a
   lock: an explicit `N` still solves one; `--category`/`--exclude` narrow further; explicit numbers =
   exactly those). Review any `triage:likely-dup` groups first so you don't solve a duplicate twice.
   `gh issue view <n>` each; WARN in the report on any that need a human GATE-1 design call (still
   solved — the merge gate is the net).
2. **Dispatch Claude Code agents**, one isolated worktree per issue, in **waves of ≤3**. Prefer the
   `dispatch-agents-branches` command (it parses issue numbers → parallel agents, each on its own
   `fix/<n>-<slug>` branch → PR). Equivalent manual form per issue: spawn the agent with
   `isolation: "worktree"` (native git worktree, auto-cleaned if unchanged) — or provision by hand:
   ```bash
   git worktree add .claude/worktrees/fix-issue-<n>-<slug> -b fix/issue-<n>-<slug>
   ```
   Each agent's brief MUST tell it to:
   - Follow the repo's `CLAUDE.md` + canonical workflow (auto-loaded `~/.claude/rules/workflow.md`; extended refs in the `claude-template-core` plugin) gates (Design→Code→Prove).
   - Make the minimal fix for issue #n; if it needs a human design call it can't make, open a
     **draft** PR describing the options rather than guessing.
   - **Hold the test lock** for any suite run: `bin/test-lock --wait [--timeout N] -- <TEST_CMD>` (queues FIFO; never a bare run).
   - **Test cadence:** run only the touched test files while building and in fix rounds;
     a full suite per PR for a tier-2 PR (tier-0/1 gates on the affected slice), at the final synced head; after the PR opens, CI (if any) is authoritative.
   - **Builder self-checks before ready:** surface any degraded/fail-open path on **stdout** (not only
     stderr); land a change to a twinned unit in **both** twins, each new test shown failing first;
     include the repo's deterministic doc checks (docs-drift / inventory-count) in the targeted run;
     ship docs describing the changed behaviour in the same PR; put a stale-base bypass token only on a
     `git merge origin/main` sync commit.
   - Conventional-commit ending with `Closes #<n>`; open it with `/pr-open` (links the issue, runs the panel).
   - Satisfy `close_issue_gate` (file follow-ups **or** emit `WORKFLOW:no-follow-ups`).
3. **Start conservative (paid — hard cap):** run **1 issue first**, verify the whole flow
   (branch → PR, GATE-2 green), then batch the rest in waves of ≤3, **confirming with the human
   before each wave** and stating the rough token spend. Never fire the whole backlog unattended.
4. **Dedup before ANY `gh issue create`** (GATE-0 for issue creation):
   `gh issue list --state all --search "<key terms>" --json number,title,state` → reference an existing
   match instead of creating a duplicate.
5. **No auto-merge.** Report every PR number; recommend a `code-reviewer` pass. The human is the merge gate.
6. **Report a completion table:** `#n | category | branch | PR | status (opened / drafted / failed)`.
   Log every issue an agent could NOT finish so nothing is silently dropped.

### The `kimi` helper (default = cheap Claude)
Labeling shells out to a **cheap Claude model** — process isolation from the session, controllable
cost.
```bash
kimi() {  # default: cheap Claude (Haiku 4.5) — paid, but small for labeling
  # Pin an EXACT ID (never a bare `haiku` alias — that floats to the newest generation).
  # Use `claude -p` (print mode); `claude --bare` REFUSES OAuth and stalls a normal login session.
  claude -p --strict-mcp-config --model "${SOLVE_MODEL:-claude-haiku-4-5-20251001}" "$@"
}
```
`stage1-triage.py` (below) uses this same pinned-Haiku path as its default classifier; override it
per-run with `TRIAGE_CLASSIFY_CMD` if you need a different tier.

### `--local` — free Ollama path (opt-in, the old free route)
Reverts labeling/solving to the free local model; treat output as **draft-quality** (a 30B local
model is weaker), and fall back to Claude for any issue it stalls on or that fails GATE-2. For a
`--local` run, override the helper with the Ollama form:
```bash
kimi() {  # --local ONLY: free Ollama
  env -u ANTHROPIC_API_KEY \
    ANTHROPIC_BASE_URL=http://127.0.0.1:11434 ANTHROPIC_AUTH_TOKEN=ollama \
    ANTHROPIC_MODEL=qwen3-coder:30b-128k ANTHROPIC_SMALL_FAST_MODEL=qwen3:8b \
    NO_PROXY=127.0.0.1 DISABLE_TELEMETRY=1 \
    claude -p --strict-mcp-config "$@"
}
```

---

## Guardrails
- **Paid by default:** labeling + solving run on Claude — batch conservatively (**1/run**, confirm per wave, state token spend). `--local` is the only free (Ollama) path.
- **Never merge. Never force-push. Never edit the primary worktree** — Stage 2 work is isolated per issue.
- Respect deny rules in `CLAUDE.md`; don't route a blocked command through any solver.
- Stage 1 is not done until the **coverage gate** shows zero unlabeled open issues.
- Design-heavy issues are still solved by default, but each is WARNED in the report and lands as a PR
  (often a draft) — the human merge is the design gate.
- `--local` labeling/solving needs Ollama up; if it's down, escalate to Claude Code and say so — never
  silently stop mid-run.

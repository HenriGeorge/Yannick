---
description: End-of-session reflection — harvest wins + lessons into the project's lessons file
argument-hint: [brief session description]
---

# Session Reflection

**Session description**: $ARGUMENTS (optional; will be derived from git log if empty)

---

## Your Mission

Close the feedback loop. Capture **both what worked and what broke** from this session as structured entries in the project's lessons file. Future sessions can load these so mistakes don't repeat and wins get reinforced.

Symmetric learning rules:
- **Lessons** capture failures — what broke and the rule that prevents it next time.
- **Wins** capture successes — what worked unusually well and why the pattern is worth keeping.
- Quality over count — 2–3 high-signal entries beats 10 mediocre ones. Zero is acceptable for trivial sessions.
- Dedupe — if an entry already exists (match by rule headline), extend it instead of re-adding.

---

## Phase 0: DISCOVER PROJECT CONVENTIONS

Before reflecting, discover where this project keeps its lessons and plans:

```bash
# Find the lessons file (check common locations)
for f in docs/lessons.md docs/dev-lessons.md docs/035_sw-dev-lessons.md LESSONS.md .claude/lessons.md; do
  [[ -f "$f" ]] && echo "LESSONS_FILE=$f" && break
done

# Find plan directories (check common locations)
for d in .claude/PRPs/plans .agents/plans .claude/plans plans; do
  [[ -d "$d" ]] && echo "PLANS_DIR=$d" && break
done

# Find state directory
for d in .claude/state .agents/state; do
  [[ -d "$d" ]] && echo "STATE_DIR=$d" && break
done
```

**If no lessons file exists**: Create one at `docs/lessons.md` with a header:

```markdown
# Development Lessons

Wins and lessons from development sessions. Loaded at session start to prevent repeated mistakes and reinforce good patterns.
```

Store the discovered paths — they're used throughout the remaining phases.

---

## Phase 1: GATHER SESSION CONTEXT

Gather the raw material:

```bash
# Git commits made in this session (last N hours as a rough proxy)
git log --oneline --since='6 hours ago' | head -20

# PRs opened/merged in this session
gh pr list --state merged --search "updated:>$(date -u -v-6H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '6 hours ago' +%Y-%m-%dT%H:%M:%SZ)" --json number,title --jq '.[] | "- #\(.number): \(.title)"' 2>/dev/null || echo "(gh query failed)"

# Files touched in uncommitted changes
git status --short
```

**Also harvest phase reflections** if the project uses state-gated workflows:

```bash
branch=$(git branch --show-current)
if [[ -n "$STATE_DIR" ]]; then
  for f in plan-reflection.md implement-reflection.md; do
    path="$STATE_DIR/$branch/$f"
    [[ -f "$path" ]] && echo "=== $f ===" && cat "$path"
  done
fi
```

**Also surface the objective friction signals for THIS session** (gitignored, under `.claude/state/`
+ `.claude/telemetry/`). Run the digest — keyed precisely by this session's id, never a wall-clock
window (7+ concurrent sessions on this repo bleed otherwise):

```bash
# per-session friction + consumption: loop_detector / scope_creep / suite_overrun / compact / edits
# + gate BLOCKs + cost (tokens·messages) + suite_time
if [ -x bin/session-friction ]; then bin/session-friction "$CLAUDE_CODE_SESSION_ID"; fi
```

Read the digest for **high-attempt / repeat-fail** friction: a `loop_detector: warned`, a large
`scope_creep`, a high `suite_overrun` (attempts-to-green ≥3 on one surface), or repeated `gate_blocks`
(e.g. many `stale_base_guard` denies = you didn't sync) is a candidate friction lesson. The `cost:`
line (tokens · messages) and `suite_time:` line surface **consumption** — an unusually high token or
suite-time burn for the work delivered is itself a friction lesson. Also read
`failures.jsonl` — a recurring `kind`+`file` (e.g. repeated `test_fail` after a schema change) is a
lesson about a missing step. These are the objective counterpart to the subjective reflection below.

**Read these sinks across ALL worktrees, not just this checkout (#787)** — they are
`CLAUDE_PROJECT_DIR`-scoped, so delegated BUILD work in worktrees writes its own
`.claude/telemetry/`, where most friction data lands:

```bash
common=$(git rev-parse --git-common-dir); root=$(cd "$common/.." && pwd)
find "$root" -path '*/.claude/telemetry/failures.jsonl' -print0 | xargs -0 cat 2>/dev/null
# (or walk `git worktree list --porcelain`)
```

Also think about:
- What did the user push back on? Corrections are high-signal lessons.
- What took longer than expected? Surprise-cost is a lesson.
- What debugging chain turned out to have a trivial root cause? That's a lesson about the sense-making process.
- What mental model of the codebase turned out to be wrong? High-value structural lesson.
- **What unusually worked?** A plan step that nailed a hard dependency, a validation command that caught a bug early, a review question that exposed a flaw — these are wins worth remembering.

---

## Phase 1.5: PROCESS DIVERGENCE ANALYSIS

**Skip this phase if**: the session had no plan (ad-hoc debugging, research-only, <5 files touched). Jump straight to Phase 2.

This phase compares **plan vs reality** to surface process bugs — problems in the workflow itself, not the code. It's the feedback loop that improves planning, tooling, and automation over time.

### Step 1: Find the plan

```bash
branch=$(git branch --show-current)
# Check state directory for plan reference
[[ -n "$STATE_DIR" ]] && ls "$STATE_DIR/$branch/" 2>/dev/null
# Check plans directory for recent plans
[[ -n "$PLANS_DIR" ]] && ls -lt "$PLANS_DIR/" | head -5
```

If no plan file exists, log `Plan alignment: N/A (no plan)` and skip to Phase 2.

### Step 2: Compare plan tasks vs actual diff

```bash
# What files were actually changed?
git diff origin/main --name-only 2>/dev/null || git diff main --name-only | head -30

# What did the plan say to change?
grep -E '^### Task|CREATE|UPDATE|MODIFY' "<plan-file>" | head -20
```

Identify divergences in three categories:

| Category | Meaning | Signal |
|----------|---------|--------|
| **Planned but not built** | Task in plan, not in diff | Scope cut or blocked dependency |
| **Built but not planned** | File in diff, not in plan | Emergent work — plan was incomplete |
| **Built differently** | Same file, different approach | Plan assumption was wrong |

### Step 3: Classify each divergence

For each divergence, ask **why**:

- **Plan was wrong** — assumed something that doesn't exist or works differently. *Process fix: improve plan research or review depth.*
- **Plan was incomplete** — missed a dependency, edge case, or integration point. *Process fix: add to review checklist or plan template.*
- **Scope changed** — user redirected mid-session. *Not a process bug — just log it.*
- **Shortcut taken** — simpler version than planned. *Is this pragmatism or tech debt?*
- **Validation caught it** — per-task or full-suite validation surfaced the issue. *System working as designed — record as a win.*

### Step 4: Identify process improvements

For each non-trivial divergence, ask: **what specific asset should change?**

| Asset | Example change |
|-------|---------------|
| `CLAUDE.md` / project config | New rule, gotcha, or constraint |
| Skill or command | Plan template, review checklist, execution protocol |
| Agent definition | New check in agent instructions |
| Memory | Feedback memory for future sessions |
| Nothing | One-off divergence, no systemic fix needed |

Don't force improvements. Sometimes divergences are one-offs and the right answer is "nothing."

### Step 5: Bias check — the all-wins audit

**If this session produced only wins and zero lessons**, actively look for:

1. A task that took multiple iterations when the plan said it should be straightforward
2. A validation check that was missing from the plan (would have caught an error earlier)
3. A review concern that turned out to be correct but was dismissed or deferred
4. An assumption about an external API or library that had to be corrected at runtime
5. A file that was edited but isn't in the plan's task list (emergent scope creep)
6. User corrections or pushback during the session (check conversation history)

All-win sessions genuinely happen — but they should be **verified as all-win**, not assumed. The absence of recorded lessons doesn't mean the absence of problems; it can mean the problems were absorbed silently. The goal isn't to manufacture fake lessons — it's to make sure real ones aren't slipping through.

If the audit confirms no lessons: great. Log `Bias check: PASS — no hidden lessons found` in the session block.

---

## Phase 2: DRAFT ENTRIES

Identify **2–4 entries total** — roughly 1–2 wins and 1–2 lessons, though sessions vary. Each entry matches one of two formats below.

### Lesson format (for failures)

```markdown
### N. <Rule headline — short, imperative, searchable>

**Trigger**: <the situation/smell that should make a FUTURE session recall this — the retrieval key a later session matches its own context against. 1 sentence.>

**Problem**: <Concrete description of what went wrong. Include file:line or command:output if relevant. 1-3 sentences.>

**Root cause**: <Why it happened. Be honest — "I assumed X without checking" is a valid root cause. 1-2 sentences.>

**Fix**: <What was done to resolve it in this session. Include the exact command / code change if illustrative.>

**Rule**: <A single-sentence generalizable guideline for future sessions. Imperative mood. Should be directly actionable: "Before X, always Y.">

**Tags**: `#area/<domain>` `#kind/<bug|process|tooling|design>` — for future filtering.
```

### Win format (for successes)

```markdown
### N. ✓ <Pattern headline — short, imperative, searchable>

**What worked**: <Concrete description of the pattern or approach that paid off. Include file:line or command if relevant. 1-3 sentences.>

**Why it worked**: <The underlying mechanism — what made this approach better than alternatives. 1-2 sentences.>

**Keep doing**: <A single-sentence generalizable guideline for future sessions. Imperative mood. Should be directly actionable: "When X, do Y.">

**Reuse when**: <the trigger condition to apply this again — the retrieval key. 1 sentence.>

**Tags**: `#area/<domain>` `#kind/<pattern|tooling|process|design>`.
```

Wins are prefixed with `✓` in the headline so they're visually distinct and greppable.

Before writing, check whether the entry is already recorded:

```bash
grep -i "<keyword from your headline>" "$LESSONS_FILE"
```

If a matching entry exists, decide:
- **Bump the recurrence counter** — the same lesson recurred → do NOT add a new row. Add/increment a
  `**Seen**: Nx (last YYYY-MM-DD)` line on the existing entry. Recurrence count is a **priority signal**:
  a lesson learned repeatedly is worth more than a one-off and is a candidate for promotion (below).
- **Extend** the existing entry with a new incidence (a near-match → merge/generalize into one broader rule).
- **Skip** if the existing entry is already sufficient.
- **Split** only if the existing entry covers a genuinely different aspect.

**Promotion (the log is a staging area, not a graveyard).** When a lesson has recurred enough (`Seen: ≥3x`)
or has been internalized as a real guardrail, it should **graduate OUT of the log** into an enforced asset
— a `CLAUDE.md` rule, a hook, a lint rule, or a test — leaving a one-line stub pointer in its place
(`### N. <headline> → promoted to <asset> YYYY-MM-DD`). A lesson that lives only in the log forever is one
nobody acted on. Note promotions in the session block's "Process improvements" table.

---

## Phase 3: DETERMINE APPEND POINT

```bash
# Find the highest-numbered existing entry
highest=$(grep -oE '^### [0-9]+\.' "$LESSONS_FILE" | grep -oE '[0-9]+' | sort -n | tail -1)
echo "Highest existing entry: ${highest:-0}"
echo "Next entry number: $(( ${highest:-0} + 1 ))"
```

New entries get sequential numbers. Wins and lessons share one number space.

---

## Phase 4: WRITE THE SESSION BLOCK

Append a new session block to the END of the lessons file:

```markdown

---

## Session: YYYY-MM-DD HH:MM (<short session description>)

<1-2 sentence session summary — what was shipped / worked on, PR numbers if any>
_(Timestamp: use `date '+%Y-%m-%d %H:%M'` — commit-local time, matching the D1 doc-stamp convention.)_

### N. ✓ <Win headline>

**What worked**: ...
**Why it worked**: ...
**Keep doing**: ...

### N+1. <Lesson headline>

**Problem**: ...
**Root cause**: ...
**Fix**: ...
**Rule**: ...

## Action items from this session

1. <Follow-up tasks surfaced by the entries — separate from the entries themselves>
2. ...

## Process review

**Plan alignment**: HIGH / MEDIUM / LOW / N/A (no plan)
**Bias check**: PASS (no hidden lessons) / FOUND (<what was surfaced>)

### Divergences (omit if alignment is HIGH or N/A)

| What diverged | Plan said | Actually built | Why | Category |
|---------------|-----------|----------------|-----|----------|
| <file or task> | <planned approach> | <actual approach> | <root cause> | Good ✅ / Bad ❌ |

### Process improvements (omit if none)

| Asset to change | Specific edit | Priority |
|-----------------|---------------|----------|
| `CLAUDE.md` | <exact rule or line to add/change> | HIGH / LOW |
| Skill/command | <what to add to template> | HIGH / LOW |
| Agent definition | <instruction change> | HIGH / LOW |
| Memory | <new feedback memory to save> | HIGH / LOW |

**Do NOT auto-apply these changes.** List them as action items. The user decides which to apply — process changes affect all future sessions and need human judgment.

## Incidents (<Session Description>)

| Entry | Type | Summary | Outcome |
|-------|------|---------|---------|
| N     | ✓    | <one-line headline> | <one-line what-worked> |
| N+1   | ✗    | <one-line headline> | <one-line root cause + fix> |
```

The Process review section is the **meta-level analysis** — it's about the workflow, not the code. It should be concise: 2-5 rows in the divergences table max. If the plan was followed perfectly, a single line (`Plan alignment: HIGH, Bias check: PASS`) is sufficient.

Order inside a session block: **wins first, lessons second, process review last**.

---

## Phase 4.5: RETENTION — archive session blocks older than 30 days

The lessons file is loaded at session start, so its cost must stay bounded — **archive, never delete.**
After appending the new block, move every `## Session:` block whose date is **older than 30 days** from
the ACTIVE file (`$LESSONS_FILE`, e.g. `docs/lessons.md`) to the sibling archive
(`docs/lessons-archive.md` — create it with a header if absent). The archive is searchable but NOT
auto-loaded, so lessons aren't lost, only de-prioritized.

```bash
ARCHIVE="$(dirname "$LESSONS_FILE")/lessons-archive.md"
cutoff="$(date -v-30d +%Y-%m-%d 2>/dev/null || date -d '30 days ago' +%Y-%m-%d)"
echo "Cutoff (archive blocks dated before this): $cutoff"
# List candidate blocks (review before moving): each '## Session: YYYY-MM-DD…' with a date < cutoff.
grep -nE '^## Session: [0-9]{4}-[0-9]{2}-[0-9]{2}' "$LESSONS_FILE" | \
  awk -v c="$cutoff" '$3 < c {print}'   # grep -n prefixes "LINENO:", so the ISO date is field $3 (default whitespace FS)
```

Move each identified block (header through the line before the next `## Session:` / EOF) to the END of
`$ARCHIVE`, preserving order. **A promoted lesson's stub stays in ACTIVE** (it's a live pointer, not
history) — only whole aged session blocks migrate. Record the archival in the session block's process
review (`Archived: <n> session blocks older than <cutoff> → lessons-archive.md`). Do this as a reviewable
edit, not a blind delete — verify the ACTIVE file still parses (headings intact) before committing.

---

## Phase 4.6: FILE FOLLOW-UPS AS CATEGORIZED ISSUES

The "Action items" and "Process improvements" surfaced above decay if they only live in the lessons
file (that rot is exactly why `/improve` exists). Turn each into a tracked, categorized GitHub issue —
this also satisfies CLOSE's close-issue gate (`WORKFLOW:no-follow-ups` is the opt-out).

For each Action item and each Process-improvement row (**cap 5 per run** — a full backlog burn is
`github-solve-issues`' job):

1. **Classify** into exactly one category from `classify-prompt.md`:
   `mechanical | bug | design-decision | docs | chore | question`. A process improvement is usually
   `design-decision` (a GATE-1 human call) or `chore`; when unsure, pick `design-decision` — never
   `mechanical` (err toward keeping a human in the loop).
2. **Dedupe** — skip if an open issue with a matching title already exists (don't double-file against a
   prior run or CLOSE):
   ```bash
   gh issue list --state open --search "<normalized title> in:title" --json number,title
   ```
3. **File** (only when step 2 found no match). Pass the title/body as literal argv via shell
   variables — never interpolate reflection-derived text directly into the command string, or a
   headline containing `` ` ``, `$(…)`, or `"` injects shell:
   ```bash
   TITLE='<concise title>'            # single-quote; literal, no shell expansion
   BODY='Surfaced by /dev-reflect. Source: <lesson #/divergence>.

   <1-3 sentence context + the concrete next action>'
   gh issue create --title "$TITLE" --body "$BODY" --label "category:<c>"
   ```

Report the filed issue numbers (and any skipped-as-dup) in the output block below. Pre-labeling means
`github-solve-issues` won't re-triage them.

## Phase 5: COMMIT THE ENTRIES

```bash
git add "$LESSONS_FILE" "$ARCHIVE"  # ARCHIVE only exists/changes if Phase 4.5 moved aged blocks
git commit -m "docs(lessons): session reflection — <short description> (<W wins, L lessons>)"
```

If on the default branch and a branch guard blocks the commit, create a branch first: `chore/lessons-YYYY-MM-DD`.

Also clean up per-phase reflections once harvested:

```bash
branch=$(git branch --show-current)
if [[ -n "$STATE_DIR" ]]; then
  rm -f "$STATE_DIR/$branch/plan-reflection.md"
  rm -f "$STATE_DIR/$branch/implement-reflection.md"
fi
```

---

## OUTPUT FORMAT

After appending, echo back:

```
## Session reflection written

Session: <description>
Entries added: N total (<W wins, L lessons>)
Recurrences bumped: <k> (Seen counters, not re-added)   Promoted: <p> → <asset>
Range: #<start>..#<end>
Archived: <a> session blocks older than <cutoff> → lessons-archive.md
File: <LESSONS_FILE> (now <line count> lines, <total entries> total)

### Wins
- <one-line headline for each win>

### Lessons
- <one-line headline for each lesson>
```

Then tell the user whether the commit succeeded and list the next step (push + PR, or continue working).

---

## When to SKIP reflection

- **Trivial session** (<5 files touched, <15 minutes, no surprises): one-line note is fine; don't force a full entry.
- **Read-only session** (audit, exploration, research): no entries unless you discovered a meaningful structural insight.

**Even on skipped sessions, if phase reflection files exist under the state directory, delete them before ending** — otherwise they'll be falsely harvested as fresh material by the next session's `/dev-reflect`.

---

## Reinvent log

Decisions from `/skill-reinvent dev-reflect` runs (anti-churn — a re-run should not re-propose a
declined idea against unchanged content).

- **2026-08-15** — blind rederivation (general-purpose subagent, goal-only). Adopted: **timestamp**
  (`## Session:` now `YYYY-MM-DD HH:MM`), **retention/archive >30d** (new Phase 4.5 → `lessons-archive.md`;
  the fresh derivation independently converged on this — corroboration), **recurrence counter** (`Seen: Nx`),
  **promotion lifecycle** (recurred/internalized lessons graduate OUT to a hook/lint/CLAUDE.md, stub left),
  **Trigger/Reuse-when** retrieval-key fields, **Tags** (`#area/#kind`). Rejected: W-/L- prefixed IDs
  (current shared numbering kept). MATCH set (corroborated, unchanged): dual wins+lessons · raw-material
  harvest · plan-vs-reality divergence · all-wins bias check · generalize-or-drop · dedupe · evidence
  anchors · verdict shape.

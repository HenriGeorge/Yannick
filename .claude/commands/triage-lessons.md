---
description: Triage one batch of docs/lessons.md by applicability scope (global vs project-specific) into docs/lessons-triage.md. Idempotent — run under /loop self-paced until every lesson is triaged.
argument-hint: "[batch-size, default 20]"
---

# triage-lessons

Classify lessons in `docs/lessons.md` by **applicability scope** and record the verdict in
`docs/lessons-triage.md`. One batch per invocation; designed to be driven by `/loop` self-paced
(`/loop /triage-lessons`) until nothing is left to triage.

**This never edits or moves a lesson** — it only appends a scope note to the triage ledger. Promoting
a global lesson into `~/.claude/rules/` is a separate, human-invoked step.

## Do one batch

1. **Read the ledger** `docs/lessons-triage.md`. Collect the set of lesson `#`s already in its table
   (the dedup key). If the file is missing, create it from the header in this repo's copy first.
2. **Find untriaged lessons.** Scan `docs/lessons.md` for `### #NNN — <headline>` blocks (lessons are
   `#165` onward; `#69–#164` are in `lessons-archive.md` — ignore those). Take the next **N** (arg, default
   20) whose `#` is NOT already in the ledger, in file order.
3. **Classify each** by scope — read enough of the lesson body to judge, don't guess from the headline
   alone:
   - **`global`** — the lesson states a practice/guard true on *any* project (workflow discipline,
     git hygiene, review habits, a language-agnostic engineering rule). Candidate for `~/.claude/rules/`
     or global `CLAUDE.md`.
   - **`project`** — the lesson only makes sense for one repo (names a specific stack, tool, file path,
     or product — `ableton`/Live, Supabase ports, this template's `setup.sh`, a Figma channel). Put the
     repo name in the Project column. If it's plausibly reusable but *written* against one repo, still
     mark `project` and name it — promotion can generalize it later.
   - **Ambiguous?** Prefer `project` with the most-likely repo named + a `?` in the Why — never invent a
     global rule from a one-off.
4. **Append rows** to the ledger table, one per lesson, in `#` order:
   `| 165 | Sequence the guard before the work it protects | global | — | workflow discipline, any repo |`
   Keep the headline short (trim to the gist); the Why is one clause.
5. **Refresh the stamp** (`Last updated:`) and **report progress**: `triaged N (#X–#Y); M lessons remain
   untriaged`. When step 2 finds **zero** untriaged lessons, say exactly `ALL LESSONS TRIAGED` — that is
   the `/loop` stop signal.

## Verify
- Every appended `#` was absent from the ledger before this run (no duplicate rows).
- Row count added == lessons classified this batch; each row has a Scope of exactly `global` or `project`.
- No line in `docs/lessons.md` was modified (this command is read-only on the lessons themselves).

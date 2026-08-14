# Documentation conventions

Last updated: 2026-08-14 15:55

> **Source of truth & sync.** Repo snapshot of the machine-global `~/.claude/rules/doc-conventions.md`
> (via `sync-rules.sh`). Listed in `sync-rules.sh`'s `HAND_RECONCILED` — captured once to its global counterpart (2026-08-09); now
> hand-maintained on BOTH sides (kept in `HAND_RECONCILED` so the blind name-sync won't clobber it).

Conventions for the docs this repo ships and every project it scaffolds. These are judgment-call
habits with one machine-assisted helper (`bin/stamp-docs.sh`), not a hard PreToolUse gate.

## D1 — Every doc carries a `Last updated:` stamp (with time-of-day)

Every documentation file (`*.md` under `docs/` and `rules/`, plus top-level `README.md`) carries a
freshness stamp near the top:

```
Last updated: YYYY-MM-DD HH:MM
```

- 24-hour clock, no seconds, no timezone (commit-local time — accepted as fine for a solo/small-team
  template; see `bin/stamp-docs.sh`'s header for the exact source).
- Place it right after the file's first `# heading`. A leading `>` blockquote form
  (`> Last updated: 2026-08-09 14:05`) is equally accepted — both are recognized by the tooling. An
  ADR's bold-list form (`- **Last updated:** 2026-08-09`) is ALSO recognized (never false-flagged as
  missing) but is **hand-updated, not auto-rewritten** by `--upgrade` — the automated forms are the
  bare and blockquote styles only. Markdown **emphasis-wrapped** stamps (`_Last updated: …_`, `*…*`,
  `**…**`, `__…__`) are likewise recognized, so a backfill never inserts a duplicate stamp above an
  already-stamped-but-emphasized line (issue #124).
- **Why the time, not just the date:** two edits landing the same day used to be indistinguishable —
  "is this still current?" needed a same-day tiebreaker. Time-of-day is the cheapest signal for that.
- **Stamp conflicts auto-resolve.** Because two PRs each bump this line to their own commit datetime,
  the stamp used to be the #1 source of mechanical rebase conflicts. A surgical merge driver
  (`bin/git-merge-docstamp.sh`, registered per-clone at session start via `.gitattributes`
  `*.md merge=docstamp`) now keeps the newer stamp automatically on a stamp-only conflict — only real
  content conflicts surface for manual resolution.
- Update the stamp whenever you make a substantive edit to the doc — the CLOSE/DOCUMENT phase of
  `workflow.md` is the natural place to refresh it (alongside the `docs-impact-agent` pass). A
  backfilled stamp's `HH:MM` is only meaningful once it's actually refreshed on a real edit — accept
  that a purely-backfilled time is "last commit time," not "last read time."
- An optional `Created: YYYY-MM-DD` line may accompany it for docs where origin date matters
  (ADRs, specs); it is never required.

## D2 — Backfill from git history, not "today"

Backfill/verify stamps with `bin/stamp-docs.sh` (`--check` = the CI/pre-commit gate; dates each doc
from its **last commit**, not "today"; idempotent; bash+coreutils+git only) — prefer running it over
hand-typing a date.

## See also

`bin/stamp-docs.sh` (the helper) · `workflow.md` (P6 DOCUMENT / P8 CLOSE — where stamps get
refreshed) · `engineering-conventions.md` (R4 "prefer editing over creating" — the sibling habit for
source files).

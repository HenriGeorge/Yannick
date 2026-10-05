# Documentation conventions

Last updated: 2026-10-05 13:57

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
  already-stamped-but-emphasized line.
- **Why the time, not just the date:** two edits landing the same day used to be indistinguishable —
  "is this still current?" needed a same-day tiebreaker. Time-of-day is the cheapest signal for that.
- **Stamp conflicts auto-resolve.** Because two PRs each bump this line to their own commit datetime,
  the stamp used to be the #1 source of mechanical rebase conflicts. A surgical merge driver
  (`bin/git-merge-docstamp.sh`, registered per-clone at session start via `.gitattributes`
  `*.md merge=docstamp`) now keeps the newer stamp automatically on a stamp-only conflict — only real
  content conflicts surface for manual resolution. Its sibling `pluginver` driver
  (`bin/git-merge-plugin-version.sh`, registered the same way) does the same for the plugin
  version-coupling files: a version-only manifest conflict resolves to max+1 **per file** — so when
  only one of a coupled pair (`plugin.json` ↔ `marketplace.json`) conflicts, the two can desync; run
  `bin/reconcile-plugin-versions.sh` after the merge to re-sync marketplace to the plugin.json version
  (`--check` reports without repairing). The generated hooks fingerprint is left as a conflict to
  regenerate, never merged as text.
- Update the stamp whenever you make a substantive edit to the doc — refresh it when the builder
  applies the P5 `docs-impact-agent` findings in the fix push (the DOCUMENT phase of `workflow.md`). A
  backfilled stamp's `HH:MM` is only meaningful once it's actually refreshed on a real edit — accept
  that a purely-backfilled time is "last commit time," not "last read time."
- **Never hand-type the time.** Refresh a stamp with `bin/stamp-docs.sh --touch <file>...` (rewrites
  the existing stamp to now, style preserved), or paste the output of `date '+%Y-%m-%d %H:%M'`. An
  invented "plausible" time lands in the future; `--check-fresh` flags it.
- An optional `Created: YYYY-MM-DD` line may accompany it for docs where origin date matters
  (ADRs, specs); it is never required.

## D2 — Backfill from git history, not "today"

Backfill/verify stamps with `bin/stamp-docs.sh` (`--check` = the CI/pre-commit gate; dates each doc
from its **last commit**, not "today"; idempotent; bash+coreutils+git only) — prefer running it over
hand-typing a date.

The three verify modes are layered, lenient → strict: `--check` (presence-only — a stamp exists) ·
`--check-time` (the stamp carries `HH:MM`, not date-only) · `--check-fresh` (the
date+time stamp is not OLDER than the doc's last **content** commit, i.e. the doc wasn't edited
without refreshing its stamp). `--check-fresh` skips commits that touched only the `Last updated:`
line (so a stamp-only re-commit never marks a doc stale against itself) and skips date-only /
untracked docs. It also flags a **future** stamp (later than now + 5 min — a hand-typed time;
untracked docs included) and
prints the file, the stamp and the current time. It is a **template-repo opt-in** — deliberately NOT wired into scaffold CI, since a
freshly scaffolded/propagated copy legitimately carries a backfilled stamp newer than its content.

## D3 — `@`-import only always-core docs; everything else lazy-links

A doc `@`-imported into `CLAUDE.md` (the `## Conventions (always-core)` block) loads into **every
session's context** and pays its token cost every turn, forever. So the bar for `@`-import is
"relevant on essentially every task," not "useful."

- **Always-relevant convention → `@`-import** (ambient repo-committed prose). This is the ~10 stable
  always-core rules only.
- **Scoped / sometimes-relevant → a trigger-fired plugin skill** (web-accessibility, figma-ui,
  local-browser-testing, rtk). Costs **zero** tokens until its trigger context appears — never
  `@`-import a doc that would be noise on an unrelated task.
- **Deterministic / enforceable → a hook**, with at most a one-line pointer in prose (see
  the hook layer's rules-vs-hooks boundary).
- **Reference docs** (e.g. `FIGMA-UI.md`, `FIELD-GUIDE.md`, and the like) are **never**
  `@`-imported — they are reached via a `## See also` lazy-link, so they stay out of ambient context
  until a task actually opens them.
- **Verify every `@`-import target exists** — a missing target is silent context loss.

The full decision tree + rationale lives in the rules-triage design spec (upstream in the
`claude_template` repo, under `docs/superpowers/specs/`); this rule is its one-paragraph
summary so it's discoverable from the doc conventions, not only the design spec.

## D4 — Plugin docs vs template-repo docs (audience split)

**IN the plugin (`plugins/claude-template-core/docs/`) = anything a scaffolded repo or its
users/agents read-or-run at _runtime_** — the workflow references, the feature guides, the field
guide. **OUT (top-level `docs/`) = template-maintenance docs only** — the operating manual, the
architecture map, onboarding, the lessons log, ADRs and design specs. This rule states the
*principle*; the exact in-plugin set is the `cloud-bundle.yaml` `bundle.docs` allowlist (so the list
lives in one place, not duplicated here), enforced against the plugin docs tree by
`tests/test_plugin_doc_packaging.sh`.

**"In the plugin" ≠ "loaded into context every session."** A plugin loads almost nothing ambiently —
a skill indexes only its one-line description until triggered; `docs/` files and `bin/` scripts are
**never** auto-loaded; a `See also` link points to them and the agent `Read`s on demand. So shipping a
doc in the plugin costs disk + bundle size, **not** per-session tokens; keep maintainer docs out for
**audience clarity**, not token cost.

Plugin docs are **canonical-in-place** (no sync copies them, unlike `bin/`/`rules/`). The consumer-doc
set is enforced against the `cloud-bundle.yaml` `bundle.docs` allowlist by
`tests/test_plugin_doc_packaging.sh`.

## See also

`bin/stamp-docs.sh` (the helper) · `workflow.md` (P6 DOCUMENT / P8 CLOSE — where stamps get
refreshed) · `engineering-conventions.md` (R4 "prefer editing over creating" — the sibling habit for
source files) · the enforcement/gate-roster reference doc (the hooks↔agents cross-walk — an example of a
See-also reference doc, deliberately not `@`-imported).

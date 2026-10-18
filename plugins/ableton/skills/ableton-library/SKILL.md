---
name: ableton-library
description: >-
  Check corpus freshness (MIDI/presets/samples), search the external drum-sample corpus, and mine
  factory presets for real parameter values. Use when Henri says "check the index", "is the corpus
  stale?", "find me a sample/loop", "what does the factory <preset> actually do?", or "digest the
  <category> presets". Consolidates `scripts/check-index.py` (read-only freshness sweep),
  `scripts/find-samples.py` (read-only sample search; `--stage` loads clips into Live and needs an
  explicit confirm), and `scripts/mine-preset.py`/`scripts/corpus-digest.py` (preset research) — NOT
  for building a multi-instrument drum kit shortlist (→ ableton-drum-kit), NOT for rack drift
  (→ ableton-racks), NOT for the daemon process (→ ableton-daemon).
---

# Ableton Library — corpus freshness, sample search, preset research

Three independent read-only surfaces (one write path, clearly marked). Pick by INTENT, not by
"which script" — Henri rarely names the script.

## A. Corpus freshness — `scripts/check-index.py`

"Is the index stale?" / a SessionStart note flagged a group as non-fresh:

    python3 scripts/check-index.py               # sweep every corpus group (midi/presets/samples)
    python3 scripts/check-index.py --group midi  # narrow to one
    python3 scripts/check-index.py --no-apply     # read-only, never prompts (use for a quiet check)

Never reindexes silently, and REFUSES while Live is running (reindexing is a heavy
between-sessions job). Interactive default offers a reindex on an explicit 'y' for a STALE group —
present it, don't auto-answer. `--establish` blesses the current corpus as baseline (migration
cold-start / after a manual reindex) — only run this if Henri asks to "reset the baseline", not as
a routine fix for a STALE finding.

## B. Sample search — `scripts/find-samples.py`

"Find me a <brief>" (a drum/loop/one-shot search over the external Drums_Extern corpus):

    python3 scripts/find-samples.py "dark jungle break" --bpm 174 --bpm-tol 5
    python3 scripts/find-samples.py "punchy kick" --kind oneshot --tier curated -n 8

Read-only by default — prints a ranked shortlist (Henri's ears choose from it, never claim to have
heard audio). **`--stage N` is a WRITE path** — it loads the top-N hits as audio clips onto a
"ZZ SAMPLE AUDITION" track in the live set. Only pass `--stage` after Henri explicitly asks to
audition in Live, never by default.

## C. Preset research — `scripts/mine-preset.py` / `scripts/corpus-digest.py`

"What does the factory <name> preset actually do?" (name-scoped, `.adg`-inclusive):

    python3 scripts/mine-preset.py Wavetable --like reese
    python3 scripts/mine-preset.py Wavetable --like reese --params Filter1_Slope

"What do factory presets in <category> typically tweak?" (category-scoped aggregate, `.adv`-only):

    python3 scripts/corpus-digest.py Operator --tag Bass
    python3 scripts/corpus-digest.py Wavetable --categories "Bass,Synth Lead"

Both are pure read-only queries over `library.db`'s preset tables — never write anything, never
touch Live. `mine-preset.py` flags every `.adg`-sourced value as possibly macro-offset (a rack macro
can drive the parameter underneath) — never launder that into a literal-looking value when
reporting to Henri.

## D. Tutorial index — `scripts/tutorials.py`

"Which tutorials do we have / have we done?", "what tutorial made this preset?",
"find the URL for X", "mark this technique built":

    python3 scripts/tutorials.py list --tag ambient --has-preset   # browse/filter guides
    python3 scripts/tutorials.py list --status built,kept          # what we've DONE
    python3 scripts/tutorials.py preset "Overmono Juno Pad"        # preset -> tutorial URL(s)
    python3 scripts/tutorials.py url https://www.attackmagazine.com/...   # url -> guide
    python3 scripts/tutorials.py status <slug> built               # mark a technique done

Read-only except `status` (bumps the ledger) and `seed`/`index` (regenerate,
normally run by refresh-library.sh). The browsable table is committed at
`docs/ableton-docs/bible/guides/TUTORIALS-INDEX.md`. Status: `indexed` = on disk,
not deliberately touched; `learned`/`built`/`kept` = human-set. NOTE: preset↔URL
links cover only ~2% of presets today (matcher-tuning is a separate task).

## E. Drum engine variants — `scripts/drum-variants.py`

"Give me the Superior/Reason/… version of this groove", "what engine variants exist for this drum
loop?": the GM MIDI Pack ships each groove in ~12 per-engine folders but only the `… GM` one is indexed
(the siblings are the SAME groove ± velocity/duration). Reach them on demand — no DB rows added:

    python3 scripts/drum-variants.py list --brief "jazz swing"                 # variants of the top hit
    python3 scripts/drum-variants.py list --path "<indexed GM-pack rel path>"  # variants of an exact groove
    python3 scripts/drum-variants.py stage --path "<GM rel>" --engine Superior --rack "<track>" --slot 0

`stage` takes `--path` only (never the ranker's guess) and same-groove-verifies the sibling before
writing. Only GM-pack grooves have siblings. See `docs/guides/DRUM-RETRIEVAL-HOWTO.md` → "Engine
variants (on demand)".

## Workflow

1. Route by intent (freshness / search / preset research) — don't guess the script from the words
   Henri used; match to the closest of the three above.
2. Freshness and preset-research are read-only by construction — no confirm needed beyond an
   explicit reindex 'y' (A) which check-index.py itself prompts for.
3. Sample search stays read-only UNLESS Henri explicitly asks to audition — only then add `--stage`.

## Notes

- `--db`/`--db-path` override the default `sidekick/library.db` for testing only.
- Reindexing corpora is a HEAVY job — never suggest running it WHILE Live is up; `check-index.py`
  itself refuses in that case.

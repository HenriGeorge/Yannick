---
name: ableton-drum-kit
description: >-
  Build a multi-instrument drum-kit shortlist from a free-text brief (e.g. "punchy techno kicks and
  hats") — a per-role pad list + manual drag-in checklist for an empty Drum Rack. Use when Henri
  says "build me a kit", "give me a drum kit for <brief>", or "shortlist a kit". Wraps
  `scripts/build-drum-kit.py` — NOT a general sample search (a single instrument/loop lookup →
  ableton-library instead), NOT a pool-widening/corpus-freshness tool (→ ableton-library). This
  never writes into Live — the output is a printed drag-in checklist Henri (or a follow-up manual
  step) executes by hand.
---

# Ableton Drum Kit — multi-instrument kit shortlist

Wraps `scripts/build-drum-kit.py`: one free-text brief → a shortlist spanning DISTINCT canonical
roles (kick/snare/clap/hat/percussion/tom/fx), filling the skeleton first and layering extra pads
onto backbone roles only once every role has one.

    python3 scripts/build-drum-kit.py "punchy techno kicks and hats" --pads 6

## When to reach for this vs. `ableton-library`

- **"Build me a kit for <brief>"** → this skill. The output is a MULTI-role shortlist (kick + snare
  + hat + …), not a single-instrument search.
- **"Find me a kick/loop/one-shot"** (ONE instrument, or Henri wants to browse a ranked list rather
  than a ready-to-drag kit) → `ableton-library`'s sample search (`find-samples.py`) instead.
- **"Is the corpus stale?" / "widen the pool"** → `ableton-library`'s freshness check
  (`check-index.py`), not this skill.

## Modes / key flags

- **`--pads N`** — TOTAL pad count (default 4), not "per role". Fewer than the canonical role count
  → skeleton fills in priority order and stops; more → leftover pads layer extra picks onto
  backbone roles (kick/snare/hat/percussion), never fabricating a near-duplicate sample.
- **`--instrument <role>`** — narrows the whole build to ONE role (skips the multi-role skeleton) —
  use only when Henri explicitly wants a single-role kit, not the default multi-instrument one.
- **`--bpm`/`--bpm-tol`** — bpm only constrains loop-eligible roles (percussion/tom/fx); one-shot
  roles (kick/snare/clap/hat) have no meaningful tempo and are never bpm-filtered.
- **`--tier curated|all`** (default all, curated ranked up, never excluded) and `-n/--limit`
  (per-role candidate pool depth) tune retrieval breadth — adjust `-n` up if a role comes back
  short of the requested pad count.
- **`--kind loop|oneshot`** overrides the per-role kind for every role (rare — usually let the
  per-role default stand).

## Workflow

1. Run with the brief + `--pads` Henri wants; if the corpus volume (`/Volumes/Extreme SSD/
   Drums_Extern` by default) isn't mounted, the script fails fast with a clear message — don't
   retry blindly, tell Henri to check the drive.
2. Present the printed Shortlist + drag-in checklist verbatim — each pad names its role + exact
   `abs_path`.
3. The drag-in itself is a MANUAL step (open a Drum Rack, one Simpler per pad, drag each listed
   file) — this skill/script never writes into Live.
4. If a role comes back short (a "pad(s) short of requested" note appears), that's honest — either
   the corpus lacks more distinct candidates for that role, or `-n/--limit` is too shallow; don't
   silently retry with a wider net without telling Henri what changed.

## Notes

- `--root` overrides the corpus root (testing only) — never point this anywhere but the real
  mounted volume for a real kit request.
- Never claim to have heard the resulting kit — the shortlist is symbolic (tag/genre/bpm-scored),
  Henri's ears choose and confirm after the manual drag-in.

## Next step — grooves for a loaded kit

Once a Drum Rack's pads ARE loaded (via the drag-in checklist, or `scripts/load-drum-rack.py`), fill
that track's clip slots with sparse→busy percussion grooves in one command:

    python3 scripts/fill-perc-scenes.py --rack "11 Perc Rack" --scenes 27 --dry-run
    python3 scripts/fill-perc-scenes.py --rack "11 Perc Rack" --scenes 27 --overwrite

Auto-detects the rack's loaded pads (roles assigned by pad NAME — a shaker gets the pulse, a bongo
the downbeats), one DISTINCT groove per scene on a rising density ramp. ADDITIVE by default (an
occupied slot is kept + reported); `--overwrite` replaces. Logic lives in
`sidekick/librarian/percussion_groove.py`; it never saves the set — Henri's ears pick the keepers.

---
name: ableton-documentation
description: >-
  Use when Henri asks how something works in Live, wants the Ableton docs or manual consulted or
  cited, "what do the docs say about X", "look it up", "explain a feature", "teach me", or needs a
  mechanic/technique from the knowledge base — anything ANSWERED from documentation rather than DONE
  in Live. Dispatches the ableton-guru agent over `docs/ableton-docs/` (the bible, the LOM
  reference, the Live 12 manual cited by section). NOT for ingesting a NEW source Henri feeds you
  (→ ableton-tutorial), NOT for touching Live (→ the action front-doors: ableton-daemon / racks /
  library / tidy / answer / watch / drum-kit).
---

# Ableton Documentation — Live-docs lookup front door

Routes a documentation question to the **`ableton-guru`** agent, which reads the knowledge base
under `docs/ableton-docs/` (plus the ambient bible in `sidekick-starter/music-production-bible/`)
and teaches from it. Read-only toward Live — this NEVER touches the bridge, never executes; it
explains, cites, and stops.

## How

**Dispatch the `ableton-guru` agent — don't answer a Live-mechanics question from memory.** The KB is
the ground truth (Henri runs 12.3.2 specifically; the manual and LOM behaviour are version-pinned,
and your recollection drifts). Use the Agent tool with `subagent_type: "ableton-guru"`; leave
`model` unset (the agent's own pinned model wins — never pass the runtime `model` param). The guru
returns the answer + the file/section it came from.

## The corpus (what the guru searches)

- `docs/ableton-docs/bible/00-10` — 11 club-oriented mechanics docs (fundamentals, pipeline, techno
  & house recipes, mixing, MIDI chords, Claude↔Ableton integration, racks/macros, automation,
  templates). Start here for "how does X work".
- `docs/ableton-docs/live12-lom-reference.md` — the Live Object Model surface (what's scriptable).
- `docs/ableton-docs/live12-manual-en.pdf` — the official manual, **local-only, cited by section**
  (e.g. "§23.3.1.2"), never quoted at length, never converted to markdown.
- `docs/ableton-docs/launchkey-mini-mk4.md` · `workflows/` · `style-music.mmd` (tagging taxonomy).
- `sidekick-starter/music-production-bible/` — ambient aesthetics (generative session view, pads/
  texture, reference workflow).
- `docs/ableton-docs/books/` — third-party copyrighted; the guru READS it to inform original
  explanations but NEVER quotes or ingests it. Don't surface its contents verbatim.

## Doctrine routing (never mix)

Club **builds**, ambient **grows** — the two workflow doctrines contradict by design. Mechanics
(routing, racks, automation) apply to both; workflow heuristics do not. If the session type is
unclear and the answer would differ, the guru asks one short question first.

## When NOT this skill

- Henri feeds a NEW article / video / URL to LEARN and file into the KB → **ableton-tutorial**
  (that's the INGEST verb; this skill is the LOOKUP verb).
- The answer requires Live to be TOUCHED, not explained (arm, stage, tidy, load, save) → the action
  front-doors. If a lookup turns into "now do it", hand off — the guru says "that's the sidekick's
  job" and stops.

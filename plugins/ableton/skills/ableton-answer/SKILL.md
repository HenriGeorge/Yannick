---
name: ableton-answer
description: >-
  Check on / arm / disarm the push-reactive Answer-Voices feed (v2.1.1: ALWAYS-ON from Ableton
  startup when the feature flag is set — listens on EVERY role lane, and whichever role-lane track
  Henri has ARMED in Live IS the source the moment it fires; no separate "pick a source" step).
  Fires a Bass + Pads + Lead + Keys + Texture answer, derived from the ACTUAL notes played, staged
  ROW-ALIGNED and ownership-guarded on each OTHER role lane (v2.3: Keys is a target too — a Keys
  answer is the FULL voiced chord/comp, root included; #226: Texture is also a target — a Texture
  answer is a sustained open-fifth drone, root + perfect fifth, modally neutral; every role is both a
  potential source AND target, the armed source's own lane is the only one ever skipped). v2.2: FAN-OUT — a role matching 2+ live tracks (e.g.
  Henri intentionally keeping both `11 Pads` and `14-Pads Rack`) answers into EVERY one of them,
  never a refusal. Use when Henri asks "is the answer-voices feed running?", "arm the answer feed",
  "what did the answer feed just do?", "stop answering my chords", or "any nudges from the answer
  feed?". Wraps `scripts/answer-voices.py` (status + start + stop) — NOT the gateway daemon PROCESS
  itself (→ ableton-daemon), NOT rack drift/tuning (→ ableton-racks), NOT the chain-rebalance
  watcher (→ ableton-watch — a different feed entirely). Enabling the FEATURE (making it armable at
  all) is the daemon's own env-gated flag (default OFF) — see Modes below.
---

# Ableton Answer — Answer-Voices (fire-a-chord, get-an-answer) front door

Wraps `scripts/answer-voices.py` — `status` (query the running feed over the daemon's Unix socket),
`start` (ARM the feed's role-lane listeners — see "Arm-to-source" below, NOT "pick which role is the
source"), and `stop` (disarm entirely). PROPOSE, NEVER APPLY: armed or not, this feed only ever ADDS
clips at the fired source's OWN row on the target lanes (row-aligned, see below) — it never fires,
never force-overwrites a user clip, never saves the `.als`.

## Arm-to-source (v2.1 — replaces the old fixed-source model)

There is no longer a "pick the source role" step. `AnswerFeed` listens on EVERY resolved role lane
(`Keys`/`Bass`/`Pads`/`Lead`/`Texture` by default) for `playing_slot_index` pushes. When ANY of those
tracks fires a clip, the feed checks Live's own **Arm** state (the same red record-arm button/state
`get_arm`/`arm()` already read/write) on THAT track:

- **Armed** → it IS the source for this fire. Every OTHER role lane gets an answer (never the
  source's own lane); the armed track can change fire-to-fire — arm Bass instead of Keys and Bass
  becomes the source on its next fire, no reconfiguration needed. v2.3: this is now fully
  symmetric — Keys is ALSO a target (a Keys answer = the full voiced chord, root included, unlike
  Pads which drops it), so arming Bass now answers Keys too, not just Pads/Lead. #226: Texture is
  ALSO a target (an open-fifth drone, root + perfect fifth, modally neutral) — arming any role now
  answers Texture too.
- **Not armed** → the fire is a no-op for this feed (some other, unarmed role lane just playing
  normally — never mistaken for an answer request).

So "arming the answer feed" (this skill's `start`) means **starting the LISTENERS on every role
lane**, not choosing a source — the actual source is decided live, per fire, by which track Henri
has armed in Live at that moment.

## Fan-out (v2.2 — a role now answers into EVERY matching lane)

**A role is one-to-MANY, not one-to-one.** If 2+ live tracks match a role (Henri intentionally keeps
both `11 Pads` and `14-Pads Rack` — a deliberate duplicate, not a naming mistake to clean up), the
feed treats ALL of them as valid, simultaneously:

- **LISTEN** — every matching track becomes a valid ARM-able source. Arming EITHER `11 Pads` or
  `14-Pads Rack` and firing it makes that ONE track the source for that fire (arm-to-source still
  picks exactly one source per fire — fan-out is about the TARGET side, and about which tracks can
  ever become a source, not about firing multiple sources at once).
- **TARGET** — the derived voice for a fanned role is staged into EVERY matching track, each with the
  SAME independent guards (row-aligned, ownership-marked, never-overwrite-playing/user-clip). Arming
  `11 Pads` as the source still fans the Pad voice into `14-Pads Rack` (and vice versa) — but NEVER
  back onto the armed source's own track, exactly like the single-match case.
- **Never a refusal.** Before v2.2, 2+ matches for a role was an ambiguity error (skip, nudge "N
  tracks match role X"). That refusal is GONE — a role matching multiple tracks now always answers
  into all of them. The only thing that still nudges (and skips) is a role matching **ZERO** tracks.
- **Accepted consequence:** an accidental near-duplicate name (e.g. a stray `"808 Bass"` that also
  tolerant-matches role `Bass`) now fans out too, rather than being refused as ambiguous. This is
  additive and deletable (PROPOSE-NEVER-APPLY still holds — an unwanted fanned clip is just deleted
  by hand), so the failure mode is "one extra clip to clean up," never data loss or a silent wrong
  pick.

## Always-on (v2.1 "Feature D")

With the feature flag set, the daemon auto-arms this feed on startup/reconnect — Henri never has to
run `start` by hand in the common case. `status` also LAZILY RE-ARMS on every poll if a prior boot-arm
failed (e.g. it raced Live still launching) — a later `status` call self-heals it, no daemon restart
needed. `start`/`stop` below remain useful for a manual re-arm with non-default `--targets`, a
different `--session`, or an explicit disarm.

## Modes

- **`status`** — `python3 scripts/answer-voices.py status`: prints whether the feed is currently
  armed, its role lanes (every track it's listening on — Keys/Bass/Pads/Lead/Texture by default, NOT just
  "the source", since arm-to-source means any of them could become one), its target roles, the
  session it's persisting under (if any), and its most recent nudges (blocked-chord refusals,
  occupied-target skips, a role lane that couldn't be resolved at all — a role matching 2+ tracks is
  no longer a nudge-worthy event, see Fan-out below, it just answers into all of them). Start
  here for "is it on?" or "why didn't my chord get an answer?". Queries the daemon's `answer_status`
  request kind over its Unix socket — the SAFE, socket-only path; it deliberately never falls back to
  constructing a raw OSC transport. ⚠️ The CLI's own `source role: ...` status line is STALE (a v2
  leftover reading a `source_role` key the daemon no longer returns — arm-to-source has no single
  fixed source to report) — read the printed **role lanes** instead; that's the real armable set.
- **`start [--targets Bass,Pads,Lead,Keys,Texture] [--session SESSION_ID]`** — ARMS the feed: resolves
  every configured role lane by name (tolerant of Henri's `N-<Role> Rack` track-naming convention, e.g.
  `13-Keys Rack`/`12-Lead Rack`/`7 Bass`/`11 Pads`) and starts listening for `playing_slot_index` on
  all of them. Omit `--session` to skip persistence (the feed still answers, it just won't be
  idempotent-suppressed across a restart or recorded in `grid_placements` — every fire re-answers
  fresh). ⚠️ The CLI's `--source` flag still exists for back-compat but is a NO-OP — the daemon
  ignores it entirely (arm-to-source decides the source at fire time, not at arm time); don't pass
  it expecting it to do anything. ⚠️ The CLI's own `--targets` default is still `Bass,Pads` (a
  pre-existing, unrelated staleness — missing **Lead**, **Keys**, and now also **Texture**) — the
  ALWAYS-ON boot-arm path uses the real default (`Bass,Pads,Lead,Keys,Texture` as of #226) since it
  calls `AnswerFeed.start()` with no `--targets` override at all; a MANUAL `start` with no `--targets`
  flag will narrow to Bass+Pads only. Pass `--targets Bass,Pads,Lead,Keys,Texture` explicitly for a
  manual re-arm that matches the boot-arm default.
- **`stop`** — disarms; stops listening on every role lane. Never touches anything already staged —
  clips the feed added earlier stay exactly where they are.
- **Enabling the FEATURE itself is NOT a subcommand here** — it's the daemon's own env-gated flag,
  default OFF: `SIDEKICK_ANSWER_VOICES=1 python -m sidekick.gateway restart` to enable, a plain
  `python -m sidekick.gateway restart` (no env var) to disable. Route THAT specific action through
  `ableton-daemon` since it's a daemon restart, not a new mechanism this skill wraps. `start` will
  report `not_enabled` if you try to arm before the feature flag is on.

## What "answering" actually does

1. Henri arms a role-lane track in Live (Keys/Bass/Pads/Lead/Texture — any of them) and fires a chord
   clip on it.
2. The feed checks that track's arm state (see "Arm-to-source" above); if armed, THAT clip's ACTUAL
   notes are read (never a name-based guess) and the chord identified — reusing the same
   anti-inversion recognizer the note→chord feature ships (never mistakes the lowest sounding note
   for the root). A clip holding a real chord PROGRESSION (multiple distinct chords by onset, not
   just a re-struck repeat) follows each resolved chord in sequence rather than blocking outright.
3. **Bass** = a note at the chord's de-inverted root, low register (~MIDI40). **Pad** = the chord's
   OTHER real played pitch classes (never synthesized), deduped across octaves, mid register
   (~MIDI55-72). **Lead** (v2.1) = a high-register voice (~MIDI72-84). **Keys** (v2.3) = the FULL
   voiced chord — every real played pitch class, root included, mid register (~MIDI48-72) — the only
   voice that's a full comp, not a single note. **Texture** (#226) = a sustained open-fifth drone —
   the de-inverted root plus a literal perfect fifth (root+7 semitones) above it, register ~MIDI48 —
   deliberately MODALLY NEUTRAL (no third), so a major and minor source chord sharing a root answer
   identically. All five sustained for the clip's own duration.
4. Each derived voice is staged ROW-ALIGNED (v2 F1) — at the SAME scene row/slot the source clip
   fired from, on its role's target lane, NOT a first-empty-slot scan. F2's ownership guard: a
   currently-PLAYING clip at that row is never touched (deferred with a nudge); an occupied-but-not-
   playing row is overwritten ONLY if its name already carries the `" answer — "` K1-ownership
   marker (durable across daemon restarts); anything else occupied is a user clip and is skipped
   with a nudge. An empty row stages freely.

## The arm contract, in one line

**Source = a recognized chord clip (3–4 notes) on a role lane** (Keys/Bass/Pads/Lead/Texture). A non-role
track, a single-note clip, an empty slot, or a chord whose pitch-class set is genuinely ambiguous all
stage NOTHING — by design, never a fabricated guess. See "When it refuses" below for the full list;
offline regression coverage for each of these lives in `sidekick/gateway/tests/test_answer_feed.py`
(feat/answer-voices-live-tests, Task C — `.claude/rules/ableton-testing.md`).

## When it refuses (and why that's correct, not a bug)

- **A non-role track fires, or the firing track isn't ARMED** — never treated as a source at all
  (see "Arm-to-source" above); a complete no-op, nothing read, nothing nudged.
- **Chord not recognized** (`quality=="other"`, e.g. a single note) or **genuinely ambiguous** (the
  pitch-class set ties between two chord templates) on a SINGLE-chord clip — the WHOLE derivation
  refuses rather than guessing. An EMPTY fired slot (no notes at all) refuses the same way. Check
  `status`'s nudges for the exact reason.
- **A multi-chord PROGRESSION clip** (v2 F3 — 2+ DISTINCT pitch-class-set onset groups, not just a
  chord re-struck twice) does **NOT** blanket-block: each onset group resolves independently, an
  unresolved one is SKIPPED (a gap in the following line, nudged) while every other resolved chord
  still gets its note. Only blocks entirely if NONE of the groups resolve.
- **The target row is occupied and NOT this feed's own clip** — F2's ownership guard: a row that's
  currently PLAYING is deferred (nudged, never interrupted); a row holding someone else's clip (no
  `" answer — "` name marker) is skipped (nudged) rather than overwritten. That ONE role's voice is
  skipped; the OTHER targets still answer normally if their rows are free/K1-owned.
- **An UNRESOLVED target role name** at fire time (ZERO tracks match, e.g. the role's only track got
  renamed away) — that role is skipped and nudged; the OTHER targets still answer (never aborts the
  whole fire for one missing role). A role matching 2+ tracks is NO LONGER refused — see Fan-out
  above; it answers into every match instead.
- **Same chord fired again at the same row, in the same session** (with `--session` set) —
  suppressed, not re-staged, so repeatedly re-triggering the same clip doesn't flood the lane with
  duplicates. A DIFFERENT chord, or the same chord in a DIFFERENT row, always answers again.

## Notes

- **No rate-limit, no cap** — row-aligned staging means each fire only ever touches ONE row per
  target lane (the source's own row); the accepted bound is Henri's own scene count plus manually
  clearing/deleting clips he doesn't want.
- **The SOURCE track needs no by-name re-resolution** — the OSC push that triggers a react already
  carries the physical track index that fired (ground truth), so a source-lane rename mid-session
  changes nothing. The TARGET roles, by contrast, ARE re-resolved BY NAME fresh on every single
  react (R3, and now fanned across every match — see Fan-out above) — a target-lane rename mid-session
  is tolerated; a target that's been renamed away entirely (zero matches left) is reported as a nudge
  for that ONE role, never a crash and never aborting the whole fire.
- Henri's role-track naming convention (a leading `N-` or `N ` number header, an optional trailing
  ` Rack`/` Rack vN` suffix — e.g. `13-Keys Rack`, `7 Bass`) is matched by a SCOPED tolerant matcher
  (`answer_feed._matches_role_lane`) used ONLY by this feed — it never widens the shared
  `precondition._matches_target` matcher every staging/kit module also relies on.
- Never edit `role_specs.py`/a `.adg`/anything Live-side based on what this skill shows — it's
  purely observational (`status`) or a runtime arm/disarm toggle (`start`/`stop`); the actual
  derive-and-stage logic lives entirely in the daemon's push-handler thread.

## Known limitations (documented by design, not bugs to fix silently)

- **Moving/deleting a source clip strands its prior answers (v2.2 "S4" — Henri's decision: document,
  don't auto-clean).** The feed is FIRE-REACTIVE, not MOVE-AWARE: it only ever reacts to a
  `playing_slot_index` push at the moment a clip fires. If Henri later moves the source chord to a
  different row/scene, or deletes it outright, the answer clips it already staged at the OLD row stay
  exactly where they are — the feed has no way to know the source that produced them moved, and
  doesn't watch for that. Henri deletes orphaned answer clips himself (they're clearly marked
  `" answer — "`, so they're easy to spot and safe to remove — PROPOSE-NEVER-APPLY means nothing else
  depends on them existing). This is NOT planned to become automatic; a "watch for a moved/deleted
  source and clean up its old answers" feature would need its own design (it isn't this feature's
  job).
- **A progression clip's answer clip NAME reflects only the FIRST chord (cosmetic).** When a clip
  holds a multi-chord progression (v2 F3), the derived voice's NOTES correctly follow every resolved
  chord at its own onset (see "What answering actually does" above) — but the clip's NAME/label is
  generated once, from `events[0].chord` (the first chord in the sequence) only. So a 2-chord
  progression answer might be named `"Bass answer — Cmaj"` even though its second note is actually a D
  minor root — the SOUND is correct, the LABEL is a minor cosmetic gap. Worth fixing if it's
  confusing in practice; not tracked as broken behavior.

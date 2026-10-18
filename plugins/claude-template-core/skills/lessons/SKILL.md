---
name: lessons
description: Surface relevant past lessons from docs/lessons.md on demand, by keyword overlap with the current task. Use at the start of a non-trivial task, before a design or a risky change, or whenever you want to check "have we learned something about this before?" Replaces the former always-on per-prompt lesson injection — now pulled when wanted, not pushed every turn.
---

# lessons — on-demand recall from docs/lessons.md

`docs/lessons.md` is the accumulated wins-and-lessons log (`/dev-reflect` appends to it; `/improve`
mines it). It is no longer pushed into every prompt. Pull from it when it helps:

1. **Pick the task's keywords** — the nouns/verbs that name what you're about to do (the hook/file/gate
   touched, the stack, the failure mode), lower-cased.
2. **Find matching lesson blocks.** Each lesson is a `###`-headed block. Grep the log for your
   keywords, e.g. `grep -niE 'worktree|merge|rebase' docs/lessons.md`, then read the surrounding
   block for each hit. Prefer blocks whose heading or `**Seen**:` count signals a recurring lesson.
3. **Surface the few that actually apply** — quote the heading + the one-line takeaway of the top 2–4
   matches, with their numbers, so the relevant history is in view before you act. Skip the rest; a
   wall of loosely-matched lessons is noise.
4. **Verify before relying.** A lesson reflects what was true when written — if it names a file, gate,
   or flag, confirm it still exists in the current tree before acting on it (the log can lag the code).

## Verify

- `test -f docs/lessons.md` — the log exists (seeded by `setup.sh`).
- A keyword grep returns `###` blocks you can quote by number.

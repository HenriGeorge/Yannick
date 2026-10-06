> Command for priming Claude Code with core knowledge about your project

# Prime Context for Claude Code

## GATE-0 baseline (do this FIRST, before reading or editing anything)

- `git log --oneline -10` — get the recent-history context for this project. (The `session_start`
  hook already ran `git fetch` and injected the behind-count / stale-local-`main` warning — read
  that; don't re-fetch here.)
- If you are NOT already inside a `.claude/worktrees/` worktree, **`EnterWorktree` now** — it
  branches fresh off the default remote branch (already synced, so no raw `git pull` /
  `git reset --hard`). All edits and commits happen in the worktree; `session_prime_gate` blocks
  mutations until you're in one and primed. A repo without worktree infra degrades to a no-op.

Use the command `tree` to get an understanding of the project structure.

Start with reading the CLAUDE.md file if it exists to get an understanding of the project.

Read the README.md file to get an understanding of the project.

Read key files in the src/ directory

> List any additional files that are important to understand the project.

Invoke the `using-superpowers` skill so the Design → Code → Prove methodology engine is loaded
for the session before any work begins (the canonical workflow lists this as a PRIME step, but
nothing else enforces it — priming is the one hard-gated point where it reliably happens).

Explain back to me:
- Project structure
- Project purpose and goals
- Key files and their purposes
- Any important dependencies
- Any important configuration files

Finally, mark the session primed so the `session_prime_gate` hook lets mutations through:

```bash
mkdir -p .claude/state && : > .claude/state/primed
```

(This `touch` is exempt from the gate — it writes under `.claude/state/`. The marker proves
`/prime-core` ran; a fresh worktree re-primes once.)
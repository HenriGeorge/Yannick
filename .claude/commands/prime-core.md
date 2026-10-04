> Command for priming Claude Code with core knowledge about your project

# Prime Context for Claude Code

Use the command `tree` to get an understanding of the project structure.

Start with reading the CLAUDE.md file if it exists to get an understanding of the project.

Read the README.md file to get an understanding of the project.

Read key files in the src/ directory

> List any additional files that are important to understand the project.

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
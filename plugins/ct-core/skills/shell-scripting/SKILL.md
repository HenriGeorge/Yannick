---
name: shell-scripting
description: 'Write or harden a bash script defensively, then verify it shellcheck-clean. Use when creating or editing any *.sh / bin/*.sh / shell hook, or on "harden this script", "lint bash", "shellcheck".'
---

# Shell Scripting

Write bash that fails loud, quotes safely, and cleans up after itself — then prove it with
`shellcheck`. This repo's own stack is bash + stdlib-python; treat every script you touch as
production.

## When to use

- Creating or editing any `*.sh`, `bin/*.sh`, or a shell hook.
- "Harden this script", "why does this bash break", "lint bash", "shellcheck".
- NOT for the sourced test files (`tests/test_*.sh`) — they deliberately omit `set -euo pipefail`
  because `run.sh` sources and aggregates them; adding it there breaks the harness.

## Workflow

### 1. Apply the defensive checklist

- **`set -euo pipefail`** at the top of every non-sourced script. `set -u` alone (seen in
  `bin/git-merge-docstamp.sh`, `bin/build-hook-wiring.sh`) catches unset vars but silently swallows
  a failed command or broken pipe.
- **Quote every expansion**: `"$var"`, `"${arr[@]}"`. Unquoted `$var` is safe *only* inside `[[ ]]`
  or `$(( ))`. Guard maybe-empty arrays: `${arr[@]+"${arr[@]}"}`.
- **`[[ ]]` over `[ ]`** in bash-only scripts (no word-splitting, supports `=~`, `&&`). Keep `[ ]`
  only where POSIX-portability is deliberate.
- **`local`** every function variable — no accidental globals.
- **`mktemp` + `trap` cleanup, always paired**: `tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT`. Bare
  `mktemp` with no trap orphans temp files on error.
- **Never a leading `cd` for cross-repo/dir work** — use `git -C <abs-path>` / absolute paths (R8);
  a leading `cd` mis-resolves under the auto-mode classifier.
- **stdlib only** — hooks/scripts every scaffold inherits stay dependency-free (bash + coreutils).

### 2. Verify with shellcheck

```bash
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck path/to/script.sh
else
  echo "shellcheck not installed — checklist applied, lint skipped (brew install shellcheck)" >&2
fi
```

Run on the specific file(s) you changed, not the whole tree. Fix each finding and re-run until
clean; add a scoped `# shellcheck disable=SCxxxx` (with a one-line why) only for a deliberate,
justified exception.

## Rules

- Log progress/errors to **stderr**, data to **stdout** — keeps a script pipeable.
- Fail loud: exit non-zero on any error path; never mask a failure with `|| true` unless intended.
- Don't add a dependency for what coreutils already does.

## Gotchas

- **`set -e` is not a safety net.** It ignores failures in `if`/`&&`/`||` conditions and in the
  left side of a pipe (without `pipefail`). Check critical commands explicitly.
- **`shellcheck` absent** → degrade gracefully (guard with `command -v`); apply the checklist by
  hand and say lint was skipped. Never claim "shellcheck-clean" without running it.
- **Sourced files differ.** A script meant to be `source`d (like `tests/lib/assert.sh`) must not
  `set -e`/`exit` — it would kill the caller. The checklist's `set -euo pipefail` is for scripts
  run as a command.

## Verdict

`shellcheck` ran exit 0 with no warnings AND the defensive checklist applied → **PASS**.
Any shellcheck warning/error, OR shellcheck skipped while claiming clean → **FAIL**.

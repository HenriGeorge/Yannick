# RTK — token-optimized command output (on by default)

Last updated: 2026-10-17 10:43

RTK ("Rust Token Killer") is an optional CLI proxy that compresses the output of common dev commands
(git, cargo/npm/pnpm, test runners, linters, psql, aws, …) **before it reaches the LLM context** —
typically 60–90% fewer output bytes on noisy commands. It's a single Rust binary with no runtime
dependencies. This template ships RTK **ON by default** (force-on at scaffold — `setup.sh` runs
`rtk init` unconditionally, telemetry OFF); set `RTK_ENABLE=0` before setup to opt a project out.

> Skill (relevance-fired): the `rtk` plugin skill.

## How it integrates (instruction mode — `RTK_HOOK=0`)

> The default is now the global `-g` auto-rewrite hook (git excluded) — see "Auto-rewrite default"
> below. This section describes the `RTK_HOOK=0` instruction-mode fallback.

At **project scope**, plain `rtk init` is **instruction-based**: it writes a `<!-- rtk-instructions -->`
block into `CLAUDE.md` ("Golden Rule: prefix commands with `rtk`") and a `.rtk/filters.toml`
template. It does **NOT** install a `PreToolUse` hook — verified: `rtk init --hook-only` only applies
with `--global`. So in instruction mode RTK never sits in this project's tool-call chain; Claude simply *chooses* to run
`rtk git status` instead of `git status`, and RTK's rewrite is purely **additive** (it prepends
`rtk `; unknown commands pass through unchanged).

Consequence for safety: the template's `PreToolUse` guard chain (H1–H11, delivered via the hooks
plugin) still inspects the real command Claude runs. Because the `rtk ` prefix never hides the
dangerous substring, every guard still fires on the prefixed form — a force-push to `main`, a
destructive `psql` DROP, a non-conventional commit, and `rm -rf` on a read-only path are all still
blocked with RTK enabled.

The global `rtk init -g` mode (a real `PreToolUse` hook that rewrites commands to their `rtk ` form)
is now the **default** for this template: `setup.sh` runs `rtk init -g` and records the choice with a
`.rtk/hook-mode` marker. It also excludes `git` from the rewrite (adds `git` to `[hooks]
exclude_commands` in rtk's machine-global `config.toml`) so a worktree-isolated `git` is never turned
into `rtk git` — which the harness refuses, deadlocking the two guards (#709). Pass `RTK_HOOK=0` to
`setup.sh` to opt back to instruction-only mode (no hook, no marker) — see "Auto-rewrite default"
below.

### Global `rtk init -g` coexistence — still guard-safe

A user may run `rtk init -g` independently, installing a real global `PreToolUse` hook that rewrites
commands machine-wide. The concern: can that global hook, ordered before/after this project's
`pre_tool_use.py`, let a dangerous command slip past H1–H11?

Characterized against Claude Code's documented multi-hook semantics
([code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks)), coexistence is **guard-safe
under all orderings**, for two independent reasons:

- **Each hook sees the ORIGINAL command, not the other's rewrite.** All matching `PreToolUse` hooks
  run **in parallel**, each receiving the **same original `tool_input`** — there is no chaining that
  feeds one hook's output into another. RTK's global hook can `updatedInput`-rewrite the command that
  ultimately *executes*, but it cannot change what the template guard *inspects*: `pre_tool_use.py`
  always sees the raw `git push --force origin main`, matches, and blocks.
- **Blocking is a logical OR.** If **any** matching hook denies (exit 2), Claude Code blocks the tool
  regardless of what the other hooks decided or the (non-deterministic) order they ran in. So the
  template guard's deny is authoritative even if RTK's hook would have allowed the command.

The one residual risk is unchanged from the project-scope case: RTK's rewrite is *additive* today
(`git … → rtk git …`), so even in the hypothetical where the guard *did* see the rewritten form it
still matches. A future RTK that rewrote in an *obfuscating* way (subshell/encoding hiding the
dangerous substring) could defeat a regex guard — but only for what *executes*. Version-pin with
`brew pin rtk` if that matters to you.

The invariant holds because the template guard yields the **identical block decision** on the
original command and on RTK's `rtk `-prefixed form, so neither hook order nor RTK's rewrite changes
the outcome.

### Auto-rewrite default (`-g` hook) — git excluded

By default rtk's own `-g` `PreToolUse` hook rewrites commands to their `rtk ` form automatically.
Safety is unchanged (the coexistence analysis above holds — the template guards still see the
original command and block danger). The one historical cost was **usability**: in a worktree-isolated
session the worktree-isolation git guard over-refuses rtk-rewritten `git`/`gh`/`bash` forms ("names
git in a form too complex to verify it stays inside the worktree"), deadlocking the two guards
(#709, lessons #418/#428). That is why `git` is **excluded** from the rewrite (`[hooks]
exclude_commands = ["git"]`): `git` runs raw everywhere, so the deadlock never arises and the
remaining ~468K of grep/cat/ls/… output still compresses — in worktrees too, where most BUILD work
runs. The absolute-path escape (`/usr/bin/git`) remains available if a stray `rtk git` ever appears.

With `RTK_HOOK=0` (instruction mode), prefixing is **not** automatic — the agent must choose to type
`rtk ` itself, per this doc's instruction-mode guidance (the `rtk_nudge` PostToolUse WARN that once
observed a raw known-RTK command was removed in the hook diet — there is no hook backstop for the
excluded `git` verb or for instruction mode; this prose is the only discipline now). Note: rtk's own
`~/.claude/RTK.md` describes the `-g` hook mode and claims commands are "automatically rewritten" —
true by default here (except the excluded `git`), but **not** in an `RTK_HOOK=0` instruction-mode
scaffold, where prefixing stays manual.

## Enable / disable

```bash
# Prerequisite (assumed on PATH — the template does NOT vendor it):
brew install rtk            # or: cargo install rtk

# At scaffold time: RTK is enabled automatically (no prompt). Preset RTK_ENABLE=0 to opt out.
# Later, in an existing project:
RTK_TELEMETRY_DISABLED=1 rtk init      # writes the CLAUDE.md block + .rtk/filters.toml
rtk telemetry disable                  # belt-and-suspenders (see Telemetry)

# Disable: remove the rtk-instructions block from CLAUDE.md and delete the .rtk/ directory.
rtk init --show                        # inspect current state
```

`permissions.allow` in the scaffold always includes `Bash(rtk *)` so the agent can invoke RTK without
a prompt — inert when RTK is disabled.

## Telemetry — forced OFF

RTK telemetry is opt-in upstream (anonymous daily ping, GDPR-compliant, no source/paths/args/secrets).
This template **forces it off** whenever it runs `rtk init` (`RTK_TELEMETRY_DISABLED=1` + an explicit
`rtk telemetry disable`), so a scaffolded project never opts a downstream user in. Hard override any
time: `export RTK_TELEMETRY_DISABLED=1`. Erase local data: `rtk telemetry forget`.

## Caveats

- **Green ≠ works.** RTK filters/summarizes output — occasionally a filter can drop a line you needed.
  If a command's compressed output looks wrong, re-run it raw (drop the `rtk ` prefix) to compare.
- **Custom filters need trust.** Project-local `.rtk/filters.toml` filters are trust-gated
  (`rtk trust`); never `--trust-filters` on a repo you don't control.
- **Savings are output-bytes, not your bill.** Bash output is one input among prompt + history +
  system prompt; RTK reduces one contributor, it doesn't linearly cut cost.

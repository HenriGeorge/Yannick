# RTK — token-optimized command output (on by default)

Last updated: 2026-10-19 13:49

RTK ("Rust Token Killer") is an optional CLI proxy that compresses the output of common dev commands
(git, cargo/npm/pnpm, test runners, linters, psql, aws, …) **before it reaches the LLM context** —
typically 60–90% fewer output bytes on noisy commands. It's a single Rust binary with no runtime
dependencies. This template ships RTK **always on** — `setup.sh` runs `rtk init` unconditionally,
telemetry OFF; there is no opt-out knob (#1410 — a former `RTK_ENABLE=0` opt-out was cosmetic, since
the rewrite mechanism it was meant to disable turned out to be machine-global; see below for how
that's fixed now).

> Skill (relevance-fired): the `rtk` plugin skill.

## How it integrates — a plugin hook, not rtk's own global one

RTK's rewrite used to be `rtk init -g`: a real `PreToolUse` hook that **rtk itself** installs into
the **machine-global** `~/.claude/settings.json`. That had three problems, one root cause (the
mechanism lived outside the project): a per-repo opt-out couldn't actually opt a repo out (#1410);
`setup.sh` patched that global file silently with no `--dry-run` preview (#1411); and tracking "is
the hook installed" needed a per-repo marker that could never reflect the real, global state
(#1412). Worse, a **claude.ai cloud session has no persistent machine-global settings.json at
all** — each session is a fresh sandbox — so `rtk init -g` structurally cannot work there.

The fix: the rewrite now ships as **`plugins/ct-hooks-py/hooks/rtk_rewrite.py`** — a small,
template-authored `PreToolUse` (matcher `Bash`) hook, wired the same way every other hook in this
plugin is (via `hooks.json` locally, and via the scaffold's own `.claude/settings.json` for a fresh
clone with no plugins installed — including a cloud clone). It ships WITH the project, so it works
identically on a laptop and in a cloud sandbox. On every Bash call it:

1. no-ops (exit 0, no output) if the command isn't Bash, if `rtk` isn't on PATH, if the command
   is already prefixed `rtk `, or if it's a `git`/`/usr/bin/git` command — **excluded** so a
   worktree-isolated `git` is never rewritten into an `rtk git` form the worktree-isolation guard
   refuses, deadlocking the two guards (#709). This REPLACES the old machine-global `config.toml
   [hooks] exclude_commands = ["git"]` patch with the same exclusion done locally in the hook.
2. otherwise runs `rtk hook claude` with the SAME stdin JSON and relays its stdout verbatim (the
   rewrite JSON, if any) — but ALWAYS exits 0 itself, regardless of `rtk hook claude`'s own exit
   code: this hook rewrites, it never gates, so a non-zero exit from rtk's own internal error must
   never turn into a PreToolUse BLOCK here. The actual rewrite decision still comes from rtk
   itself, just invoked from inside a hook this template controls instead of one rtk installed
   globally.

Fail-open: any exception, or `rtk` erroring, exits 0 with no output — a bad rtk day never blocks a
Bash call. `_rtk_enable` in `setup.sh` now only handles the project-local half (`rtk init
--auto-patch` for the `CLAUDE.md` "prefix with rtk" block + `.rtk/filters.toml`, and forcing
telemetry off) — it prints ONE line on every run: `RTK: rewrite hook wired via plugin
(rtk_rewrite.py); global rtk init -g no longer used` (`--update --dry-run` previews the identical
line without calling anything — the #1411 fix). There is no `.rtk/hook-mode` marker to read or
write anywhere anymore (the #1412 fix) — the hook is simply present with the plugin, or absent
without it.

### A leftover global hook from an earlier template version is harmless

If `~/.claude/settings.json` still carries `"command": "rtk hook claude"` from before this change,
`_rtk_enable` WARNs (fail-soft grep, never an error if the file's missing) but does not touch it —
editing a machine-global file from inside a project script is exactly the kind of side effect this
redirect removes. Running both hooks is safe: `rtk hook claude` is idempotent on an already-`rtk
`-prefixed command (verified: feeding it a command already starting with `rtk ` produces no
output), so even if the global hook fires first (or both fire — `PreToolUse` hooks run in parallel
against the SAME original input, never chained) the second attempt is a no-op. Remove the leftover
entry by hand if you'd rather not carry it — one line (keeps every other hook, writes a copy first):

```bash
cp ~/.claude/settings.json ~/.claude/settings.json.bak && jq '.hooks.PreToolUse |= map(.hooks |= map(select(.command != "rtk hook claude")) | select(.hooks | length > 0))' ~/.claude/settings.json.bak > ~/.claude/settings.json
```

Consequence for safety either way: the template's `PreToolUse` guard chain (H1–H11, delivered via
the hooks plugin) always inspects the real command Claude runs, not RTK's rewrite — every guard
still fires on the prefixed form (a force-push to `main`, a destructive `psql` DROP, a
non-conventional commit, `rm -rf` on a read-only path), because all `PreToolUse` hooks see the
SAME original `tool_input` in parallel (no chaining), and because blocking is a logical OR: any
hook's deny wins regardless of what rtk's rewrite would have allowed. See
[code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks) for the documented
multi-hook semantics this relies on.

### In a claude.ai cloud session

`plugins/ct-hooks-py/hooks/cloud_session.py` (SessionStart, cloud-only) installs `rtk` itself when
it's missing — a fresh cloud sandbox has nothing pre-installed — using rtk's own `install.sh`. The
script is fetched from the pinned release **tag** (`refs/tags/<RTK_VERSION>/install.sh`, not a moving
branch) and its sha256 is checked against `RTK_INSTALL_SHA256` before it runs; a mismatch is refused
(`rtk: install failed (checksum mismatch)`). The installer also receives the pinned `RTK_VERSION`, which
skips its "latest release" lookup (the GitHub API 403s behind the cloud proxy). Bumping the version
means re-pinning both constants in `cloud_session.py` (`curl -fsSL <url> | shasum -a 256`). The hook
notes `rtk: installed` or `rtk: install failed (<status>)` in its systemMessage; silent when `rtk` is
already present. `rtk_rewrite.py` itself needs no cloud-specific code — once `rtk` is on PATH, the
plugin hook behaves identically to the local case.

## Enable / disable

```bash
# Prerequisite (assumed on PATH — the template does NOT vendor it):
brew install rtk            # or: cargo install rtk

# At scaffold time: RTK is enabled automatically (no prompt, no opt-out — #1410).
# Later, in an existing project:
RTK_TELEMETRY_DISABLED=1 rtk init      # writes the CLAUDE.md block + .rtk/filters.toml
rtk telemetry disable                  # belt-and-suspenders (see Telemetry)

# There is no per-repo disable for the rewrite — it's a plugin hook now, so it's simply present or
# absent with the plugin itself. Removing just the project-local instruction block:
# delete the rtk-instructions block from CLAUDE.md and the .rtk/ directory.
rtk init --show                        # inspect current state
```

The scaffold writes `Bash(rtk *)` into `permissions.allow`, and `setup.sh --update-hooks` backfills it
into a repo scaffolded before the entry existed (`_merge_permissions_allow`, add-only), so the agent
can invoke RTK without a prompt.

## Telemetry — forced OFF

RTK telemetry is opt-in upstream (anonymous daily ping, GDPR-compliant, no source/paths/args/secrets).
This template **forces it off** whenever it runs `rtk init` (`RTK_TELEMETRY_DISABLED=1` + an explicit
`rtk telemetry disable`; if that persistent write fails, `_rtk_enable` prints `RTK-WARN: rtk telemetry
disable failed` and carries on — the init call itself already ran with `RTK_TELEMETRY_DISABLED=1`), so a
scaffolded project never opts a downstream user in. Hard override any
time: `export RTK_TELEMETRY_DISABLED=1`. Erase local data: `rtk telemetry forget`.

## Caveats

- **Green ≠ works.** RTK filters/summarizes output — occasionally a filter can drop a line you needed.
  If a command's compressed output looks wrong, re-run it raw (drop the `rtk ` prefix) to compare.
- **Custom filters need trust.** Project-local `.rtk/filters.toml` filters are trust-gated
  (`rtk trust`); never `--trust-filters` on a repo you don't control.
- **Savings are output-bytes, not your bill.** Bash output is one input among prompt + history +
  system prompt; RTK reduces one contributor, it doesn't linearly cut cost.
- **The absolute-path escape** (`/usr/bin/git`) is excluded by `rtk_rewrite.py` the same as a bare
  `git`, so it always runs raw too.

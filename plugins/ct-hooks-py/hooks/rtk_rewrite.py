#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""PreToolUse (Bash) hook — rtk's own command-rewrite hook, wired as a template-authored plugin
hook instead of rtk's machine-global `-g` ~/.claude/settings.json entry (#1410/#1411/#1412). The
global `-g` form never worked in a claude.ai cloud session, which has no persistent machine-global
Claude Code config to patch — this hook ships WITH the project instead, so it works there too.

Delegates the actual rewrite decision to `rtk hook claude` (reads the SAME PreToolUse JSON from
stdin, emits whatever updatedInput/decision JSON it wants on stdout) — this script only decides
WHETHER to invoke it, no-op (exit 0, no output) for:
  - any tool other than Bash (rtk only proxies shell commands);
  - rtk absent from PATH (soft-skip, same as every other optional-tool hook in this plugin);
  - a `git`/`/usr/bin/git` command — excluded so a worktree-isolated `git` is never rewritten into
    an `rtk git` form the worktree-isolation guard refuses, deadlocking the two guards (#709); this
    REPLACES the old machine-global `config.toml [hooks] exclude_commands = ["git"]` patch;
  - a command already prefixed with `rtk ` (belt-and-suspenders against a double rewrite — rtk
    itself is also idempotent here: `rtk hook claude` on an already-`rtk `-prefixed command emits
    no output, verified live).

Fail-open: ANY exception, or `rtk` erroring, exits 0 with no output — never blocks a Bash call
just because rtk had a bad day. This hook ALWAYS exits 0 regardless of `rtk hook claude`'s own exit
code — this script's job is rewriting, never gating, so even if `rtk hook claude` exited non-zero
(e.g. its own internal error) that must never translate into a PreToolUse BLOCK here; it still
relays whatever stdout `rtk hook claude` produced (the `updatedInput` rewrite JSON, if any)."""

import json
import re
import shutil
import subprocess
import sys

# Matches a bare `git`, `git <args>`, or the absolute-path escape `/usr/bin/git` (docs/RTK.md).
_GIT_RE = re.compile(r"^(?:/usr/bin/)?git(?:\s|$)")


def main():
    raw = sys.stdin.buffer.read()
    try:
        data = json.loads(raw or b"{}")
    except (json.JSONDecodeError, ValueError):
        return
    if data.get("tool_name") != "Bash":
        return
    command = (data.get("tool_input") or {}).get("command") or ""
    stripped = command.lstrip()
    if not stripped or _GIT_RE.match(stripped) or stripped.startswith("rtk "):
        return
    rtk = shutil.which("rtk")
    if not rtk:
        return
    proc = subprocess.run(
        [rtk, "hook", "claude"],
        input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=10, check=False,
    )
    if proc.stdout:
        sys.stdout.buffer.write(proc.stdout)
    # F1 (self-check): never propagate rtk's own exit code — this hook rewrites, it never gates,
    # so a non-zero `rtk hook claude` exit (its own internal error) must not become a PreToolUse
    # BLOCK here. Still relay whatever stdout it produced above.


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — fail open; a crashed rewrite hook must never block Bash
        sys.exit(0)

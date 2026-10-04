#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""SessionStart (#fleet-freshness, Trigger B): (a) DIRECT — auto-ff the CURRENT repo's main checkout
when safe (the primitive self-guards: behind+clean+on-trunk+ff-able+not-opted-out), and (b) SIDEWAYS
— WARN-ONLY if a fleet project's claude_template plugin-source primary (resolved from the repo's
`.claude/settings.json` marketplace `directory` source) is behind its trunk. NEVER auto-ff a repo you
didn't open — the sideways leg only READS + warns. Byte-parity Node twin: session_autoff.cjs
(identical behaviour + identical stderr strings). Guarded import, fail-open, ALWAYS exit 0."""
import json
import os
import subprocess
import sys

try:
    # Reuse the primitive's FULL trunk chain (origin/HEAD -> main -> master -> @{u} ->
    # init.defaultBranch) so the sideways warn resolves an exotic default branch too, not a subset.
    from _ff_checkout import _trunk as _ff_trunk
    from _ff_checkout import ff_checkout_if_safe
except Exception:  # noqa: BLE001 — no primitive -> no-op, never crash
    ff_checkout_if_safe = None
    _ff_trunk = None


def _git(cwd, *args):
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True,
                           timeout=8, check=False)
    except Exception:  # noqa: BLE001 — fail open
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _sideways_primary(cwd):
    """The claude_template plugin-source primary path from cwd's marketplace settings, or None.
    Missing / unparseable / oddly-shaped settings -> None (silent noop, never error)."""
    try:
        with open(os.path.join(cwd, ".claude", "settings.json"), encoding="utf-8") as f:
            data = json.load(f)
        p = data["extraKnownMarketplaces"]["claude-template"]["source"]["path"]
        if not isinstance(p, str) or not p:
            return None
        resolved = p if os.path.isabs(p) else os.path.join(cwd, p)
        return os.path.realpath(resolved)
    except Exception:  # noqa: BLE001 — best-effort parse
        return None


def _warn_if_behind(primary):
    """Read-only: if the primary repo is strictly behind (ff-able from) its trunk, WARN to stderr."""
    trunk = _ff_trunk(primary)
    if not trunk:
        return
    head = _git(primary, "rev-parse", "HEAD")
    remote = _git(primary, "rev-parse", f"origin/{trunk}")
    if not head or not remote or head == remote:
        return
    ancestor = subprocess.run(
        ["git", "-C", primary, "merge-base", "--is-ancestor", "HEAD", f"origin/{trunk}"],
        capture_output=True, check=False).returncode == 0
    if not ancestor:
        return
    sys.stderr.write(
        f"fleet-freshness: claude_template primary {primary} is behind origin/{trunk} — "
        f"run: git -C {primary} merge --ff-only origin/{trunk}\n")


def main():
    if ff_checkout_if_safe is None:
        return 0
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        return 0
    cwd = (data.get("cwd") if isinstance(data, dict) else None) or os.getcwd()
    # Direct leg: auto-ff the current repo when safe (primitive self-guards; breadcrumb inside).
    # exit-0 stderr is invisible to the agent, so surface a declined-ff reason on stdout (#924).
    _verdict, reason = ff_checkout_if_safe(cwd)
    if reason:
        sys.stdout.write(json.dumps({"systemMessage": reason}) + "\n")
    # Sideways leg (best-effort, warn-only): a fleet project's plugin-source primary behind its trunk.
    # Self-double-ff guard: if the primary IS this repo (same realpath as cwd), the direct leg already
    # handled it — don't also warn.
    try:
        primary = _sideways_primary(cwd)
        if primary and os.path.isdir(primary) and primary != os.path.realpath(cwd):
            _warn_if_behind(primary)
    except Exception:  # noqa: BLE001 — sideways is best-effort, never error a session
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

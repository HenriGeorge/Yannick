"""Shared by the commit gates (tdd_gate / nocommit_guard): which staged paths are vendored content
per `.claude/vendor.lock`'s `files` map (written by `bin/vendor-tooling.sh` — see its `_read_lock` /
`vendor()` for the lock's shape: `files[rel] = {"plugin", "ref", "sha256"}`). Vendored content is
reviewed upstream, not in the consuming repo, so these paths are exempt from the TDD-test-required
and leftover-sentinel commit gates — but ONLY while the staged blob still matches the lock's
recorded sha256 (PR #1014 review, security hardening): a path merely LISTED in `files` is not
enough, or an agent could add its own file to `vendor.lock` to smuggle it past both gates. A
missing/mismatched sha never exempts — the gate then runs normally on that path.

Fail-open, degraded path visible on stdout (not just stderr): a MISSING lock is the common case (no
vendoring in this repo) and skips silently — no note. A PRESENT-but-malformed lock still never
blocks a commit, but leaves a note for the caller to surface via `ctx.notes` (the allow-path
breadcrumb channel other guards use — e.g. parallel_gate's PG32/PG33), so a broken lock's effect
(skip disabled this run) is visible, not silently inconsistent.
"""
import hashlib
import json
import os
import subprocess


def vendored_paths(cwd):
    """({repo-root-relative vendored path: locked sha256}, note_or_None).

    Missing `.claude/vendor.lock` -> ({}, None) — no skip, no note (the common case). Malformed
    lock (unreadable / bad JSON / no `files` dict) -> ({}, note) — no skip, with a note describing
    the degradation. A `files` entry with no/non-string `sha256` maps to None (never matches —
    `sha_matches` below always returns False for it).
    """
    path = os.path.join(cwd or ".", ".claude", "vendor.lock")
    if not os.path.isfile(path):
        return {}, None
    try:
        with open(path, encoding="utf-8") as f:
            lock = json.load(f)
        files = lock.get("files")
        if not isinstance(files, dict):
            raise ValueError("no `files` map")
    except (OSError, ValueError, AttributeError) as e:
        return {}, (
            f"vendor.lock unreadable ({type(e).__name__}) — vendored-path skip disabled this run"
        )
    out = {}
    for rel, meta in files.items():
        sha = meta.get("sha256") if isinstance(meta, dict) else None
        # Keys are already repo-root-relative (`.claude/hooks/...`), exactly as vendor-tooling writes them.
        out[rel.replace("\\", "/")] = sha if isinstance(sha, str) else None
    return out, None


def _staged_blob_sha256(cwd, path, timeout=5):
    """sha256 of `path`'s STAGED (index) blob content, or None when it can't be read (path not
    staged, git error, timeout) — a read failure is a non-match, never a match.
    ponytail: a fixed small timeout, not clamped to the shared PreToolUse wall-clock deadline
    (`_git.set_deadline`) like the other guard git calls — this is one tiny per-file blob read;
    wire it into the shared clamp if a real overrun ever shows up."""
    try:
        r = subprocess.run(
            ["git", "show", f":{path}"], cwd=cwd or None,
            capture_output=True, timeout=timeout, check=False,
        )
    except Exception:  # noqa: BLE001 - fail open toward "not vendored" (never skip the gate)
        return None
    if r.returncode != 0:
        return None
    return hashlib.sha256(r.stdout).hexdigest()


def sha_matches(cwd, path, locked_sha):
    """True only if `path`'s currently-STAGED content hashes to `locked_sha`. A missing/empty
    `locked_sha` or a hash mismatch (edited since vendoring, or never genuinely vendored) is NOT a
    match — the caller must then run the gate normally on that path, never exempt it."""
    if not locked_sha:
        return False
    actual = _staged_blob_sha256(cwd, path)
    return actual is not None and actual == locked_sha

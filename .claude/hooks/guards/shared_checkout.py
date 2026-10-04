"""Shared-checkout guard — a mutating git op in a primary checkout another live session shares
(hook consolidation PR 5)."""

import json
import os
import re
import subprocess

from _git import clamp as _git_clamp  # #979 — clamp this guard's git to the entry's hard deadline
from _lib.git import _GIT_GLOBAL_OPT, _resolve_git_cwd
from _lib.shell import _bare_shell_mask, _process_env_override, _segment_has_bare_command, _segment_has_leading_override, _segments_with_offsets


# Shared-checkout guard helpers (mirror of session_start.py.tmpl:418-490; inlined — hooks are
# standalone/dependency-free, a cross-file import would break the plugin-copied contract).
def _git_timeout():
    """SCG git-shell timeout in seconds (default 3). CT_GIT_TIMEOUT lets a test grant more time so
    the deliberately fail-open guard reaches a real verdict under CPU contention (#487) — production
    keeps 3s. A malformed OR non-positive value falls back to 3 (a 0/negative timeout makes
    subprocess.run raise immediately → guard silently fails open; parity with the Node twin's
    `v > 0` guard)."""
    try:
        v = float(os.environ.get("CT_GIT_TIMEOUT") or 3)
    except (TypeError, ValueError):
        return 3
    return v if v > 0 else 3


def _run(cmd, cwd):
    """subprocess.run wrapper; fail-safe empty-stdout CompletedProcess on ANY error (git missing,
    timeout, not a repo). Mirrors the file's other git shells (capture_output/text/timeout/check)."""
    try:
        return subprocess.run(cmd, cwd=cwd or None, capture_output=True,
                              text=True, timeout=_git_clamp(_git_timeout()), check=False)
    except Exception:  # noqa: BLE001
        return subprocess.CompletedProcess(cmd, 1, "", "")


def _session_lock_dir(cwd):
    override = os.environ.get("CT_SESSION_DIR")
    if override:
        return override
    common = _run(["git", "rev-parse", "--git-common-dir"], cwd).stdout.strip()
    if common and not os.path.isabs(common):
        common = os.path.join(os.path.abspath(cwd or "."), common)
    key = (common or os.path.abspath(cwd or ".")).replace(os.sep, "-").strip("-") or "root"
    return os.path.join(os.path.expanduser("~/.local/share/claude-template/sessions"), key)


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:  # noqa: BLE001
        return False


def _other_live_session(cwd):
    d = _session_lock_dir(cwd)
    me = os.getppid()
    try:
        names = [n for n in os.listdir(d) if n.endswith(".json")]
    except Exception:  # noqa: BLE001
        return False
    for name in names:
        try:
            with open(os.path.join(d, name)) as fh:
                pid = int(json.load(fh).get("pid"))
        except Exception:  # noqa: BLE001
            continue
        if pid != me and _pid_alive(pid):
            return True
    return False


def _is_primary_checkout(cwd):
    gd = _run(["git", "rev-parse", "--absolute-git-dir"], cwd).stdout.strip()
    cd = _run(["git", "rev-parse", "--git-common-dir"], cwd).stdout.strip()
    if cd and not os.path.isabs(cd):
        cd = os.path.abspath(os.path.join(cwd or ".", cd))
    # realpath (not abspath): git's --absolute-git-dir returns a symlink-resolved path, so a
    # symlinked checkout root (macOS /var→/private/var, any symlinked worktree) would else mismatch.
    return bool(gd) and os.path.realpath(gd) == os.path.realpath(cd)


def _checkout_clean_on_main(cwd):
    br = _run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd).stdout.strip()
    if br != "main":
        return False
    if _run(["git", "status", "--porcelain"], cwd).stdout.strip():
        return False
    # No origin/main ref → clean-vs-remote is unprovable; fail CLOSED (not clean → keep blocking).
    # Explicit ref check, not reliance on rev-list erroring to empty output for a missing ref (#466).
    if not _run(["git", "rev-parse", "--verify", "--quiet", "origin/main"], cwd).stdout.strip():
        return False
    counts = _run(["git", "rev-list", "--count", "--left-right", "origin/main...HEAD"], cwd).stdout.split()
    return counts == ["0", "0"]


# Mutating git subcommands — the ops that write to the shared index/worktree/refs. A read-only op
# (`git status`, `git log`, `git diff`) never trips the shared-checkout guard. Nudge-grade like the
# sibling guards: matches `git … <sub>`, not a full shell parse.
_MUTATING_GIT_RE = re.compile(
    r"\bgit\s+" + _GIT_GLOBAL_OPT
    + r"(commit|add|rm|checkout|switch|branch|merge|rebase|reset|restore|stash)\b")


def _guard_shared_checkout(command: str, cwd: str):
    """BLOCK a mutating git op when ALL four gates hold: this is the PRIMARY checkout (a linked
    worktree is the agent's own space), another live session shares it, it is not clean on
    origin/main (a quick clean-main op is fine), and the op mutates. Segment-split + per-segment
    override, mirroring _check_protected_branch. Bypass: CT_ALLOW_SHARED=1 (process or leading)."""
    if _process_env_override("CT_ALLOW_SHARED"):
        return
    bare = _bare_shell_mask(command)  # #889: a mutating git op merely quoted / heredoc-embedded is inert
    for segment, seg_off in _segments_with_offsets(command):
        if not _MUTATING_GIT_RE.search(segment):
            continue
        if not _segment_has_bare_command(segment, seg_off, bare, ("git",)):
            continue  # #889: the git op is inside a quote/heredoc body → inert text, not a dispatch
        if _segment_has_leading_override(segment, "CT_ALLOW_SHARED"):
            continue
        effective_cwd = _resolve_git_cwd(segment, cwd)
        if not _is_primary_checkout(effective_cwd):   # your own worktree never trips
            continue
        if not _other_live_session(effective_cwd):    # solo session never trips
            continue
        if _checkout_clean_on_main(effective_cwd):     # clean origin/main quick op is fine
            continue
        return (
            "Concurrent session shares this primary checkout and it is not clean on origin/main. "
            "Work in your own worktree: git worktree add -b <name> .claude/worktrees/<name> origin/main (flat name, no slash). "
            "Set CT_ALLOW_SHARED=1 to override.")


def check(ctx):
    return _guard_shared_checkout(ctx.command, ctx.cwd)

"""H9 — block staging a file over CT_MAX_FILE_MB (hook consolidation PR 5)."""

import os
import subprocess

from _lib.git import GIT_ADD_RE, GIT_COMMIT_INVOCATION_RE, _add_command_targets, _resolve_git_cwd, _staged_names
from _lib.shell import SHELL_SEGMENT_SPLIT_RE, _process_env_override, _segment_has_leading_override


DEFAULT_MAX_FILE_MB = 10.0


def _staged_blob_size_mb(cwd: str, path: str):
    """Size (MB) of PATH as staged in the git index (`git cat-file -s :path`) — robust regardless
    of working-tree state (the file may have changed or been deleted since it was staged). None on
    any failure (fail open)."""
    try:
        result = subprocess.run(
            ["git", "cat-file", "-s", f":{path}"],
            cwd=cwd or None, capture_output=True, text=True, timeout=5, check=False,
        )
    except Exception:  # noqa: BLE001
        return None
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip()) / (1024 * 1024)
    except ValueError:
        return None


def _max_file_mb() -> float:
    try:
        return float(os.environ.get("CT_MAX_FILE_MB", DEFAULT_MAX_FILE_MB))
    except (TypeError, ValueError):
        return DEFAULT_MAX_FILE_MB


def _check_giant_file(command: str, cwd: str):
    if _process_env_override("CT_ALLOW_BIGFILE"):
        return
    max_mb = _max_file_mb()
    for segment in SHELL_SEGMENT_SPLIT_RE.split(command):
        if GIT_ADD_RE.search(segment):
            # Pre-staging: the file isn't in the index yet at hook-check-time, so check its size
            # on disk — from the command's own path arguments, OR (HIGH fix) from `git status` if
            # this is a stages-everything form (-A/-u/`.`) that names no explicit paths.
            for path in _add_command_targets(segment, cwd):
                full = path if os.path.isabs(path) else os.path.join(cwd or ".", path)
                try:
                    if not os.path.isfile(full):
                        continue  # a directory / doesn't exist — nudge-grade, not a shell parser
                    size_mb = os.path.getsize(full) / (1024 * 1024)
                except OSError:
                    continue
                if size_mb > max_mb:
                    if _segment_has_leading_override(segment, "CT_ALLOW_BIGFILE"):
                        continue
                    return (
                        f"Blocked: '{path}' is {size_mb:.1f}MB, over the {max_mb:g}MB limit "
                        "(CT_MAX_FILE_MB). Set CT_ALLOW_BIGFILE=1 to override."
                    )
        elif GIT_COMMIT_INVOCATION_RE.search(segment):  # #237: `git -C <p> commit` too
            # Post-staging: the file(s) were staged by an EARLIER `git add` call, so check the
            # index's own blob size (robust even if the working-tree file since changed/gone).
            git_cwd = _resolve_git_cwd(segment, cwd)  # #237: enumerate the -C target's index, not cwd
            for path in _staged_names(git_cwd):
                size_mb = _staged_blob_size_mb(git_cwd, path)
                if size_mb is not None and size_mb > max_mb:
                    if _segment_has_leading_override(segment, "CT_ALLOW_BIGFILE"):
                        continue
                    return (
                        f"Blocked: staged file '{path}' is {size_mb:.1f}MB, over the {max_mb:g}MB "
                        "limit (CT_MAX_FILE_MB). Set CT_ALLOW_BIGFILE=1 to override."
                    )


def check(ctx):
    return _check_giant_file(ctx.command, ctx.cwd)

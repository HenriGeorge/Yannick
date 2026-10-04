"""H8 backstop (#437) — a git add/commit whose worktree cwd fell back to the primary checkout
(hook consolidation PR 5)."""

import os
import re

from _lib.git import GIT_ADD_RE, GIT_COMMIT_INVOCATION_RE, _git_show_toplevel, _resolve_git_cwd
from _lib.shell import SHELL_SEGMENT_SPLIT_RE, _process_env_override, _segment_has_leading_override


# H8 cwd-assertion backstop (#437) — a native worktree lives at `.../.claude/worktrees/<name>`;
# that prefix of the (effective) cwd is the worktree root Claude BELIEVES it's in, independent of
# git's (possibly-stale) registry. If the worktree vanished and cwd silently fell back to the
# primary checkout (#483), `git rev-parse --show-toplevel` resolves to a DIFFERENT root — the
# silent-drop-onto-primary vector this backstop catches.
WORKTREE_ROOT_FROM_CWD_RE = re.compile(r"^(.*/\.claude/worktrees/[^/]+)")


def _check_worktree_cwd_assertion(command: str, cwd: str):
    """H8 backstop (#437): a `git add`/`git commit` whose effective cwd claims to sit in a native
    worktree (`.../.claude/worktrees/<name>`) but where `git rev-parse --show-toplevel` resolves to
    a DIFFERENT root — the silent-drop-onto-primary half of #483 (the worktree vanished, cwd fell
    back to the primary checkout on main, and the staged diff would land on the wrong branch). The
    remove-guard DENY covers the delete; this covers the commit that follows. Fail-open on any git
    error / non-worktree cwd. Override CT_ALLOW_DANGER=1 (process-env or segment-leading)."""
    if _process_env_override("CT_ALLOW_DANGER"):
        return
    for segment in SHELL_SEGMENT_SPLIT_RE.split(command):
        if not (GIT_ADD_RE.search(segment) or GIT_COMMIT_INVOCATION_RE.search(segment)):
            continue
        effective_cwd = _resolve_git_cwd(segment, cwd)
        m = WORKTREE_ROOT_FROM_CWD_RE.match(effective_cwd or "")
        if not m:
            continue  # not inside a native worktree path — not this backstop's concern
        top = _git_show_toplevel(effective_cwd)
        if not top:
            continue  # git errored / cwd gone → fail-open (the remove-guard covers the vanish case)
        # Block ONLY when the resolved toplevel truly fell back to the primary checkout — i.e. it is
        # NOT itself within a `.claude/worktrees/` subtree. A worktree for a slashed branch nests
        # (worktrees/feat/automation-pilot), so an exact match against the one-segment regex group
        # would false-positive; the "did we escape the worktree tree" test is slash-safe (#603).
        if "/.claude/worktrees/" not in os.path.realpath(top):
            if _segment_has_leading_override(segment, "CT_ALLOW_DANGER"):
                continue
            return (
                f"Blocked: cwd '{effective_cwd}' names a native worktree, but the worktree git "
                f"resolves to is '{top}' — the worktree vanished and cwd fell back to the primary "
                "checkout; a git add/commit here would land the staged diff on the wrong branch "
                "(#483). Set CT_ALLOW_DANGER=1 to override."
            )


def check(ctx):
    return _check_worktree_cwd_assertion(ctx.command, ctx.cwd)

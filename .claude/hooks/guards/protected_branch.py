"""H8 — no direct commit/push to main/master (hook consolidation PR 5)."""

import re

from _lib.git import GIT_PUSH_WITH_DASH_C_RE, PROTECTED_BRANCHES, _current_branch, _push_candidates, _resolve_git_cwd
from _lib.shell import _bare_shell_mask, _process_env_override, _segment_has_leading_override, _segments_with_offsets


# A bare `\bgit\s+commit\b` / `\bgit\s+push\b` adjacency doesn't match when a
# `-C <path>` sits between "git" and the subcommand — H8 needs its OWN trigger checks that
# tolerate it, else the -C fix above is never actually reached.
GIT_COMMIT_OR_PUSH_WITH_DASH_C_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(?:commit|push)\b(?!-)")  # #744(3): (?!-) so `git commit-tree`/`commit-graph` don't over-trigger the protected-branch guard




def _check_protected_branch(command: str, cwd: str):
    if _process_env_override("CT_ALLOW_PROTECTED"):
        return
    bare = _bare_shell_mask(command)  # #482: a commit/push merely quoted / heredoc-embedded is inert
    for segment, seg_off in _segments_with_offsets(command):
        if _segment_has_leading_override(segment, "CT_ALLOW_PROTECTED"):
            continue
        # #482 Gap 3: evaluate EVERY bare commit/push in the segment, not just the first — truly
        # mirroring H2's _check_conventional_commit (which loops ALL matches with NO break). `&` is
        # not a SHELL_SEGMENT_SPLIT_RE separator, so `git commit -m x & git push origin main` is ONE
        # segment holding BOTH a bare commit AND a bare push; acting on only the first (the commit,
        # scored against the current — unprotected — branch) let the trailing protected-branch push
        # slip through (was blocked pre-#482, silently re-allowed by the first-match-only pass). Each
        # bare match is scored independently against its own tail; block if ANY warrants it.
        effective_cwd = None
        for m in GIT_COMMIT_OR_PUSH_WITH_DASH_C_RE.finditer(segment):
            if not bare[seg_off + m.start()]:
                continue  # inside a quote / heredoc body — inert text, not a dispatch
            if effective_cwd is None:
                effective_cwd = _resolve_git_cwd(segment, cwd)
            tail = segment[m.start():]  # scope push/commit parsing to THIS bare invocation
            if GIT_PUSH_WITH_DASH_C_RE.match(tail):
                # 2nd fix-up (HIGH-1 still open after the 1st pass): TARGET-aware, not "current
                # branch is protected" unconditionally — `git push origin feature-x` while on main
                # must ALLOW; only the push's actual DESTINATION(S) matter here (3rd fix-up: a push
                # can update MULTIPLE refs at once — `git push origin main feature` — so ANY candidate
                # resolving to a protected branch blocks the whole push, not just the last one).
                branch = next(
                    (b for b, _ in _push_candidates(tail, effective_cwd) if b in PROTECTED_BRANCHES),
                    None,
                )
                action = "push"
            else:
                # `git commit` — a commit always lands on the CURRENT branch, so this stays
                # unconditional (unchanged from the 1st pass).
                branch = _current_branch(effective_cwd)
                action = "commit"
            if branch in PROTECTED_BRANCHES:
                return (
                    f"Blocked: direct git {action} on protected branch '{branch}'. Use a feature "
                    "branch + PR, or set CT_ALLOW_PROTECTED=1 to override."
                )


def check(ctx):
    return _check_protected_branch(ctx.command, ctx.cwd)

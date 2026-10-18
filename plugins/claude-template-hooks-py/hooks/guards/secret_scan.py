"""H3 — staged-diff secret scan at `git commit` (hook consolidation PR 5)."""

import re

from _lib.git import GIT_COMMIT_INVOCATION_RE, _resolve_git_cwd, run_memo
from _lib.shell import SHELL_SEGMENT_SPLIT_RE, _process_env_override, _segment_has_leading_override


# H3 — secret-scan: obvious secrets in a staged diff (AWS key, private-key header, generic token
# assignment). Overridable via CT_ALLOW_SECRETS=1 (see `_segment_has_leading_override` /
# `_process_env_override` — leading env-assignment token of the COMMIT's own segment, or real
# process env; never an unanchored substring, never leaking from a different segment).
AWS_KEY_RE = re.compile(r"AKIA[0-9A-Z]{16}")


PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")


# TODO(secret-scan): GENERIC_SECRET_RE only catches a QUOTED `key = "value"` assignment; an
# unquoted `KEY=value` (e.g. a bare .env-style line) is currently missed. Left as-is this pass —
# broadening risks false positives on ordinary code (`token = getToken()`-shaped lines, etc.) and
# needs its own design pass, not a drive-by widen.
GENERIC_SECRET_RE = re.compile(
    r'(?i)\b(token|secret|api[_-]?key)\b\s*[:=]\s*["\']([A-Za-z0-9+/=_-]{16,})["\']'
)


def _check_secret_scan(command: str, cwd: str):
    # KNOWN LIMITATION (Increment-4 audit, documented not silently left inconsistent): unlike H6/
    # H9/H10, this does NOT see a brand-new secret introduced by a SAME-COMMAND chained
    # `git add -A && git commit ...` — this reads `git diff --cached` at hook-check time, which is
    # PRE-execution (nothing in the chain has actually run yet), so a file `git add -A` would
    # newly stage isn't reflected here. H6/H9/H10 closed the equivalent gap cheaply because they
    # only need FILENAMES (`git status` enumeration); closing it here would mean reading and
    # regex-scanning the CONTENT of every about-to-be-staged file (raw untracked-file bytes +
    # working-tree diffs for modified-tracked files) — a real cost/complexity increase (binary
    # files, huge files, encoding) that's its own design pass, not a drive-by fix — same class of
    # call as the existing GENERIC_SECRET_RE TODO below. Pinned by
    # tests/test_pretooluse_h3h6.sh's "H3-LIMIT" case so this gap can't silently regress further
    # or be mistaken for "already handled".
    #
    # Find the segment that actually does the `git commit` (MED fix: the override must be scoped
    # to THIS segment, not "any segment of the whole command" — see _check_test_lock for the same
    # reasoning). If more than one segment matches, the first is used — multiple chained commits
    # in one Bash call is an edge case outside this guard's stated scope.
    commit_segment = next(
        (seg for seg in SHELL_SEGMENT_SPLIT_RE.split(command)
         if GIT_COMMIT_INVOCATION_RE.search(seg)), None  # #237: match `git -C <p>/-c <cfg> commit` too
    )
    if commit_segment is None:
        return
    if _process_env_override("CT_ALLOW_SECRETS"):
        return
    if _segment_has_leading_override(commit_segment, "CT_ALLOW_SECRETS"):
        return
    # Routed through the per-call memo with color_off=True (hook consolidation PR 6, W3): same memo
    # key as nocommit's full staged diff, so the full `git diff --cached` runs once per commit call.
    diff = run_memo("pre_tool_use", _resolve_git_cwd(commit_segment, cwd), ["git", "diff", "--cached"],
                    timeout=5, color_off=True)
    if diff is None:
        return  # fail open (no git, not a repo, etc.)
    if AWS_KEY_RE.search(diff) or PRIVATE_KEY_RE.search(diff) or GENERIC_SECRET_RE.search(diff):
        return (
            "Blocked: staged diff appears to contain a secret (AWS key / private-key header / "
            "token-like assignment). Review `git diff --cached`, remove it, or set "
            "CT_ALLOW_SECRETS=1 to override."
        )


def check(ctx):
    return _check_secret_scan(ctx.command, ctx.cwd)

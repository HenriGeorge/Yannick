"""H5 PR-review, H6 docs-staleness and the worktree-prune note — INJECT-ONLY reminders, never a
deny (hook consolidation PR 5)."""

import re

from _lib.git import GIT_COMMIT_INVOCATION_RE, _add_segment_stages_everything, _resolve_git_cwd, _staged_names, _would_be_staged_by_add_all
from _lib.shell import SHELL_SEGMENT_SPLIT_RE
from _lib.docs_map import is_doc, is_source_excluded, load as load_docs_map  # D1 — one docs map for docs_gate + this reminder


# H5 — PR-review reminder: INJECT-ONLY (PreToolUse can block, but this guard never does — a nudge,
# not a gate). Never calls _block; only ever appends to the reminders list.
PR_MERGE_RE = re.compile(r"\bgh\s+pr\s+merge\b")


# H-prune (#483) — INJECT-ONLY nudge, same rationale as H5: `git worktree prune` only clears DEAD
# metadata, but a blind prune during concurrent-agent work can race a sibling. Never blocks.
GIT_WORKTREE_PRUNE_RE = re.compile(r"\bgit\b.*\bworktree\s+prune\b")


# H6 — docs-staleness reminder: INJECT-ONLY, same rationale as H5. Paths under these prefixes don't
# count as "source" for this heuristic — infra/config dirs, not the kind of change that would make
# docs stale. `tests/`/`test/` included: a test-only commit is pure noise here — it never blocks
# either way, but nudging "check the docs" on a change that touched no product code is a false
# positive the reminder shouldn't produce. Doc paths are excluded via `is_doc()` (the one docs map,
# D1) instead of a hard-coded `docs/` prefix here.
DOCS_STALENESS_EXCLUDED_PREFIXES = ("crew/", ".claude/", ".github/", "tests/", "test/")


def _check_pr_review_reminder(command: str) -> str | None:
    """H5 — never blocks. A `gh pr merge` anywhere in the command gets a /review nudge."""
    if PR_MERGE_RE.search(command):
        return "Reminder: run /review on this PR before merging (rules/workflow.md REVIEW phase)."
    return None


def _check_worktree_prune_reminder(command: str) -> str | None:
    """Nudge, never a block: `git worktree prune` only clears DEAD metadata, but a blind prune
    during concurrent-agent work can race a sibling — remind, don't stop."""
    if GIT_WORKTREE_PRUNE_RE.search(command):
        return ("Note: 'git worktree prune' clears metadata for worktrees whose dir is already "
                "gone. If a sibling agent is live, don't assume its tree is stale (#483).")
    return None


def _check_docs_staleness_reminder(command: str, cwd: str) -> str | None:
    """H6 — never blocks. If a `git commit`'s staged diff touches source but NOT docs/, nudge a
    docs-impact-agent check. Uses `_staged_names` (shared with H9/H10) — same event/trigger as
    H3's secret scan, but a separate call since H3 needs the diff CONTENT, this needs file PATHS.

    Broader-fix (Increment-4 audit): unlike H3 (which needs file CONTENT and is documented as a
    known gap for this same scenario — see `_check_secret_scan`), this is CHEAP to close with the
    same H9/H10 enumeration since it only needs filenames — merge in what a same-command chained
    `git add -A`/`.`/`-u` WOULD stage so the reminder isn't silently skipped."""
    commit_segment = next(
        (seg for seg in SHELL_SEGMENT_SPLIT_RE.split(command)
         if GIT_COMMIT_INVOCATION_RE.search(seg)), None  # #237: `git -C <p> commit` too
    )
    if commit_segment is None:
        return None
    git_cwd = _resolve_git_cwd(commit_segment, cwd)  # #237: enumerate the -C target's index, not cwd
    paths = list(_staged_names(git_cwd))
    for segment in SHELL_SEGMENT_SPLIT_RE.split(command):
        if _add_segment_stages_everything(segment):
            paths.extend(_would_be_staged_by_add_all(git_cwd))
            break
    if not paths:
        return None  # nothing staged — nothing to flag
    globs, historical = load_docs_map(cwd)
    touches_docs = any(is_doc(p, globs, historical) for p in paths)
    touches_source = any(
        not is_doc(p, globs, historical)
        and not is_source_excluded(p, globs, historical)
        and not p.startswith(DOCS_STALENESS_EXCLUDED_PREFIXES)
        for p in paths
    )
    if touches_source and not touches_docs:
        return (
            "Reminder: this commit touches source but no doc in the docs map — consider running "
            "docs-impact-agent to check for stale docs."
        )
    return None


def pr_review(ctx):
    return _check_pr_review_reminder(ctx.command)


def docs_staleness(ctx):
    return _check_docs_staleness_reminder(ctx.command, ctx.cwd)


def worktree_prune(ctx):
    return _check_worktree_prune_reminder(ctx.command)

"""stale_base_guard as a pre_tool guard (hook consolidation PR 6) — the old hook's body, moved verbatim.
GATE-0 "rebase if behind" teeth, without per-commit noise.

Intercepts `git commit`. Resolves the COMMITTING repo (honors `git -C <path>`, else the invocation
cwd) — never the shared primary checkout (that cross-worktree misread is issue #470). If HEAD is
behind origin/main AND the staged files overlap files that changed on origin/main since the
merge-base -> DENY (real redo/conflict). Behind but disjoint -> WARN (allow). Not behind / no
origin/main ref -> allow. A `git merge origin/main` in progress is the sync itself, so it's exempt
(#959). Bypass: WORKFLOW:no-rebase-check is honoured ONLY while a merge is in progress (MERGE_HEAD
exists) — on a normal commit it is IGNORED and the block stands (#959 follow-up). Fails OPEN on any error.
"""
import os
import shlex
import sys
import time

from _git import run as _git_run  # #743 — shared git-runner: fail-open BUT leave a stderr breadcrumb
from _lib.git import run_memo  # PR 6 — per-call memo for the read-only diff/show/status queries

BYPASS = "WORKFLOW:no-rebase-check"
# Throttled auto-fetch: in a long-lived session origin/main goes stale (session_start/worktree_create
# fetch only at start), so a behind-check against the CACHED ref silently under-warns. Refresh it here
# at most once per window, gated on git's own FETCH_HEAD mtime (shared across worktrees). Fail-open.
FETCH_THROTTLE_SEC = 300
FETCH_TIMEOUT_SEC = 5  # ≤5 s hard cap — runs last inside pre_tool (spec grill C2)
GIT_VALUE_FLAGS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
DENY_REASON = (
    "GATE-0 stale-base ⛔ — HEAD is behind origin/main and your staged files overlap what already "
    "landed there. Sync, don't bypass: `git stash push -u -m <tag>` → `git merge origin/main` "
    "(sync commit, no bypass needed) → `git stash apply <sha>` → commit. WORKFLOW:no-rebase-check is "
    "only honoured on a merge commit — it is IGNORED on a normal commit."
)


def _run(cwd, args, timeout=8):
    # PR 6: the read-only queries go through the per-call memo (diff/show/status); everything else
    # (rev-parse / rev-list / merge-base) passes straight through. Fail-open WITH a breadcrumb.
    return run_memo("stale_base_guard", cwd, args, timeout=timeout)


def _tokens(cmd):
    try:
        return shlex.split(cmd, comments=False)
    except ValueError:
        return cmd.split()


def _is_git_commit(tokens):
    """True if tokens invoke `git … commit …` (flag-tolerant, like close_gate)."""
    i, n = 0, len(tokens)
    while i < n and tokens[i] != "git":
        i += 1
    if i >= n:
        return False
    i += 1
    while i < n:
        t = tokens[i]
        if t in GIT_VALUE_FLAGS:
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        return t == "commit"
    return False


def _commit_stages_tracked(tokens):
    """True if a `-a`/`--all` commit flag is present — it auto-stages modified tracked files at
    commit time, so the overlap check must also union the currently-unstaged tracked edits (#488
    Gap B). `--amend` is deliberately NOT matched (its short-cluster test rejects a leading `--`)."""
    for t in tokens:
        if t == "--all":
            return True
        if t.startswith("-") and not t.startswith("--") and "a" in t[1:]:
            return True
    return False


def _target_repo(tokens, cwd):
    """The committing repo: value of `git -C <path>` if present, else cwd. #470 anchor."""
    for j, t in enumerate(tokens):
        if t == "-C" and j + 1 < len(tokens):
            p = tokens[j + 1]
            return p if os.path.isabs(p) else os.path.join(cwd or ".", p)
    return cwd or "."


def _merge_in_progress(repo):
    """True when a merge is underway (MERGE_HEAD present). Located via --git-path (rc 0, no fail-open
    breadcrumb) + existence check, NOT `rev-parse -q --verify MERGE_HEAD` — that exits 1 on the common
    no-merge path, spamming the shared runner's breadcrumb on every behind-commit. Mirrors
    _maybe_fetch's FETCH_HEAD handling."""
    ghp = _run(repo, ["git", "rev-parse", "--git-path", "MERGE_HEAD"])
    if not ghp:
        return False
    p = ghp.strip()
    if not os.path.isabs(p):
        p = os.path.join(repo, p)
    return os.path.exists(p)


def _merge_syncs_main(repo):
    """#959 — True when an in-progress merge's MERGE_HEAD is origin/main or contains it (origin/main
    is an ancestor). That merge commit is the act that brings the branch up to date, so the behind
    check is a false positive here. A plain commit (no MERGE_HEAD) or a merge of some other branch
    falls through to the overlap check and still DENYs. origin/main-is-ancestor is tested by
    stdout, not `--is-ancestor`'s exit code (the shared runner collapses non-zero to None)."""
    if not _merge_in_progress(repo):
        return False
    om = _run(repo, ["git", "rev-parse", "origin/main"])
    mb = _run(repo, ["git", "merge-base", "origin/main", "MERGE_HEAD"])
    return bool(om and mb and om.strip() == mb.strip())


def _maybe_fetch(repo):
    """Throttled `git fetch origin` so origin/main reflects the true remote tip. No-ops if a fetch
    happened within FETCH_THROTTLE_SEC (git's FETCH_HEAD mtime). Fail-open: any error is ignored and
    the check falls back to the cached ref (pre-existing behavior)."""
    ghp = _run(repo, ["git", "rev-parse", "--git-path", "FETCH_HEAD"])
    if ghp:
        p = ghp.strip()
        if not os.path.isabs(p):
            p = os.path.join(repo, p)
        try:
            if time.time() - os.path.getmtime(p) <= FETCH_THROTTLE_SEC:
                return  # fetched recently -> skip (no commit-latency in rapid loops)
        except OSError:
            pass  # FETCH_HEAD missing -> treat as stale -> fetch
    # ≤5 s hard cap + discard_output so a hung fetch whose grandchild still holds a pipe can never
    # stall pre_tool (spec grill C2/C3). Goes straight to _git_run, bypassing the read-only memo.
    _git_run("stale_base_guard", repo, ["git", "fetch", "--quiet", "origin"],
             timeout=FETCH_TIMEOUT_SEC, discard_output=True)


def check(ctx):
    cmd = ctx.command
    tokens = _tokens(cmd)
    if not _is_git_commit(tokens):
        return None

    repo = _target_repo(tokens, ctx.data.get("cwd") or ".")
    has_bypass = BYPASS in cmd
    # #959 follow-up — the bypass token is honoured ONLY during an in-progress merge. A normal commit
    # must sync via `git merge origin/main` (itself exempt below), not route around the gate; five
    # agents mis-used the token on normal fix commits. During a merge (of origin/main OR a deliberate
    # other branch) the token keeps its escape hatch.
    if has_bypass and _merge_in_progress(repo):
        return None
    # #979/item1+3: once another check already blocks this call, the entry sets ctx.skip_stale_fetch
    # so we skip the network FETCH (the only slow/hanging call) but STILL run the local overlap check
    # below — the deny is never dropped. This note is emitted ONLY here (a real git commit reached the
    # fetch), so a denied non-commit/Write never gets a spurious "skipped" note.
    if getattr(ctx, "skip_stale_fetch", False):
        notes = getattr(ctx, "stderr_notes", None)
        if notes is not None:
            notes.append("stale-base: network fetch skipped (a block is already pending) — "
                         "checked against last-known origin/main")
    else:
        _maybe_fetch(repo)  # refresh stale origin/main before the behind-check (throttled, fail-open)
    behind = _run(repo, ["git", "rev-list", "--count", "HEAD..origin/main"])
    if not behind or behind.strip() == "0":
        return None  # current (or no origin/main ref) -> allow silently
    if _merge_syncs_main(repo):  # #959 — merging origin/main IS the sync, not a stale-base redo
        return None

    base = _run(repo, ["git", "merge-base", "HEAD", "origin/main"])
    if not base:
        return None
    base = base.strip()
    main_changed = _run(repo, ["git", "diff", "--name-only", base, "origin/main"]) or ""
    staged = _run(repo, ["git", "diff", "--cached", "--name-only"]) or ""
    main_set = {ln for ln in main_changed.splitlines() if ln}
    staged_set = {ln for ln in staged.splitlines() if ln}
    if _commit_stages_tracked(tokens):  # #488 Gap B — `-a`/`--all` stages tracked edits at commit
        unstaged = _run(repo, ["git", "diff", "--name-only"]) or ""
        staged_set |= {ln for ln in unstaged.splitlines() if ln}
    if main_set & staged_set:
        # (reason, bypass_token) — record a REFUSED bypass (token on a normal commit) distinctly
        # from a plain block, matching the standalone's _block(reason, BYPASS if has_bypass else None).
        return (DENY_REASON, BYPASS if has_bypass else None)
    # behind but disjoint -> WARN breadcrumb, allow. #979/L2: route it through ctx.stderr_notes — the
    # entry surfaces it on stdout in full mode (exit-0 stderr is invisible) and on stderr for the
    # `--only` forwarder path (byte-parity with the retired standalone).
    msg = "GATE-0 note: HEAD is behind origin/main (disjoint files) — consider `git rebase origin/main`."
    notes = getattr(ctx, "stderr_notes", None)
    if notes is not None:
        notes.append(msg)
    else:
        sys.stderr.write(msg + "\n")
    return None

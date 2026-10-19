"""session_prime_gate as a pre_tool guard (hook consolidation PR 6) — the old hook's body, moved verbatim.
The enforcement half of GATE-0's "isolate + prime first".

A SessionStart hook can only INJECT text, never block; so this PreToolUse gate is what makes the
"always start in a worktree, primed, before touching anything" discipline non-skippable. It BLOCKS
the first *mutation* (Edit / Write / NotebookEdit, or a `git commit`) in a **managed** repo when the
session is still on the shared PRIMARY checkout (not isolated in a `.claude/worktrees/` worktree) OR
has not been primed (no prime-ack marker written by `/prime-core`). Read-only tools never trip it.

The marker is session-bound: `/prime-core` writes the CURRENT session's id into
`.claude/state/primed`, and the gate only accepts a marker whose content equals the hook input's
`session_id` (an empty marker, e.g. from a bare `touch`, never counts). A child session (a
teammate/subagent spawned inside the coordinator's own worktree) inherits any non-empty marker
regardless of its own id — it shares the coordinator's prime. When the hook input carries no
`session_id` at all, the gate falls back to a plain presence check (and breadcrumbs that it did, via
`ctx.stderr_notes`) rather than denying everyone on an older harness that doesn't send one. Gated
Bash commands: `git commit`, `git push`, `gh pr create`, `gh pr merge`.

Escape hatches (the genuinely-trivial / solo case):
- `PRIME_GATE=0` in the environment — disables the gate entirely.
- `WORKFLOW:no-worktree` / `WORKFLOW:no-prime` inline in a `git commit` / `git push` / `gh pr
  create` / `gh pr merge` command.

Fail-open on any error (a startup guard must never brick a session). Writes to `.claude/state/**`
are always exempt so priming / the marker / the bypass can be written without self-blocking.

Scope (#995): a worktree only isolates the repo's OWN tracked tree — it does nothing for a target
OUTSIDE the repo (`~/.claude/plans/*.md`, `~/.claude/CLAUDE.md`) or for a per-user file INSIDE the
repo that's gitignored (`CLAUDE.local.md`). Gating those left no path through except the shared
bypass marker, even though no worktree could ever help. So before the isolation/primed checks, a
mutating Edit/Write/NotebookEdit target is resolved (relative paths joined to `cwd`, symlinks
resolved) against the current checkout's `git rev-parse --show-toplevel`; outside that tree, or
inside it but `git check-ignore`'d, the gate exits immediately. Resolution failure (no git / no
toplevel / a bad path, e.g. a NUL byte) falls back to the pre-#995 behavior (treat as inside,
unignored) — it does not grant a new bypass. **`git check-ignore` itself erroring (not a plain "not
ignored" exit 1) fails CLOSED** — treated as NOT ignored, so the mutation falls through to the normal
isolation/primed checks (which already fail open, distinguishably, via `stderr_notes`, when the
checkout itself is unresolvable) — a check-ignore hiccup on an in-repo path (a broken symlink, a
submodule, a missing git) must not silently skip the gate the way an out-of-tree path legitimately
does. `git commit` carries no `file_path` and is unaffected.
"""
import os
import re
import shlex
import subprocess
import sys

from _git import clamp as _git_clamp  # #979 — clamp this guard's git to the entry's hard deadline
from _lib.git import _staged_names  # memoized `diff --cached --name-only` shared with the commit gates
from _lib.session import is_child_session  # same guarded-sibling style as the other guards' _git import
from _lib.tier import TIER0_DENY_RE, TIER0_DOC_RE  # #1427 — pr-tier's docs-only predicate, one source

MUTATING_TOOLS = {"Edit", "Write", "NotebookEdit"}
# git commit, tolerating global options between `git` and `commit` (mirrors grill_gate's regex).
GIT_COMMIT_RE = re.compile(
    r"\bgit\s+(?:(?:-C|-c|--git-dir|--work-tree|--namespace|--exec-path)\s+\S+\s+|-{1,2}\S+\s+)*commit\b(?!-)"
)
# Session-id gated Bash surface: git commit (above) plus git push and gh pr create/merge — the
# three ways a session can publish work it was never primed to produce.
GATED_BASH_RE = re.compile(
    GIT_COMMIT_RE.pattern + r"|\bgit\s+(?:\S+\s+)*push\b|\bgh\s+pr\s+(?:create|merge)\b"
)
NO_WORKTREE = "WORKFLOW:no-worktree"
NO_PRIME = "WORKFLOW:no-prime"
# #1427: the lessons log is docs-only FOR THIS GATE although pr-tier's TIER0_DENY_RE lists it — that
# deny is a review-tier concern (it used to be injected into every prompt), while a lessons append
# from the primary checkout was the single most common reason the gate was bypassed.
DOCS_ONLY_ALLOW_RE = re.compile(r"(^|/)docs/lessons[^/]*\.md$", re.IGNORECASE)


def _is_docs_only(rel_path):
    """pr-tier's tier-0 definition (`_lib/tier.py`, the one source pr_gate reads too): a `.md`
    that is not instruction-bearing."""
    if not rel_path:
        return False
    if DOCS_ONLY_ALLOW_RE.search(rel_path):
        return True
    return bool(TIER0_DOC_RE.search(rel_path)) and not TIER0_DENY_RE.search(rel_path)


def _repo_relative(file_path, cwd):
    """file_path relative to the checkout's toplevel, or None when it can't be resolved."""
    toplevel = _repo_toplevel(cwd)
    if toplevel is None or not file_path:
        return None
    target = file_path if os.path.isabs(file_path) else os.path.join(cwd or ".", file_path)
    try:
        target = os.path.realpath(target)
    except ValueError:
        return None
    if target == toplevel or not target.startswith(toplevel + os.sep):
        return None
    return os.path.relpath(target, toplevel)


# A commit may claim the docs-only exemption only when the WHOLE command is `git commit` plus
# message/quiet/signoff flags (or a `-m`/`--message` argument). Anything else — `-a`, `--include`,
# `--only`, a pathspec, a `-C`/`--git-dir` global option, an env prefix, or a chained segment before
# or after (`git add … &&`, `&& git push`, `; git commit -am`) — widens the commit past the index
# the gate inspected (security self-check on #1427), so it falls through to the gate.
_PLAIN_COMMIT_FLAGS = {"-q", "--quiet", "-s", "--signoff", "--no-verify", "--no-edit", "-m", "--message"}
_MSG_FLAGS = {"-m", "--message"}


def _commit_is_index_only(command):
    """True when the command tokenizes to exactly `git commit <plain flags…>` — one segment."""
    try:
        toks = shlex.split(command, comments=True)
    except ValueError:
        return False
    if toks[:2] != ["git", "commit"]:
        return False
    skip = False
    for tok in toks[2:]:
        if skip:
            skip = False
            continue
        if tok in _MSG_FLAGS:
            skip = True
            continue
        if tok.startswith("--message=") or tok in _PLAIN_COMMIT_FLAGS:
            continue
        return False  # a pathspec, a widening flag, or a chain operator (`&&`, `;`, `|`, a 2nd `git`)
    return True


def _staged_docs_only(cwd, command):
    """True when the commit set is provably docs-only: an index-only commit form (no `-a`, no
    `--include`, no pathspec) over a non-empty staged set whose every path is docs-only. Reads the
    index through the per-call memo, so the commit gates still run `diff --cached` once."""
    if not _commit_is_index_only(command):
        return False
    paths = _staged_names(cwd)
    return bool(paths) and all(_is_docs_only(p) for p in paths)


def _run(args, cwd):
    try:
        return subprocess.run(args, capture_output=True, text=True, cwd=cwd, timeout=_git_clamp(5))
    except Exception:  # noqa: BLE001
        return None


def _isolation_state(cwd):
    """'primary' (shared checkout) | 'worktree' (isolated, git-dir != common-dir) | 'unknown'.

    'unknown' means git couldn't resolve the checkout (missing git / timeout / error) — the caller
    fail-opens on it, but distinguishably (F1). Both refs must resolve; an empty `cd` is 'unknown',
    NOT `realpath("")` which returns CWD and would misclassify (F2 py/node parity).
    """
    gd = _run(["git", "rev-parse", "--absolute-git-dir"], cwd)
    cd = _run(["git", "rev-parse", "--git-common-dir"], cwd)
    gd = gd.stdout.strip() if gd else ""
    cd = cd.stdout.strip() if cd else ""
    if not gd or not cd:
        return "unknown"
    if not os.path.isabs(cd):
        cd = os.path.abspath(os.path.join(cwd or ".", cd))
    return "primary" if os.path.realpath(gd) == os.path.realpath(cd) else "worktree"


def _is_managed(project_dir):
    """Only managed (template) repos are gated — a plain repo is never forced into this workflow."""
    return (os.path.isfile(os.path.join(project_dir, ".claude", "worktrees.conf"))
            or os.path.isfile(os.path.join(project_dir, "project-context.md")))


def _primed(checkout, session_id):
    """(ok, why, marker_path) for the marker /prime-core wrote in THIS session: non-empty, and equal
    to the hook input's session_id — except a child session (teammate/subagent in the coordinator's
    worktree), which inherits any non-empty marker, and an input with no session_id (presence
    fallback, breadcrumbed by the caller). An empty marker (a bare `touch`) is never primed.
    `checkout` is the toplevel of the checkout being mutated (the worktree after a mid-session
    EnterWorktree), NOT CLAUDE_PROJECT_DIR — the harness pins that to the launch dir for the whole
    session, so it still names the primary while /prime-core writes the marker relative to the
    Bash cwd. `why` names what was wrong so the deny is actionable: missing / empty / another session."""
    marker = os.path.join(checkout, ".claude", "state", "primed")
    try:
        with open(marker, encoding="utf-8") as fh:
            content = fh.read().strip()
    except FileNotFoundError:
        return False, "missing", marker
    except OSError:
        return False, "unreadable", marker
    if not content:
        return False, "empty", marker
    if is_child_session() or not session_id or content == session_id:
        return True, "", marker
    return False, "written by another session", marker


def _is_state_write(file_path, cwd):
    """A Write/NotebookEdit targeting the repo's OWN .claude/state/** is exempt (priming / marker /
    bypass writes). #1005: anchored to `<toplevel>/.claude/state` via the same realpath resolution
    `_is_outside_repo` uses — a bare substring test matched a look-alike path (`src/evil.claude/
    state/x`) ANYWHERE in the string and silently skipped the gate. Fails CLOSED (False = "not a
    state write") when the toplevel or the path can't be resolved, so a non-state target is never
    exempted on a resolution hiccup."""
    if not file_path:
        return False
    toplevel = _repo_toplevel(cwd)
    if toplevel is None:
        return False
    state_dir = os.path.join(toplevel, ".claude", "state")
    target = file_path if os.path.isabs(file_path) else os.path.join(cwd or ".", file_path)
    try:
        target = os.path.realpath(target)
    except ValueError:
        return False
    return target == state_dir or target.startswith(state_dir + os.sep)


def _repo_toplevel(cwd):
    r = _run(["git", "rev-parse", "--show-toplevel"], cwd)
    tl = r.stdout.strip() if r else ""
    return os.path.realpath(tl) if tl else None


def _is_outside_repo(file_path, cwd):
    """True when file_path resolves outside the current checkout's working tree. Fails CLOSED
    (False = "treat as inside") when the toplevel can't be resolved OR the path itself can't be
    resolved (e.g. a NUL byte raises ValueError), preserving pre-#995 behavior."""
    if not file_path:
        return False
    toplevel = _repo_toplevel(cwd)
    if toplevel is None:
        return False
    target = file_path if os.path.isabs(file_path) else os.path.join(cwd or ".", file_path)
    try:
        target = os.path.realpath(target)
    except ValueError:
        return False
    return target != toplevel and not target.startswith(toplevel + os.sep)


def _is_gitignored(file_path, cwd):
    """True when file_path is confirmed git-ignored (clean exit 0). Fails CLOSED (False = "not
    ignored") on any subprocess error or a non-0/1 exit — a `git check-ignore` hiccup on an in-repo
    path (broken symlink, submodule, missing git) must fall through to the normal isolation/primed
    checks, not silently exempt the target the way a genuinely out-of-tree path does."""
    if not file_path:
        return False
    r = _run(["git", "check-ignore", "-q", "--", file_path], cwd)
    if r is None or r.returncode not in (0, 1):
        return False  # subprocess error, or a fatal (e.g. bad pathspec) exit — fail closed
    return r.returncode == 0


def check(ctx):
    if os.environ.get("PRIME_GATE") == "0":
        return None

    tool = ctx.tool_name
    tool_input = ctx.tool_input or {}
    cwd = ctx.data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or "."
    session_id = str(ctx.data.get("session_id") or "")

    # Is this a gated MUTATION? (read-only tools exit immediately)
    inline_cmd = ""
    if tool in MUTATING_TOOLS:
        file_path = tool_input.get("file_path", "")
        if _is_state_write(file_path, cwd):
            return None  # never block writing prime/marker/bypass state
        if _is_outside_repo(file_path, cwd):
            return None  # #995: a worktree can't isolate a target outside it either
        if _is_gitignored(file_path, cwd):
            return None  # #995: nor a per-user gitignored file inside it (e.g. CLAUDE.local.md)
        if _is_docs_only(_repo_relative(file_path, cwd)):
            return None  # #1427: a docs-only edit needs neither isolation nor priming
    elif tool in ("Bash", "PowerShell"):
        inline_cmd = tool_input.get("command", "")
        if not GATED_BASH_RE.search(inline_cmd):
            return None  # only commit/push/gh-pr-create|merge are gated on the Bash path
        # #1427: an index-only commit whose staged set is docs-only is exempt too. ponytail: `git
        # push` of that commit still gates (its content is not in the index) — add a HEAD..@{u}
        # docs-only probe if the push half shows up in the bypass telemetry.
        if _staged_docs_only(cwd, inline_cmd):
            return None
    else:
        return None

    # The checkout being mutated: the hook cwd's git toplevel (the worktree after EnterWorktree),
    # falling back to CLAUDE_PROJECT_DIR / cwd when git can't resolve it.
    checkout = _repo_toplevel(cwd) or os.environ.get("CLAUDE_PROJECT_DIR") or cwd
    if not _is_managed(checkout):
        return None

    def _note(msg):
        notes = getattr(ctx, "stderr_notes", None)
        if notes is not None:
            notes.append(msg)
        else:
            print(msg, file=sys.stderr)

    if not session_id:
        # Q6: an older harness / a hook input with no session_id can't be bound to anything — fall
        # back to a plain presence check, breadcrumbed so a silently-weakened check is visible.
        _note("session-prime-gate: no session_id in hook input — marker checked by presence")

    # Isolation check (skippable per-commit with WORKFLOW:no-worktree)
    iso = _isolation_state(cwd)
    if iso == "unknown":
        # F1: git couldn't resolve the checkout — fail-open, but leave a breadcrumb so a silently
        # unenforced gate is distinguishable from a legit isolated worktree. #979/L2: route it through
        # ctx.stderr_notes — the entry surfaces it on stdout in full mode (exit-0 stderr is invisible)
        # and on stderr for the `--only` forwarder path (byte-parity with the retired standalone).
        _note("session-prime-gate: git checkout undetectable — allowing (fail-open; gate not "
              "enforced this call)")
        return None
    if iso == "primary" and NO_WORKTREE not in inline_cmd:
        return (
            "session-prime-gate: not isolated. This session is on the shared PRIMARY checkout — "
            "start work in a worktree first: EnterWorktree (fresh off origin/main), then edit there. "
            "Bypass: PRIME_GATE=0, or 'WORKFLOW:no-worktree' inline in the command.",
            NO_WORKTREE)

    # Primed check (skippable per-commit with WORKFLOW:no-prime)
    ok, why, marker = _primed(checkout, session_id)
    if not ok and NO_PRIME not in inline_cmd:
        return (
            f"session-prime-gate: not primed for this session — marker {marker} is {why}. Run "
            "`/prime-core` first (its last step writes this session's id, "
            "$CLAUDE_CODE_SESSION_ID, to .claude/state/primed in the checkout you are editing). "
            "Bypass: PRIME_GATE=0, or 'WORKFLOW:no-prime' inline in the command.",
            NO_PRIME)

    return None

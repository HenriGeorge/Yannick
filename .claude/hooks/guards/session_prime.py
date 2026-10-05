"""session_prime_gate as a pre_tool guard (hook consolidation PR 6) — the old hook's body, moved verbatim.
The enforcement half of GATE-0's "isolate + prime first".

A SessionStart hook can only INJECT text, never block; so this PreToolUse gate is what makes the
"always start in a worktree, primed, before touching anything" discipline non-skippable. It BLOCKS
the first *mutation* (Edit / Write / NotebookEdit, or a `git commit`) in a **managed** repo when the
session is still on the shared PRIMARY checkout (not isolated in a `.claude/worktrees/` worktree) OR
has not been primed (no prime-ack marker written by `/prime-core`). Read-only tools never trip it.

Escape hatches (the genuinely-trivial / solo case):
- `PRIME_GATE=0` in the environment — disables the gate entirely.
- `touch .claude/state/prime-bypass` — a per-checkout bypass marker (covers the Edit/Write path,
  which has no command to carry an inline token).
- `WORKFLOW:no-worktree` / `WORKFLOW:no-prime` inline in a `git commit` command.

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
import subprocess
import sys

from _git import clamp as _git_clamp  # #979 — clamp this guard's git to the entry's hard deadline

MUTATING_TOOLS = {"Edit", "Write", "NotebookEdit"}
# git commit, tolerating global options between `git` and `commit` (mirrors grill_gate's regex).
GIT_COMMIT_RE = re.compile(
    r"\bgit\s+(?:(?:-C|-c|--git-dir|--work-tree|--namespace|--exec-path)\s+\S+\s+|-{1,2}\S+\s+)*commit\b(?!-)"
)
NO_WORKTREE = "WORKFLOW:no-worktree"
NO_PRIME = "WORKFLOW:no-prime"


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


def _primed(project_dir):
    return os.path.isfile(os.path.join(project_dir, ".claude", "state", "primed"))


def _bypass_marker(project_dir):
    return os.path.isfile(os.path.join(project_dir, ".claude", "state", "prime-bypass"))


def _is_state_write(file_path):
    """A Write/NotebookEdit targeting .claude/state/** is exempt (priming/markers/bypass writes)."""
    if not file_path:
        return False
    norm = file_path.replace("\\", "/")
    return "/.claude/state/" in norm or norm.endswith("/.claude/state") or ".claude/state/" in norm


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

    # Is this a gated MUTATION? (read-only tools exit immediately)
    inline_cmd = ""
    if tool in MUTATING_TOOLS:
        file_path = tool_input.get("file_path", "")
        if _is_state_write(file_path):
            return None  # never block writing prime/marker/bypass state
        if _is_outside_repo(file_path, cwd):
            return None  # #995: a worktree can't isolate a target outside it either
        if _is_gitignored(file_path, cwd):
            return None  # #995: nor a per-user gitignored file inside it (e.g. CLAUDE.local.md)
    elif tool in ("Bash", "PowerShell"):
        inline_cmd = tool_input.get("command", "")
        if not GIT_COMMIT_RE.search(inline_cmd):
            return None  # only `git commit` is gated on the Bash path
    else:
        return None

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or cwd
    if not _is_managed(project_dir):
        return None
    if _bypass_marker(project_dir):
        return None

    # Isolation check (skippable per-commit with WORKFLOW:no-worktree)
    iso = _isolation_state(cwd)
    if iso == "unknown":
        # F1: git couldn't resolve the checkout — fail-open, but leave a breadcrumb so a silently
        # unenforced gate is distinguishable from a legit isolated worktree. #979/L2: route it through
        # ctx.stderr_notes — the entry surfaces it on stdout in full mode (exit-0 stderr is invisible)
        # and on stderr for the `--only` forwarder path (byte-parity with the retired standalone).
        msg = ("session-prime-gate: git checkout undetectable — allowing (fail-open; gate not "
               "enforced this call)")
        notes = getattr(ctx, "stderr_notes", None)
        if notes is not None:
            notes.append(msg)
        else:
            print(msg, file=sys.stderr)
        return None
    if iso == "primary" and NO_WORKTREE not in inline_cmd:
        return (
            "session-prime-gate: not isolated. This session is on the shared PRIMARY checkout — "
            "start work in a worktree first: EnterWorktree (fresh off origin/main), then edit there. "
            "Bypass: PRIME_GATE=0, or `touch .claude/state/prime-bypass`, or "
            "'WORKFLOW:no-worktree' in a git commit.",
            NO_WORKTREE)

    # Primed check (skippable per-commit with WORKFLOW:no-prime)
    if not _primed(project_dir) and NO_PRIME not in inline_cmd:
        return (
            "session-prime-gate: not primed. Run `/prime-core` first (loads project context + writes "
            ".claude/state/primed). Bypass: PRIME_GATE=0, or `touch .claude/state/prime-bypass`, or "
            "'WORKFLOW:no-prime' in a git commit.",
            NO_PRIME)

    return None

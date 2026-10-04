"""parallel_gate as a pre_tool guard (hook consolidation PR 6) — the old hook's body, moved verbatim.
Block committing a plan whose parallel batches collide on files.

Fires on a `git commit` that stages a file under docs/superpowers/plans/** (excluding TEMPLATE*).
For a plan with >=2 `Task N` blocks (any `## `..`#### ` heading level) it enforces two things:
  1. a `## Parallelization` section MUST exist (else the plan claims tasks but never declares how
     they parallelize — BLOCK); and
  2. within any declared batch, no two member tasks may touch the SAME file (Create/Modify) — that
     is a write–write race two agents would hit at once (BLOCK, naming the path + the two tasks).

Bypass a genuinely serial/trivial plan with `WORKFLOW:no-parallel` in the commit command. Fail-open
on any git/parse error. Structure mirrors grill_gate.py (staged-path collection, cwd resolution,
dual-form block JSON) — only the per-file CHECK differs.
"""
import os
import re
import shlex

from _lib.git import run_memo
from _lib.parallel_parse import evaluate as _evaluate_plan

PLAN_PREFIX = "docs/superpowers/plans/"
GIT_COMMIT_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)*commit\b")
GIT_DASH_C_RE = re.compile(r"\bgit\s+-C\s+(\S+)")
GIT_CD_RE = re.compile(r"^\s*cd\s+(\S+)")
SHELL_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||;|\n|\|")
ADD_STAGES_EVERYTHING_FLAGS = ("-A", "--all", "-u", "--update")
COMMIT_ALL_LONG = "--all"
BYPASS_SENTINEL = "WORKFLOW:no-parallel"


def _resolve_git_cwd(command: str, cwd: str) -> str:
    """Effective cwd of the `git commit` invocation (honors a leading `cd` + explicit `git -C`)."""
    base = cwd
    for segment in SHELL_SEGMENT_SPLIT_RE.split(command):
        cd = GIT_CD_RE.match(segment)
        if cd:
            target = cd.group(1).strip("'\"")
            base = target if os.path.isabs(target) else os.path.join(base or ".", target)
        if GIT_COMMIT_RE.search(segment):
            m = GIT_DASH_C_RE.search(segment)
            if m:
                target = m.group(1).strip("'\"")
                return target if os.path.isabs(target) else os.path.join(base or ".", target)
            return base
    return base


def _run_git(cwd: str, *args, record: bool = True) -> str | None:
    return run_memo("parallel_gate", cwd, ["git", *args], timeout=5, record=record)  # PR 6: per-call memo


def _staged_names(cwd: str) -> list:
    out = _run_git(cwd, "diff", "--cached", "--name-only")
    return [p.strip() for p in out.splitlines() if p.strip()] if out else []


def _add_segment_stages_everything(segment: str) -> bool:
    m = re.search(r"\bgit\s+add\b(.*)$", segment)
    if not m:
        return False
    try:
        tokens = shlex.split(m.group(1))
    except ValueError:
        tokens = m.group(1).split()
    if any(t in ADD_STAGES_EVERYTHING_FLAGS for t in tokens):
        return True
    return any(t in (".", "./") for t in tokens if not t.startswith("-"))


def _explicit_add_paths(segment: str) -> list:
    m = re.search(r"\bgit\s+add\b(.*)$", segment)
    if not m:
        return []
    try:
        tokens = shlex.split(m.group(1))
    except ValueError:
        tokens = m.group(1).split()
    return [t for t in tokens if t and not t.startswith("-")]


def _would_be_staged_everything(cwd: str) -> list:
    out = _run_git(cwd, "status", "--porcelain", "--untracked-files=all")
    if not out:
        return []
    paths = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        rest = line[3:].strip()
        if " -> " in rest:
            rest = rest.split(" -> ", 1)[1].strip()
        if len(rest) >= 2 and rest[0] == '"' and rest[-1] == '"':
            rest = rest[1:-1]
        if rest:
            paths.append(rest)
    return paths


def _collect_staged(command: str, cwd: str) -> list:
    """Everything already staged, PLUS what a same-command chained `git add` would stage."""
    paths = list(_staged_names(cwd))
    for segment in SHELL_SEGMENT_SPLIT_RE.split(command):
        if not re.search(r"\bgit\s+add\b", segment):
            continue
        if _add_segment_stages_everything(segment):
            paths.extend(_would_be_staged_everything(cwd))
        else:
            paths.extend(_explicit_add_paths(segment))
    return paths


def _is_plan_path(path: str) -> bool:
    norm = path.lstrip("./")
    if not norm.startswith(PLAN_PREFIX):
        return False
    base = os.path.basename(norm)
    return not base.upper().startswith("TEMPLATE")


def _commit_stages_all(command: str) -> bool:
    seg = next(
        (s for s in SHELL_SEGMENT_SPLIT_RE.split(command) if GIT_COMMIT_RE.search(s)),
        command,
    )
    m = re.search(r"\bcommit\b(.*)$", seg)
    if not m:
        return False
    try:
        tokens = shlex.split(m.group(1))
    except ValueError:
        tokens = m.group(1).split()
    for t in tokens:
        if t == COMMIT_ALL_LONG:
            return True
        if t.startswith("--"):
            continue
        if t.startswith("-") and len(t) > 1:
            for ch in t[1:]:
                if ch == "a":
                    return True
                if ch == "m":
                    break
    return False


def _modified_tracked(cwd: str) -> list:
    out = _run_git(cwd, "diff", "--name-only")
    return [p.strip() for p in out.splitlines() if p.strip()] if out else []


def _file_text(cwd: str, path: str, prefer_worktree: bool = False) -> str | None:
    def _worktree() -> str | None:
        full = path if os.path.isabs(path) else os.path.join(cwd or ".", path)
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return None

    def _staged() -> str | None:
        return _run_git(cwd, "show", f":{path}", record=False)  # #979/item2 — worktree fallback below

    if prefer_worktree:
        t = _worktree()
        return t if t is not None else _staged()
    t = _staged()
    return t if t is not None else _worktree()


def _check_plan(text: str, notes: list | None = None) -> str | None:
    """Return a block reason, or None to allow. Appends dropped-bullet breadcrumbs to `notes`.

    The parsing + analysis live in `_lib.parallel_parse.evaluate` (#663 — shared with
    `parallel_nudge`); this function only decides which of `evaluate`'s signals BLOCK a commit and
    which merely surface a note (same wording as the retired standalone hook, for test parity).
    """
    ev = _evaluate_plan(text)
    if notes is not None:
        notes.extend(ev["notes"])
    if ev["unclosed"]:
        return (
            "has an unclosed code fence — plan can't be parsed for parallel batches. Close the "
            "``` / ~~~ block."
        )
    if not ev["tasks"]:
        # #556: a '## Parallelization' section with ZERO parseable tasks used to collapse into
        # "trivial/no tasks" and allow silently. Fail loud — the batches can't be collision-checked.
        if ev["has_par"]:
            return (
                "has a '## Parallelization' section but no parseable 'Task <id>' blocks — its "
                "batches can't be checked for file collisions. Add '### Task <id>' headers "
                "(numeric like '1' or letter-prefixed like 'A1')."
            )
        return None
    # #668: a batch referencing an unrecognized task id BLOCKs loudly regardless of how many OTHER
    # tasks parsed — even a single recognized task among >=2 declared batch members must be caught
    # (previously this check only ran once len(tasks) >= 2, so a 1-task partial parse slipped through).
    if ev["has_par"]:
        for _, unknown in ev["unknown"]:
            return (
                f"batch names task id(s) {unknown} with no matching '### Task <id>' block "
                f"(known task ids: {ev['known']}). Fix the batch id or add the task header."
            )
    if len(ev["tasks"]) < 2:
        return None
    if not ev["has_par"]:
        return (
            "declares >=2 tasks but has no '## Parallelization' section. Add one mapping tasks to "
            "batches (e.g. '- Batch 1: T1, T3'), or add 'WORKFLOW:no-parallel' for a serial plan."
        )
    if notes is not None:
        # #2 — a batch-named task with a `**Files:**` marker but ZERO parsed paths can't be
        # collision-checked. Don't block (prose plans are legit) — surface a note so the gap is
        # visible on stdout (exit-0 stderr is invisible to the agent).
        for nid in ev["nopath"]:
            notes.append(
                f"parallel_gate: task {nid} has a Files block but no parsable paths "
                "— not collision-checked"
            )
    if ev["collision"]:
        path, task_a, task_b = ev["collision"]
        return (
            f"file '{path}' is touched by BOTH Task {task_a} and Task {task_b} in the "
            "same batch — a write-write race for two parallel agents. Split the batch "
            "or give each task disjoint files."
        )
    return None


def check(ctx):
    # notes (#915): dropped-bullet / no-parsable-path breadcrumbs + the internal-error breadcrumb.
    # They ride ctx.notes, which pre_tool surfaces as a stdout systemMessage on the ALLOW path only
    # (exit-0 stderr is invisible to the agent); a block drops them, matching the standalone hook.
    notes: list = []
    try:
        command = ctx.command
        cwd = ctx.data.get("cwd", "")
        if not GIT_COMMIT_RE.search(command):
            return None
        if BYPASS_SENTINEL in command:
            return None
        git_cwd = _resolve_git_cwd(command, cwd)
        stages_all = _commit_stages_all(command)
        paths = list(_collect_staged(command, git_cwd))
        if stages_all:
            paths.extend(_modified_tracked(git_cwd))
        seen = set()
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            if not _is_plan_path(path):
                continue
            text = _file_text(git_cwd, path, prefer_worktree=stages_all)
            if text is None:
                continue  # unreadable → fail open for this file
            reason = _check_plan(text, notes)
            if reason:
                return (  # block drops notes (never reached ctx.notes) — matches the standalone
                    f"Blocked: plan '{path}' {reason} (see rules/workflow.md Adherence). Bypass a "
                    f"genuinely serial plan with '{BYPASS_SENTINEL}' in the commit command."
                )
        if notes:
            ctx.notes.extend(notes)
        return None
    except Exception as e:  # noqa: BLE001 — never brick a session; surface the gap (#915 / #3)
        # exit-0 with no output hides that a plan went UNCHECKED — surface it on stdout (systemMessage).
        ctx.notes.append(f"parallel_gate: internal error {e!r} — plan NOT collision-checked")
        return None

"""plan_interview_gate as a pre_tool guard (hook consolidation PR 6) — the old hook's body, moved verbatim.
Block committing a PLAN with no non-empty `## Questions resolved`.

Deliverable H (design §9). An EXACT sibling of grill_gate: fires on a `git commit` that stages a
plan under docs/superpowers/plans/** (excluding TEMPLATE*), and BLOCKS unless that plan carries a
NON-EMPTY `## Questions resolved` section — the durable record of the GATE-1 plan-time interview
(the AskUserQuestion prompts + the human's answers `writing-plans` runs before finalizing). This keeps
the human in the loop at design time even though BUILD runs autonomously (model D). Gating on a
doc SECTION (not a transcript scan) is transcript-independent: AskUserQuestion is main-session-only, so
a delegated builder can't call it, but the section proves the interview happened regardless of which
session wrote the plan.

Bypass a genuinely trivial plan with `WORKFLOW:no-interview` in the commit command. Fail-open on any
error. Distinct from grill_gate's `## Grill findings` (specs/plans/ADRs) — this gate is plans-only.
"""
import os
import re
import shlex

from _lib.git import run_memo

PLAN_PREFIXES = ("docs/superpowers/plans/",)
GIT_COMMIT_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)*commit\b")  # #555: -C-aware like parallel_gate
GIT_DASH_C_RE = re.compile(r"\bgit\s+-C\s+(\S+)")
GIT_CD_RE = re.compile(r"^\s*cd\s+(\S+)")
SHELL_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||;|\n|\|")
ADD_STAGES_EVERYTHING_FLAGS = ("-A", "--all", "-u", "--update")
COMMIT_ALL_LONG = "--all"
BYPASS_SENTINEL = "WORKFLOW:no-interview"
# A non-empty `## Questions resolved` section: the header, then at least one line of real content
# before EOF or the next `## ` header. Tolerate trailing text on the heading line (mirrors grill_gate
# #148) so an annotated header ("## Questions resolved (writing-plans, this session)") still counts.
QUESTIONS_HEADER_RE = re.compile(r"^\s*##\s+Questions resolved\b.*$", re.MULTILINE)
# A "real content" line records an interview answer, is a `- Q1 —` bullet, or (mirroring grill_gate
# #108) is ANY content bullet (`- <text>` / `* <text>`) — so a Q&A section written as prose bullets
# ALLOWs. A copied TEMPLATE with an UNFILLED table still BLOCKS: its skeleton has NO content bullets
# (only the instruction blockquote, the column-header row, the `|---|` separator, an empty-cell row).
ANSWER_RE = re.compile(
    r"\b(answer|answered|chose|decided|resolved|confirmed|clarified|agreed|q:|a:)\b",
    re.IGNORECASE,
)
QUESTION_BULLET_RE = re.compile(r"^\s*[-*]\s*Q\d+\b")
# Any bullet with real content after the marker — the general widening for prose-style Q&A.
CONTENT_BULLET_RE = re.compile(r"^\s*[-*]\s+\S")


def _resolve_git_cwd(command: str, cwd: str) -> str:
    """Effective cwd of the `git commit` invocation.

    Walks the shell segments in order, applying a leading `cd <path>` so a
    `cd <worktree> && git commit` chain is judged against the WORKTREE's own
    staged set — not the session's PRIMARY checkout, whose concurrent staged
    plans would otherwise leak into the gate decision (#470). An explicit
    `git -C <path>` on the commit segment still wins (resolved against the
    current cd base). ponytail: plain `cd <path>` only — no pushd/popd, no
    `cd -`, no subshell scoping; those never appeared in the observed misfire.
    """
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
    return run_memo("plan_interview_gate", cwd, ["git", *args], timeout=5, record=record)  # PR 6: per-call memo


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
    if not norm.startswith(PLAN_PREFIXES):
        return False
    base = os.path.basename(norm)
    # TEMPLATE* files intentionally carry an empty skeleton — never self-block them.
    return not base.upper().startswith("TEMPLATE")


def _commit_stages_all(command: str) -> bool:
    """True if the `git commit` command auto-stages modified tracked files (-a / --all / -am)."""
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
                if ch == "m":  # -m consumes the remainder of the cluster as the message
                    break
    return False


def _modified_tracked(cwd: str) -> list:
    """Tracked files with unstaged modifications — what a `git commit -a` would additionally stage."""
    out = _run_git(cwd, "diff", "--name-only")
    return [p.strip() for p in out.splitlines() if p.strip()] if out else []


def _file_text(cwd: str, path: str, prefer_worktree: bool = False) -> str | None:
    """Text of the version that will be committed.

    Normal commits use the STAGED blob (what `git add` recorded). A `git commit -a` stages the
    WORKTREE version at commit time, so for that path the worktree file is authoritative and must
    win over the stale index blob.
    """
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


def _is_table_separator(s: str) -> bool:
    return bool(s) and s.startswith("|") and set(s) <= set("|-: ") and "-" in s


def _table_cells(s: str) -> list:
    return [c.strip() for c in s.strip().strip("|").split("|")]


def _is_real_content(s: str) -> bool:
    return bool(
        ANSWER_RE.search(s)
        or QUESTION_BULLET_RE.search(s)
        or CONTENT_BULLET_RE.search(s)
    )


def _has_nonempty_questions_section(text: str) -> bool:
    """A FILLED questions-resolved section — not just the TEMPLATE skeleton.

    Excludes the instruction blockquote, the markdown table HEADER row (the row directly above a
    `|---|` separator), the separator itself, and empty-cell rows. Requires at least one remaining
    line that reads as real content — a Q&A/answer keyword, a `- Q\\d` bullet, or any content bullet.
    A copied TEMPLATE whose table is unfilled therefore BLOCKS. (Mirrors grill_gate exactly.)
    """
    m = QUESTIONS_HEADER_RE.search(text)
    if not m:
        return False
    after = text[m.end():]
    nxt = re.search(r"^\s*##\s+", after, re.MULTILINE)
    body = after[: nxt.start()] if nxt else after
    lines = body.splitlines()
    n = len(lines)
    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s:
            continue
        if s.startswith(">"):             # instruction blockquote — not content
            continue
        if _is_table_separator(s):        # |---| separator — not content
            continue
        if s.startswith("|"):             # a table row
            cells = _table_cells(s)
            if all(c == "" for c in cells):   # empty-cell data row — not content
                continue
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n and _is_table_separator(lines[j].strip()):
                continue                       # this is the column-header row — not content
            if _is_real_content(" ".join(cells)):
                return True
            continue
        if _is_real_content(s):           # a prose / bullet content line
            return True
    return False


def check(ctx):
    command = ctx.command
    cwd = ctx.data.get("cwd", "")
    if not GIT_COMMIT_RE.search(command):
        return None
    if BYPASS_SENTINEL in command:
        return None
    # anchor to the committing worktree (honors a leading `cd` + an explicit `git -C`)
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
        # `git commit -a` will stage the WORKTREE version → read that, not the stale index blob.
        text = _file_text(git_cwd, path, prefer_worktree=stages_all)
        if text is None:
            continue  # unreadable → fail open for this file
        if not _has_nonempty_questions_section(text):
            return (
                f"Blocked: '{path}' is a plan with no non-empty '## Questions resolved' "
                "section. Run the writing-plans interview (>=3 AskUserQuestion prompts) and "
                "record the Q&A (see rules/design-workflow.md, deliverable H). For a genuinely "
                f"trivial plan, add '{BYPASS_SENTINEL}' to the commit command — but prefer "
                "recording the interview."
            )
    return None

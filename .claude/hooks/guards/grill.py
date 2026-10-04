"""grill_gate as a pre_tool guard (hook consolidation PR 6) — the old hook's body, moved verbatim.
Block committing a spec/plan/ADR with no non-empty `## Grill findings`.

Fires on a `git commit` that stages a file under docs/superpowers/specs/**,
docs/superpowers/plans/** (issue #116 — a plan is a second GATE-1 artifact that must be grilled
post-writing-plans), or docs/decisions/** (an ADR). Each such file must contain a NON-EMPTY
`## Grill findings` section. Bypass a genuinely trivial doc with `WORKFLOW:no-grill` in the commit
command. Fail-open on any error.

NOTE (#146-T3): this hook does NOT (and structurally cannot) cover the plan-mode path
(~/.claude/plans/*.md) — that directory lives outside any project's git repo, so a plan written
there can never appear in `git diff --cached` for a project commit; widening SPEC_PREFIXES to
include it would be a no-op. `grill_nudge.py` (PostToolUse, WARN-only) is the mechanism that covers
that path instead, firing on the Write/Edit itself rather than at commit time.
"""
import os
import re
import shlex

from _lib.git import run_memo

SPEC_PREFIXES = (
    "docs/superpowers/specs/",
    "docs/superpowers/plans/",  # issue #116 — grill the plan too, not just the spec/ADR
    "docs/decisions/",
)
# #153: tolerate ANY global option between `git` and `commit` — value-flags (`-C <path>`, `-c <cfg>`,
# `--git-dir <p>`, …) consume their separate argument; plain flags (`--no-pager`, `-P`) don't. The
# trailing `(?!-)` rejects `commit-tree`/`commit-graph` (the `\b` alone matched the `-` word boundary).
GIT_COMMIT_RE = re.compile(
    r"\bgit\s+(?:(?:-C|-c|--git-dir|--work-tree|--namespace|--exec-path)\s+\S+\s+|-{1,2}\S+\s+)*commit\b(?!-)"
)
GIT_DASH_C_RE = re.compile(r"\bgit\s+-C\s+(\S+)")
GIT_CD_RE = re.compile(r"^\s*cd\s+(\S+)")
SHELL_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||;|\n|\|")
ADD_STAGES_EVERYTHING_FLAGS = ("-A", "--all", "-u", "--update")
COMMIT_ALL_LONG = "--all"
BYPASS_SENTINEL = "WORKFLOW:no-grill"
# A non-empty `## Grill findings` section: the header, then at least one line of real content
# before EOF or the next `## ` header.
# #148: tolerate trailing text on the heading line (e.g. an annotation like
# "## Grill findings   (grill-me, this session — required GATE-1 leg)") — the \b after
# "findings" still requires the literal word, `.*` just no longer forces end-of-line right after it.
GRILL_HEADER_RE = re.compile(r"^\s*##\s+Grill findings\b.*$", re.MULTILINE)
# A "real finding" line records a disposition, is a `- C1 —` finding bullet, or (issue #108) is ANY
# content bullet (`- <text>` / `* <text>`) — so a grill section written as prose bullets ("- design
# sound; no material weaknesses") ALLOWs instead of false-blocking. The disposition vocabulary is
# widened past the original fixed/parked/deferred/accepted to the words real grills actually use.
# A copied TEMPLATE with an UNFILLED table still BLOCKS: its skeleton has NO content bullets (only the
# instruction blockquote, the column-header row, the `|---|` separator, and an empty-cell data row).
DISPOSITION_RE = re.compile(
    r"\b(fixed|parked|deferred|accepted|resolved|mitigated|addressed|acknowledged|wontfix|"
    r"won't\s*fix|noted|ruled)\b",
    re.IGNORECASE,
)
FINDING_BULLET_RE = re.compile(r"^\s*[-*]\s*C\d+\b")
# Any bullet with real content after the marker — the general widening for prose-style grills.
CONTENT_BULLET_RE = re.compile(r"^\s*[-*]\s+\S")

# #709 spec-alignment gate — a FINAL spec commit also needs a `## Interview` (>=4 recorded Q&A).
SPEC_ONLY_PREFIX = "docs/superpowers/specs/"          # interview is required for specs, not plans/ADRs
INTERVIEW_BYPASS = "WORKFLOW:no-interview"
DRAFT_RE = re.compile(r"^\s*status:\s*draft\s*$", re.M)  # G3b front-matter escape — WIP spec commits freely
INTERVIEW_HDR = re.compile(r"^##\s+Interview\s*$", re.M)
# Canonical Q&A marker: a `- **Q...` bullet OR a `1. **Q...` numbered-list item (both forms show up
# in real specs — #909 found the numbered form silently counted as 0). plan_interview_gate uses a
# DIFFERENT header (`## Questions resolved`) and marker (`- Q\d`) with no count, so the two can't
# share one regex; this marker is the one that counts the live spec's Q&A entries as >=4 (#709).
QA_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s*\*\*Q", re.M)


def _spec_needs_interview(text, commit_cmd):
    """Return a block reason if a FINAL spec lacks a `## Interview` (>=4 Q&A), else None."""
    if INTERVIEW_BYPASS in commit_cmd:          # bypass token
        return None
    # (draft escape is handled by main()'s `is_final_spec and DRAFT_RE` pre-filter, which `continue`s
    # before this is ever called on a draft — so an internal DRAFT_RE branch here would be dead code.)
    if not INTERVIEW_HDR.search(text):
        return "spec is missing a '## Interview' section (>=4 recorded Q&A)"
    if len(QA_RE.findall(text)) < 4:
        return ("spec '## Interview' has fewer than 4 recorded Q&A "
                "(expected `- **Q...` bullets or `1. **Q...` numbered items)")
    return None


def _resolve_git_cwd(command: str, cwd: str) -> str:
    """Effective cwd of the `git commit` invocation.

    Walks the shell segments in order, applying a leading `cd <path>` so a
    `cd <worktree> && git commit` chain is judged against the WORKTREE's own
    staged set — not the session's PRIMARY checkout, whose concurrent staged
    specs/plans would otherwise leak into the gate decision (#470). An explicit
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
    return run_memo("grill_gate", cwd, ["git", *args], timeout=5, record=record)  # PR 6: per-call memo


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


def _is_spec_path(path: str) -> bool:
    norm = path.lstrip("./")
    if not norm.startswith(SPEC_PREFIXES):
        return False
    base = os.path.basename(norm)
    # *.gates.md acceptance ledgers live under plans/ but are NOT plans — the sibling plan .md
    # carries the findings (build_loop's resolve_plan excludes them too). Never block a ledger.
    if base.endswith(".gates.md"):
        return False
    # TEMPLATE* files intentionally carry an empty findings table — never self-block them.
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


def _in_merge(cwd: str) -> bool:
    """True if a merge is in progress (MERGE_HEAD exists) — resolved via `--git-path` so a
    worktree's own `.git/worktrees/<name>/MERGE_HEAD` is checked, not the primary checkout's (#996).
    """
    out = _run_git(cwd, "rev-parse", "--git-path", "MERGE_HEAD", record=False)
    if out is None:
        return False
    out = out.strip()
    full = out if os.path.isabs(out) else os.path.join(cwd or ".", out)
    return os.path.isfile(full)


def _unchanged_from_merge_head(cwd: str, path: str) -> bool:
    """True if `path`'s staged blob is identical to its blob at MERGE_HEAD — it arrived unchanged
    from the OTHER parent during a sync merge (#996), so the local author can't grill it and the
    gate must not block on it. An author edit during the merge changes the staged blob, so it
    still gets checked normally.
    """
    staged = _run_git(cwd, "rev-parse", f":{path}", record=False)
    if staged is None:
        return False
    other = _run_git(cwd, "rev-parse", f"MERGE_HEAD:{path}", record=False)
    if other is None:
        return False
    return staged.strip() == other.strip()


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


def _is_real_finding(s: str) -> bool:
    return bool(
        DISPOSITION_RE.search(s)
        or FINDING_BULLET_RE.search(s)
        or CONTENT_BULLET_RE.search(s)
    )


def _has_nonempty_grill_section(text: str) -> bool:
    """A FILLED grill section — not just the TEMPLATE skeleton.

    Excludes the instruction blockquote, the markdown table HEADER row (the row directly above a
    `|---|` separator), the separator itself, and empty-cell rows. Requires at least one remaining
    line that reads as a real finding — a disposition keyword, a `- C\\d` finding bullet, or (issue
    #108) any content bullet. A copied TEMPLATE whose table is unfilled therefore BLOCKS.
    """
    m = GRILL_HEADER_RE.search(text)
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
            if _is_real_finding(" ".join(cells)):
                return True
            continue
        if _is_real_finding(s):           # a prose / bullet finding line
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
    in_merge = _in_merge(git_cwd)
    seen = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        if not _is_spec_path(path):
            continue
        # #996 — a sync merge commit bringing this spec/plan in UNCHANGED from the other parent:
        # the branch author can't fix someone else's historical spec, so skip it entirely.
        if in_merge and _unchanged_from_merge_head(git_cwd, path):
            continue
        # `git commit -a` will stage the WORKTREE version → read that, not the stale index blob.
        text = _file_text(git_cwd, path, prefer_worktree=stages_all)
        if text is None:
            continue  # unreadable → fail open for this file
        is_final_spec = path.lstrip("./").startswith(SPEC_ONLY_PREFIX)
        # G3b — a draft spec commits freely (grill + interview both waived); WIP versions normally.
        if is_final_spec and DRAFT_RE.search(text):
            continue
        if not _has_nonempty_grill_section(text):
            return (
                f"Blocked: '{path}' is a spec/plan/ADR with no non-empty '## Grill findings' "
                "section. Run grill-me and record findings + dispositions (see "
                "rules/workflow-adherence.md). For a genuinely trivial doc, add "
                f"'{BYPASS_SENTINEL}' to the commit command — but prefer recording the grill."
            )
        if is_final_spec:  # #709 — a finalized spec must also record its `## Interview` (>=4 Q&A)
            msg = _spec_needs_interview(text, command)
            if msg:
                return (
                    f"Blocked: '{path}' {msg}. Run the spec interview (>=4 AskUserQuestion Q&A) "
                    "and record it under '## Interview' (see rules/design-workflow.md). "
                    f"bypass: '{INTERVIEW_BYPASS}' in the commit command, or mark 'status: draft'."
                )
    return None

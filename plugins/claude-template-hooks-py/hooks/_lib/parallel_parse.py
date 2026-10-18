"""Shared plan parser for `parallel_gate` (guards/parallel.py) and `parallel_nudge` (post_nudges.py)
— issue #663. Both hooks need the SAME answer to "what tasks/batches/files does this plan declare",
so the parsing lives here ONCE and each caller only adds its own commit-time vs write-time plumbing
and its own ALLOW/BLOCK vs WARN wording.

`evaluate(text)` is the single entry point: a pure function (no git, no filesystem) that returns a
dict describing the plan's tasks, batches, and any structural problems (unknown batch ids, a
Files-marked task with zero parsable paths, a same-batch file collision). Callers decide what to do
with each signal — the gate BLOCKs a subset of them, the nudge WARNs on all of them, never blocking.

Node twin: hooks/_lib/parallel_parse.cjs — keep both byte-for-byte equivalent in behavior.
"""
import os
import re

TASK_HEADER_RE = re.compile(r"^\s*(#{2,4})\s+Task\s+([A-Za-z]*\d+)\b")  # `## `..`#### ` Task <id>
HEADING_RE = re.compile(r"^\s*(#{1,6})\s+")  # any heading; depth <= the task's own ends the task (#929.2)
FILES_MARKER_RE = re.compile(r"\*\*Files:\*\*")
# A `**Label:**` marker (e.g. **Interfaces:**) ends the Files block (#915) — EXCEPT `**Notes:**`
# (#929.4), which is a common in-block annotation, not a section boundary; files listed after it
# must still be collected.
LABEL_MARKER_RE = re.compile(r"^\s*\*\*[^*]+:\*\*")
NOTES_LABEL_RE = re.compile(r"^\s*\*\*Notes?:\*\*", re.IGNORECASE)
BULLET_RE = re.compile(r"^\s*[-*]\s+")
CHECKBOX_RE = re.compile(r"^\[[ xX]?\]")
CHECKBOX_LINE_RE = re.compile(r"^\s*[-*]\s+\[[ xX]?\]")
FENCE_OPEN_RE = re.compile(r"^\s*(`{3,}|~{3,})")
# An explicit WRITE verb (`Create:`/`Modify:`/`Add:`/`Delete:`/`Edit:`/`Test:`). When present, the
# next single token is the path — even extensionless (`- Modify: Makefile`, `- Create: Dockerfile`).
FILE_VERB_RE = re.compile(r"^(?:Create|Modify|Add|Delete|Edit|Test)\s*:\s*", re.IGNORECASE)
# A generic `Label:` prefix (single- or multi-word, letters/slash/space — e.g. `Spec:`, `Set up:`,
# `Create/Modify:`), stripped before the path-like check (#929.3 widened this to multi-word labels).
GENERIC_VERB_RE = re.compile(r"^[A-Za-z][A-Za-z/ ]*\s*:\s*")
NONFILE_PREFIX_RE = re.compile(
    r"^(?:Produces|Consumes|Interfaces|Depends|Decision|Gap|Note|Rationale|Why|Risk|Assumption)\b",
    re.IGNORECASE,
)
PATH_TOKEN_RE = re.compile(r"^(?:`([^`]+)`|([^\s`]*[/.][^\s`]*))")
ANY_TOKEN_RE = re.compile(r"^(?:`([^`]+)`|(\S+))")
# A real file with no extension that a verb/label-stripped bullet otherwise drops (#929.1): the
# common build/config filenames. Deliberately narrow — README/CHANGELOG are too often prose refs.
KNOWN_EXTENSIONLESS_RE = re.compile(
    r"^(Makefile|Dockerfile|Containerfile|Rakefile|Gemfile|Procfile|Jenkinsfile|Vagrantfile|LICENSE)$",
    re.IGNORECASE,
)
PARALLELIZATION_RE = re.compile(r"^\s*##\s+Parallelization\b", re.MULTILINE | re.IGNORECASE)
BATCH_LINE_RE = re.compile(r"^\s*[-*]\s*Batch\b.*?:\s*(.+?)\s*$", re.IGNORECASE)
BATCH_TASKNUM_RE = re.compile(r"\bT?([A-Za-z]*\d+)\b", re.IGNORECASE)
LINE_RANGE_SUFFIX_RE = re.compile(r":\d+(?:-\d+)?$")


def clean_path(raw: str) -> str:
    """Strip surrounding backticks and a trailing :line-range suffix (e.g. `f.py:12-40` -> f.py)."""
    s = raw.strip().strip("`").strip()
    s = LINE_RANGE_SUFFIX_RE.sub("", s)
    return os.path.normpath(s) if s else s


def file_path_from_bullet(line: str) -> str | None:
    """A FILE bullet's path, or None when the line doesn't name a file.

    Rejects `- [ ]` step checkboxes and `- Produces:/Consumes:/Interfaces:` interface declarations.
    With an explicit write verb the next token is the path, extensionless included. Otherwise a
    `Label:` prefix (single- or multi-word) is stripped and the first token must be path-like
    (backticked, containing `/` or `.`, or a known extensionless filename — #929.1/#929.3).
    Returning None is "skip this line" — the caller keeps scanning, it does NOT close the Files block.
    """
    m = BULLET_RE.match(line)
    if not m:
        return None
    rest = line[m.end():]
    if CHECKBOX_RE.match(rest) or NONFILE_PREFIX_RE.match(rest):
        return None
    fv = FILE_VERB_RE.match(rest)
    if fv:
        tok = ANY_TOKEN_RE.match(rest[fv.end():])
        return clean_path(tok.group(1) or tok.group(2)) if tok else None
    gv = GENERIC_VERB_RE.match(rest)
    rest_after = rest[gv.end():] if gv else rest
    pm = PATH_TOKEN_RE.match(rest_after)
    if pm:
        return clean_path(pm.group(1) or pm.group(2))
    tok = ANY_TOKEN_RE.match(rest_after)
    if tok:
        candidate = clean_path(tok.group(1) or tok.group(2))
        if KNOWN_EXTENSIONLESS_RE.match(candidate):
            return candidate
    return None


def strip_fenced(text: str) -> tuple[str, bool]:
    """Drop every ``` / ~~~ fenced-code line (incl. the fences). Returns (stripped, unclosed)."""
    out = []
    fence_char = None
    fence_len = 0
    for line in text.splitlines():
        if fence_char is None:
            m = FENCE_OPEN_RE.match(line)
            if m:
                run = m.group(1)
                fence_char, fence_len = run[0], len(run)
                continue
            out.append(line)
        else:
            s = line.strip()
            if s and set(s) == {fence_char} and len(s) >= fence_len:
                fence_char, fence_len = None, 0
    return "\n".join(out), fence_char is not None


def is_write_verb_bullet(line: str) -> bool:
    m = BULLET_RE.match(line)
    return bool(m and FILE_VERB_RE.match(line[m.end():]))


def norm_id(task_id: str) -> str:
    """`T1` normalizes to `1`; a letter-prefixed id (`A1`) is preserved."""
    m = re.match(r"^[Tt](\d.*)$", task_id.strip())
    return m.group(1) if m else task_id.strip()


def parse_tasks(text: str, notes: list | None = None) -> tuple:
    """({task_id: set(paths)}, files_marked) over already fence-stripped `text`.

    A task block ends at a heading whose depth is <= the task header's own depth (#929.2 — a deeper
    sub-heading like `#### Steps` placed inside a task no longer ends it), a `**Label:**` marker
    (except `**Notes:**`, #929.4), or the first `- [ ]` step-checkbox line.
    """
    tasks: dict = {}
    files_marked: set = set()
    cur = None
    in_files = False
    closed_by_checkbox = False
    for line in text.splitlines():
        m = TASK_HEADER_RE.match(line)
        if m:
            cur = m.group(2)
            cur_depth = len(m.group(1))
            tasks.setdefault(cur, set())
            in_files = False
            closed_by_checkbox = False
            continue
        hm = HEADING_RE.match(line)
        if cur is not None and hm and len(hm.group(1)) <= cur_depth:
            cur = None
            in_files = False
            closed_by_checkbox = False
            continue
        if cur is None:
            continue
        if FILES_MARKER_RE.search(line):
            in_files = True
            closed_by_checkbox = False
            files_marked.add(cur)
            continue
        if in_files:
            if LABEL_MARKER_RE.match(line) and not NOTES_LABEL_RE.match(line):
                in_files = False
                continue
            if CHECKBOX_LINE_RE.match(line):
                in_files = False
                closed_by_checkbox = True
                continue
            path = file_path_from_bullet(line)
            if path:
                tasks[cur].add(path)
            continue
        if closed_by_checkbox and is_write_verb_bullet(line) and notes is not None:
            notes.append(
                f"parallel_gate: note — write-verb bullet after a step checkbox in Task {cur} is "
                f"not counted as a file (move it above the step list): {line.strip()}"
            )
    return tasks, files_marked


def parse_batches(text: str) -> list:
    """List of (label, [task_nums]) for each `- Batch N: T1, T3` line under ## Parallelization."""
    pm = PARALLELIZATION_RE.search(text)
    if not pm:
        return []
    after = text[pm.end():]
    nxt = re.search(r"^\s*##\s+", after, re.MULTILINE)
    body = after[: nxt.start()] if nxt else after
    batches = []
    for i, line in enumerate(body.splitlines()):
        bm = BATCH_LINE_RE.match(line)
        if bm:
            nums = BATCH_TASKNUM_RE.findall(bm.group(1))
            batches.append((f"Batch {i}", nums))
    return batches


def evaluate(text: str) -> dict:
    """Pure parse + analysis of plan `text`. Both `parallel_gate` and `parallel_nudge` drive their
    ALLOW/BLOCK/WARN decisions off this ONE result (#663) instead of two independent parsers.

    Returns:
      unclosed: an unterminated ``` / ~~~ fence makes the rest of the plan unparseable.
      tasks: {normalized_id: set(paths)} — empty when `unclosed` or no `Task <id>` headers found.
      files_marked: {normalized_id} that carried a `**Files:**` marker (even with 0 parsed paths).
      has_par: a `## Parallelization` section exists.
      known: sorted list of normalized task ids.
      batches: [(label, [raw task tokens])] under `## Parallelization`.
      unknown: [(batch_label, [unknown raw ids])] — a batch referencing a task id with no
        matching header (#668 — surfaced regardless of how many OTHER tasks parsed).
      nopath: [normalized_id, ...] — batch-referenced tasks with a Files marker but 0 parsed paths.
      collision: (path, task_a, task_b) for the FIRST same-batch file collision found, else None.
      notes: breadcrumbs from `parse_tasks` (dropped bullets after a step checkbox).
    """
    notes: list = []
    result = {
        "unclosed": False,
        "tasks": {},
        "files_marked": set(),
        "has_par": False,
        "known": [],
        "batches": [],
        "unknown": [],
        "nopath": [],
        "collision": None,
        "notes": notes,
    }
    stripped, unclosed = strip_fenced(text)
    if unclosed:
        result["unclosed"] = True
        return result
    tasks, files_marked = parse_tasks(stripped, notes)
    has_par = bool(PARALLELIZATION_RE.search(stripped))
    result["has_par"] = has_par
    if not tasks:
        return result
    norm_tasks: dict = {}
    for tid, paths in tasks.items():
        norm_tasks.setdefault(norm_id(tid), set()).update(paths)
    norm_files_marked = {norm_id(t) for t in files_marked}
    result["tasks"] = norm_tasks
    result["files_marked"] = norm_files_marked
    result["known"] = sorted(norm_tasks)
    if not has_par:
        return result
    batches = parse_batches(stripped)
    result["batches"] = batches
    nopath_noted: set = set()
    for label, nums in batches:
        unknown = sorted({tn for tn in nums if norm_id(tn) not in norm_tasks})
        if unknown:
            result["unknown"].append((label, unknown))
        for tn in nums:
            nid = norm_id(tn)
            if (nid in norm_files_marked and not norm_tasks.get(nid)
                    and nid not in nopath_noted):
                nopath_noted.add(nid)
                result["nopath"].append(nid)
        seen: dict = {}
        for tn in nums:
            nid = norm_id(tn)
            for path in norm_tasks.get(nid, set()):
                if path in seen and seen[path] != nid:
                    if result["collision"] is None:
                        result["collision"] = (path, seen[path], nid)
                seen[path] = nid
    return result

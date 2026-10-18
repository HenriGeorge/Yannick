"""ONE streaming pass over a Stop/PreCompact transcript (hook consolidation PR 7).

Replaces the four private copies of _tokenize/_skip_flags/_has_subcommand/_scan_transcript in
close_gate, close_issue_gate, docs_gate and precompact_evidence. Reads line by line, keeping only
the pending tool ids, never the whole file. Forward only: merges, reflect, issues and first_ts need
the whole session, so a backward scan would be wrong.

Speed: `has_subcommand` checks `prog in command/segment` BEFORE shlex. Without that, shlex over every
segment of every heredoc made each py gate O(command bytes) — 80-86 s on a 50 MB transcript (PR 7
measurement); with it the same scan takes < 1 s.

A check run's outcome, from what real transcripts record:
  pass     result without an `Exit code` prefix and without failure/lock text
  fail     `Exit code N` (N != 75), a background `failed`/non-zero notification, or — when a pipe
           masked the exit (`… | tail`) — a failure summary in the output
  lock     exit 75 / `test-lock: lock held` (another session holds bin/test-lock)
  notrun   is_error WITHOUT `Exit code` (hook deny, permission/user rejection) or a killed bg task
  unknown  no result seen (older transcripts, a still-running background task)
"""
import json
import os
import re
import shlex
import time
from datetime import datetime, timezone

from _lib.shell import SHELL_SEGMENT_SPLIT_RE, SHELL_TOOLS, ps_to_sh  # #1091: ONE shared split RE
from _lib.test_cmd import is_suite_run

GIT_VALUE_FLAGS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"})
GH_VALUE_FLAGS = frozenset({"-R", "--repo", "--hostname"})
# "A check ran" — the old close_gate TEST_RUNNER_RE, unchanged (suites AND lint; outcome not judged).
CHECK_RE = re.compile(r"\b(pytest|npm\s+test|vitest|cargo\s+test|go\s+test|bash\s+tests/run\.sh|"
                      r"npm\s+run\s+lint|ruff\s+check)\b")
REFLECT_MARKER_RE = re.compile(r"dev-reflect|docs\(lessons\):")
# Combined cheap gate: a Bash command's detectors (git commit, gh pr merge/issue create, reflect,
# suite/check run) can only fire if one of these needles is present. One scan skips all five on a
# heredoc body (the 50 MB hot path) — a pure SUPERSET of every detector's trigger, so detection is
# unchanged (hook consolidation PR 7). test_cmd is OR-ed in at the call site (it is runtime).
_BASH_PREFILTER_RE = re.compile(
    r"git|gh|dev-reflect|docs\(lessons\):|npm|pytest|vitest|cargo|go\s+test|jest|ruff\s+check|"
    r"bash\s+tests/run\.sh|yarn|pnpm|python|uv\s+run")
EXIT_CODE_RE = re.compile(r"Exit code (-?\d+)")
BG_STARTED_RE = re.compile(r"Command (?:running in background|was moved to the background)")
# mocha prints "N failing"; pytest/jest "N failed"; cargo "test result: FAILED"; a bare "^FAIL".
FAILED_SUMMARY_RE = re.compile(r"(?m)\b[1-9]\d*\s+fail(?:ed|ing)\b|^FAIL\b|test result: FAILED")
# a positive "N passed/passing" summary (mirrors FAILED_SUMMARY_RE's [1-9]\d* so "0 passed" is NOT a
# pass) — lets an exit-coded run with an explicit green summary stay a clean pass, while one with NO
# such summary is `unknown`, not an assumed pass (R2 HIGH-1, R3 E1).
PASS_SUMMARY_RE = re.compile(r"\b[1-9]\d*\s+pass(?:ed|ing)\b")
LOCK_HELD = "test-lock: lock held"
# is_error results that mean the command NEVER RAN (hook deny / permission / user rejection) — these
# are `notrun` (excluded from the verdict). Anything else is_error WITHOUT an Exit code is a
# kill/timeout/unknown error → `unknown` (so an OLDER pass can't silently become the verdict). (PR 7 R1)
DENIAL_RE = re.compile(r"^(?:Blocked:|Permission to use|This session is isolated|"
                       r"The user (?:doesn't|does not) want|The user chose)")
SCAN_BUDGET_S = 45.0  # internal deadline: emit partial results before the 60 s harness kill (PR 7 R1)
NOTE_RE = re.compile(r"<task-notification>(.*?)</task-notification>", re.S)
ASSISTANT_TOKENS = ("WORKFLOW:no-reflect", "WORKFLOW:no-verify", "WORKFLOW:no-follow-ups",
                    "WORKFLOW:no-docs")
RAW_TOKENS = ("WORKFLOW:no-plan-check",)  # plan_gate: anywhere in the file (today's semantics)


class Check:
    __slots__ = ("kind", "command", "outcome", "exit", "trust_exit")

    def __init__(self, kind, command, trust_exit=True):
        self.kind, self.command, self.outcome, self.exit = kind, command, "unknown", None
        # trust the paired `Exit code N` only when the suite is the last stage (code review R1).
        self.trust_exit = trust_exit


class Scan:
    def __init__(self):
        self.first_ts = None
        self.made_commit = self.did_merge = self.filed_issue = self.ran_reflect = False
        self.tokens = set()      # bypass tokens seen in assistant text
        self.raw_tokens = set()  # tokens seen anywhere in the raw file
        self.checks = []         # Check, in transcript order
        self.timed_out = False   # the scan hit its internal deadline (partial result)


def _tokenize(segment):
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def _skip_flags(tokens, i, value_flags):
    while i < len(tokens) and tokens[i].startswith("-") and tokens[i] != "-":
        i += 2 if ("=" not in tokens[i] and tokens[i] in value_flags) else 1
    return i


def has_subcommand(command, prog, path, value_flags):
    """`prog` (flag-tolerant) → `path` in order, in ANY shell segment (`git -C x commit`,
    `gh --repo o/r pr merge`). Substring prefilter first — see the module docstring."""
    if prog not in command:
        return False
    for segment in SHELL_SEGMENT_SPLIT_RE.split(command):
        if prog not in segment:
            continue
        tokens = _tokenize(segment)
        for i, t in enumerate(tokens):
            if t != prog:
                continue
            j, ok = i + 1, True
            for expected in path:
                j = _skip_flags(tokens, j, value_flags)
                if j >= len(tokens) or tokens[j] != expected:
                    ok = False
                    break
                j += 1
            if ok:
                return True
    return False


def parse_ts(raw):
    if not isinstance(raw, str) or not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _text(block):
    c = block.get("content")
    if isinstance(c, list):
        return " ".join(b.get("text", "") for b in c if isinstance(b, dict) and isinstance(b.get("text"), str))
    return c if isinstance(c, str) else ""


def _merge_ok(block, text):
    # #442: a pr_gate deny / runtime failure is an ATTEMPT, not a merge.
    return not block.get("is_error") and not text.lstrip().startswith("Blocked:")


def _classify(block, text, trust_exit=True):
    """Outcome of one check run. `trust_exit` is False when the suite is NOT the last stage of the
    command (`run.sh | grep X`, `run.sh && git commit`) — then the `Exit code N` is a LATER stage's
    status, so fall back to the text signals (code review R1)."""
    head = text.lstrip()
    m = EXIT_CODE_RE.match(head)
    if m and trust_exit:
        code = int(m.group(1))
        return ("pass" if code == 0 else "lock" if code == 75 else "fail"), code
    # exit not present, or present-but-untrusted → text signals first.
    if LOCK_HELD in text:
        return "lock", 75
    if FAILED_SUMMARY_RE.search(text):
        return "fail", None
    if m:  # an (untrusted) exit code is present: trust an explicit "N passed" as a pass, else `unknown`
        # — a killed run whose partial output happens to show "N passed" has NO exit code, so it is NOT
        # routed here and stays `unknown` (R2 HIGH-1, R3 E2).
        return ("pass", None) if PASS_SUMMARY_RE.search(text) else ("unknown", None)
    if block.get("is_error"):
        if DENIAL_RE.match(head):
            return "notrun", None   # never ran (hook deny / permission / user rejection)
        if BG_STARTED_RE.match(head):
            return "background", None
        return "unknown", None      # started, finished uncertainly (kill/timeout) — not an older pass
    if BG_STARTED_RE.match(head):
        return "background", None
    return "pass", 0


def _notes(text, background):
    if not isinstance(text, str) or "<task-notification>" not in text:
        return
    for blk in NOTE_RE.findall(text):
        tid = re.search(r"<tool-use-id>([^<]+)</tool-use-id>", blk)
        check = background.pop(tid.group(1), None) if tid else None
        if check is None:
            continue
        st = re.search(r"<status>(\w+)</status>", blk)
        ec = re.search(r"exit code (-?\d+)", blk)
        status, code = (st.group(1) if st else ""), (int(ec.group(1)) if ec else None)
        if status == "killed":
            check.outcome = "unknown"   # killed/stopped: started but didn't finish → not an older pass (R1 HIGH-7)
        elif status == "completed" and code in (None, 0):
            check.outcome, check.exit = "pass", 0
        else:
            check.outcome, check.exit = ("lock" if code == 75 else "fail"), code


def _suite_is_last_stage(command, test_cmd):
    """True when the suite run is the LAST top-level stage — so its paired `Exit code N` is really the
    suite's. `run.sh | grep X` / `run.sh && git commit` put the suite earlier, so the exit belongs to
    a later stage and must not be trusted as the suite's result (code review R1)."""
    segs = [(i, seg) for i, seg in enumerate(SHELL_SEGMENT_SPLIT_RE.split(command)) if seg.strip()]
    if not segs:
        return True
    last_idx = segs[-1][0]
    suite_idx = -1
    for i, seg in segs:
        if is_suite_run(seg, test_cmd):
            suite_idx = i
    return suite_idx == -1 or suite_idx == last_idx


def scan(path, test_cmd=None):
    """Raises OSError if the file can't be opened (callers fail open)."""
    s = Scan()
    pending, background = {}, {}  # tool_use id -> (is_merge, Check|None); id -> Check
    budget = SCAN_BUDGET_S
    ov = os.environ.get("STOP_GATE_SCAN_BUDGET_S")  # test/ops override of the internal deadline
    if ov:
        try:
            budget = float(ov)
        except ValueError:
            pass
    deadline = time.monotonic() + budget
    n = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            n += 1
            # sample the clock cheaply (every 16384 lines), but also on line 1 so a 0-budget override
            # trips immediately (R2 MEDIUM-4 testability).
            if (n == 1 or (n & 0x3FFF) == 0) and time.monotonic() > deadline:
                s.timed_out = True  # emit what we have before the 60 s harness kill (R1 MEDIUM)
                break
            if not line.strip():
                continue
            for tok in RAW_TOKENS:
                if tok in line:
                    s.raw_tokens.add(tok)
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            if s.first_ts is None:
                s.first_ts = parse_ts(ev.get("timestamp"))
            msg = ev.get("message")
            content = msg.get("content") if isinstance(msg, dict) else None
            if ev.get("type") == "user":
                if isinstance(content, str):
                    _notes(content, background)
                elif isinstance(content, list):
                    for b in content:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "text":
                            _notes(b.get("text"), background)
                        elif b.get("type") == "tool_result" and b.get("tool_use_id") in pending:
                            tid = b.get("tool_use_id")
                            merge, check = pending.pop(tid)
                            text = _text(b)
                            if merge and _merge_ok(b, text):
                                s.did_merge = True
                            if check is not None:
                                check.outcome, check.exit = _classify(b, text, check.trust_exit)
                                if check.outcome == "background":
                                    check.outcome = "unknown"
                                    background[tid] = check
                continue
            if ev.get("type") != "assistant" or not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use" and b.get("name") in SHELL_TOOLS:
                    cmd = (b.get("input") or {}).get("command", "")
                    if not isinstance(cmd, str):
                        continue
                    if b.get("name") == "PowerShell":
                        cmd = ps_to_sh(cmd)
                    if not (_BASH_PREFILTER_RE.search(cmd) or (test_cmd and test_cmd in cmd)):
                        continue  # no detector can fire — skip the full-command scans (speed)
                    if has_subcommand(cmd, "git", ("commit",), GIT_VALUE_FLAGS):
                        s.made_commit = True
                    merge = has_subcommand(cmd, "gh", ("pr", "merge"), GH_VALUE_FLAGS)
                    if has_subcommand(cmd, "gh", ("issue", "create"), GH_VALUE_FLAGS):
                        s.filed_issue = True
                    if REFLECT_MARKER_RE.search(cmd):
                        s.ran_reflect = True
                    check = (Check("suite", cmd, _suite_is_last_stage(cmd, test_cmd)) if is_suite_run(cmd, test_cmd)
                             else Check("check", cmd) if CHECK_RE.search(cmd) else None)
                    if check is not None:
                        s.checks.append(check)
                    if b.get("id") and (merge or check is not None):
                        pending[b["id"]] = (merge, check)
                elif b.get("type") == "tool_use" and b.get("name") == "Skill":
                    if "dev-reflect" in json.dumps(b.get("input") or {}):
                        s.ran_reflect = True
                elif b.get("type") == "text" and isinstance(b.get("text"), str):
                    t = b["text"]
                    if REFLECT_MARKER_RE.search(t):
                        s.ran_reflect = True
                    for tok in ASSISTANT_TOKENS:
                        if tok in t:
                            s.tokens.add(tok)
    return s


def last_verdict(s):
    """The verify leg's input: the last suite run that actually ran (or None), and whether ANY
    check ran. Lint never sets the verdict — it only satisfies "a check ran" (grill S1)."""
    ran = [c for c in s.checks if c.outcome != "notrun"]
    suites = [c for c in ran if c.kind == "suite"]
    return (suites[-1] if suites else None), bool(ran)


def verdict(s):
    """The verify leg's real input (R2 HIGH-2): the most recent suite with a DEFINITE result
    (pass/fail/lock) — so a later `unknown` run (killed/still-running) can't hide an earlier FAIL —
    plus whether the LATEST suite was itself `unknown`. Returns (Check|None, last_unknown)."""
    suites = [c for c in s.checks if c.kind == "suite" and c.outcome != "notrun"]
    if not suites:
        return None, False
    definite = [c for c in suites if c.outcome in ("pass", "fail", "lock")]
    return (definite[-1] if definite else None), (suites[-1].outcome == "unknown")


def last_suite(s):
    """The suite OUTCOME for the compaction snapshot — the most recent DEFINITE run, so a FAILED suite
    seen before compaction is not read as passing (R1 HIGH-4) and is not hidden by a later unknown
    (R2 HIGH-2). None when no suite had a definite result."""
    mr, _ = verdict(s)
    if mr is None:
        return None
    return {"outcome": mr.outcome, "exit": mr.exit, "command": mr.command}


def snapshot_flags(s):
    """The 8 precompact_evidence flag names, derived from one scan."""
    return {
        "made_commit": s.made_commit, "did_merge": s.did_merge, "ran_reflect": s.ran_reflect,
        "ran_test": last_verdict(s)[1], "filed_issue": s.filed_issue,
        "declared_none": "WORKFLOW:no-follow-ups" in s.tokens,
        "no_reflect": "WORKFLOW:no-reflect" in s.tokens, "no_verify": "WORKFLOW:no-verify" in s.tokens,
    }

#!/usr/bin/env python3
# dependencies = []
"""PostToolUse `post_nudges` — ONE process for the Write/Edit/Bash nudges (hook consolidation PR 4).
Matcher "Write|Edit|Bash".

Modules, in the retired hooks' wiring order (each self-filters on tool_name, exactly as before):
  skill_nudge         — Write/Edit of a SKILL.md → writing-skills notice (+ interview notice)
  grill_nudge         — plan without `## Grill findings` / spec without `## Interview` (WARN)
  parallel_nudge      — multi-task plan without `## Parallelization` or with a same-batch overlap
  scope_creep         — this session's edits crossed SCOPE_CREEP_THRESHOLD distinct files (once)
  suite_overrun_nudge — the full suite ran > SUITE_OVERRUN_THRESHOLD times this session (once)
  merge_autoff        — after `gh pr merge`, safely ff the main checkout (network git; runs LAST)

Never blocks. Several nudges on one call become ONE systemMessage joined with "\\n" (_dispatch). The
retired <name>.py files forward here with main(only=<name>). Fail-open: always exit 0.
"""
import json
import os
import random
import re
import sys
from pathlib import Path

from _dispatch import dispatch
from _lib.parallel_parse import evaluate as _pn_evaluate_plan

# #554 — shared age-based state GC. Guarded: a missing module degrades to no-GC, never a crash.
try:
    from _state_prune import gc_every as _gc_every
    from _state_prune import prune_stale as _prune_stale
except Exception:  # noqa: BLE001 - GC is best-effort; never block hook load
    _prune_stale = None

    def _gc_every(_env, default=50):
        return default

try:
    from _ff_checkout import ff_checkout_if_safe
except Exception:  # noqa: BLE001 — no primitive -> no-op, never crash
    ff_checkout_if_safe = None


# ---- skill_nudge ----------------------------------------------------------------------------------
# Matches .../skills/<name>/SKILL.md at any depth, forward or backward slashes.
SK_SKILL_MD_RE = re.compile(r"(^|[/\\])skills[/\\][^/\\]+[/\\]SKILL\.md$")
# A skill that takes arguments (frontmatter `argument-hint:`) is "choice-taking" and should run an
# interview; `## Interview` is the convention block that satisfies it.
SK_CHOICE_RE = re.compile(r"^argument-hint:", re.MULTILINE)
SK_INTERVIEW_RE = re.compile(r"^##\s+Interview\b", re.MULTILINE | re.IGNORECASE)

SK_NOTICE = (
    "Notice: you're editing a SKILL.md directly. Skill authoring/edits should go through the "
    "writing-skills methodology (not ad-hoc edits) — see skill-creator's quality "
    "checklist before shipping this skill."
)
SK_INTERVIEW_NOTICE = (
    "This skill takes arguments (argument-hint) but has no `## Interview` block — consider a "
    "≥4-question AskUserQuestion interview up front (one question at a time), and a "
    "/to-questionnaire pass AFTER it finishes (the before/after-skill feedback lifecycle). See "
    "the interview convention in design-workflow.md."
)


def _skill_nudge(data):
    try:
        tool_name = data.get("tool_name", "")
        if tool_name not in ("Write", "Edit"):
            return None
        file_path = data.get("tool_input", {}).get("file_path", "")
        if not isinstance(file_path, str) or not SK_SKILL_MD_RE.search(file_path):
            return None
        msgs = [SK_NOTICE]
        # Interview-convention nudge: a choice-taking skill with no `## Interview` block gets a WARN.
        try:
            with open(file_path, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
        except Exception:  # noqa: BLE001 - mirror node's `catch {}`; any read failure → base notice only
            body = ""
        if body and SK_CHOICE_RE.search(body) and not SK_INTERVIEW_RE.search(body):
            msgs.append(SK_INTERVIEW_NOTICE)
        return " ".join(msgs)
    except Exception:  # noqa: BLE001 - never brick a session
        return None


# ---- grill_nudge ----------------------------------------------------------------------------------
# One level deep under docs/superpowers/plans/ — matches grill_gate.py's own SPEC_PREFIXES shape.
GN_PLAN_PATH_RE = re.compile(r"(^|[/\\])docs[/\\]superpowers[/\\]plans[/\\][^/\\]+\.md$")
# The plan-mode path, anywhere under a `.claude/plans/` dir — deliberately NOT anchored to a
# specific $HOME so it matches regardless of machine/user.
GN_PLAN_MODE_PATH_RE = re.compile(r"(^|[/\\])\.claude[/\\]plans[/\\][^/\\]+\.md$")
# #709: any .md under docs/superpowers/specs/ (any depth) — the spec-interview WARN path, the
# write-time counterpart of grill_gate.py's commit-time BLOCK.
GN_SPEC_PATH_RE = re.compile(r"(^|[/\\])docs[/\\]superpowers[/\\]specs[/\\].+\.md$")

# #709 — the SAME 3 regexes grill_gate.py uses for its `## Interview` BLOCK, duplicated here
# (stdlib-only, no cross-hook import) so this write-time WARN fires in exactly the cases the BLOCK
# would deny: a spec missing `## Interview`, OR one with fewer than 4 recorded `- **Q...` Q&A.
GN_DRAFT_RE = re.compile(r"^\s*status:\s*draft\s*$", re.M)
GN_INTERVIEW_HDR = re.compile(r"^##\s+Interview\s*$", re.M)
GN_QA_RE = re.compile(r"^\s*[-*]\s*\*\*Q", re.M)

# #148: tolerate trailing text on the heading line (mirrors grill_gate.py's widening exactly).
GN_GRILL_HEADER_RE = re.compile(r"^\s*##\s+Grill findings\b.*$", re.MULTILINE)
# Mirrors grill_gate.py's finding-detection exactly (same disposition vocabulary + bullet shapes)
# so a plan that would satisfy the commit-time BLOCK never spuriously nudges here, and vice versa.
GN_DISPOSITION_RE = re.compile(
    r"\b(fixed|parked|deferred|accepted|resolved|mitigated|addressed|acknowledged|wontfix|"
    r"won't\s*fix|noted|ruled)\b",
    re.IGNORECASE,
)
GN_FINDING_BULLET_RE = re.compile(r"^\s*[-*]\s*C\d+\b")
GN_CONTENT_BULLET_RE = re.compile(r"^\s*[-*]\s+\S")

GN_NOTICE = (
    "Notice: this plan has no non-empty '## Grill findings' section yet. "
    "rules/workflow-adherence.md #5 requires grilling the PLAN (not just the design) before BUILD "
    "— run grill-me and record findings + dispositions. This never blocks; it's a reminder."
)
GN_SPEC_NOTICE = (
    "Notice: this spec has no '## Interview' section (>=4 recorded Q&A) yet. "
    "rules/design-workflow.md requires recording the spec interview (>=4 AskUserQuestion Q&A under "
    "'## Interview') before finalizing. This never blocks; it's a reminder."
)


def _gn_is_table_separator(s: str) -> bool:
    return bool(s) and s.startswith("|") and set(s) <= set("|-: ") and "-" in s


def _gn_table_cells(s: str) -> list:
    return [c.strip() for c in s.strip().strip("|").split("|")]


def _gn_is_real_finding(s: str) -> bool:
    return bool(
        GN_DISPOSITION_RE.search(s)
        or GN_FINDING_BULLET_RE.search(s)
        or GN_CONTENT_BULLET_RE.search(s)
    )


def _gn_has_nonempty_grill_section(text: str) -> bool:
    m = GN_GRILL_HEADER_RE.search(text)
    if not m:
        return False
    after = text[m.end():]
    nxt = re.search(r"^\s*##\s+", after, re.MULTILINE)
    body = after[: nxt.start()] if nxt else after
    for raw in body.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith(">"):
            continue
        if _gn_is_table_separator(s):
            continue
        if s.startswith("|"):
            cells = _gn_table_cells(s)
            if all(c == "" for c in cells):
                continue
            if _gn_is_real_finding(" ".join(cells)):
                return True
            continue
        if _gn_is_real_finding(s):
            return True
    return False


def _gn_is_watched_plan(path) -> bool:
    if not isinstance(path, str) or not path:
        return False
    if os.path.basename(path).upper().startswith("TEMPLATE"):
        return False
    return bool(GN_PLAN_PATH_RE.search(path) or GN_PLAN_MODE_PATH_RE.search(path))


def _gn_is_watched_spec(path) -> bool:
    if not isinstance(path, str) or not path:
        return False
    if os.path.basename(path).upper().startswith("TEMPLATE"):
        return False
    return bool(GN_SPEC_PATH_RE.search(path))


def _gn_spec_missing_interview(text) -> bool:
    """True if a FINAL spec lacks a `## Interview` (>=4 Q&A) — draft escapes. Agrees with grill_gate."""
    if GN_DRAFT_RE.search(text):
        return False
    if not GN_INTERVIEW_HDR.search(text):
        return True
    return len(GN_QA_RE.findall(text)) < 4


def _grill_nudge(data):
    try:
        if data.get("tool_name", "") not in ("Write", "Edit"):
            return None
        file_path = data.get("tool_input", {}).get("file_path", "")
        is_plan = _gn_is_watched_plan(file_path)
        is_spec = _gn_is_watched_spec(file_path)
        if not (is_plan or is_spec):
            return None
        try:
            with open(file_path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            return None  # missing/unreadable -> fail open
        if is_plan:
            if _gn_has_nonempty_grill_section(text):
                return None
            return GN_NOTICE
        # is_spec (#709) — write-time counterpart of grill_gate's `## Interview` BLOCK
        if not _gn_spec_missing_interview(text):
            return None
        return GN_SPEC_NOTICE
    except Exception:  # noqa: BLE001 - never brick a session
        return None


# ---- parallel_nudge -------------------------------------------------------------------------------
# #663: the parsing is shared with parallel_gate via `_lib.parallel_parse.evaluate` — this hook only
# decides which of `evaluate`'s signals get a WARN (it never blocks, unlike the gate).
PN_PLAN_PATH_RE = re.compile(r"(^|[/\\])docs[/\\]superpowers[/\\]plans[/\\][^/\\]+\.md$")
PN_PLAN_MODE_PATH_RE = re.compile(r"(^|[/\\])\.claude[/\\]plans[/\\][^/\\]+\.md$")


def _pn_is_watched_plan(path) -> bool:
    if not isinstance(path, str) or not path:
        return False
    if os.path.basename(path).upper().startswith("TEMPLATE"):
        return False
    return bool(PN_PLAN_PATH_RE.search(path) or PN_PLAN_MODE_PATH_RE.search(path))


def _parallel_nudge(data):
    try:
        if data.get("tool_name", "") not in ("Write", "Edit"):
            return None
        file_path = data.get("tool_input", {}).get("file_path", "")
        if not _pn_is_watched_plan(file_path):
            return None
        try:
            with open(file_path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            return None  # missing/unreadable -> fail open

        ev = _pn_evaluate_plan(text)
        if ev["unclosed"]:
            return None  # the gate BLOCKs this; the nudge has nothing useful to parse, stay silent
        if not ev["tasks"]:
            # #663/#556 parity: a '## Parallelization' section with ZERO parseable tasks is the same
            # silent-collapse the gate fails loud on — WARN here too (the nudge never blocks).
            if ev["has_par"]:
                return (
                    "Notice: this plan has a '## Parallelization' section but no parseable "
                    "'Task <id>' blocks — its batches can't be checked for file collisions. Add "
                    "'### Task <id>' headers (numeric like '1' or letter-prefixed like 'A1'). This "
                    "never blocks; it's a reminder."
                )
            return None  # nothing to parallelize

        if len(ev["tasks"]) < 2:
            return None  # nothing to parallelize

        if not ev["has_par"]:
            return (
                "Notice: this plan has {n} tasks but no '## Parallelization' section. "
                "Declare which tasks can run concurrently (e.g. '- Batch 1: T1, T3') so parallel "
                "implementers don't collide. This never blocks; it's a reminder."
            ).format(n=len(ev["tasks"]))

        if ev["collision"]:
            path, t_a, t_b = ev["collision"]
            return (
                "Notice: Parallelization batches Task {a} and Task {b} together, but both touch "
                "'{p}' — same-batch tasks that share a file will collide. Split them "
                "into different batches. This never blocks; it's a reminder."
            ).format(a=t_a, b=t_b, p=path)
        return None
    except Exception:  # noqa: BLE001 - never brick a session
        return None


# ---- scope_creep ----------------------------------------------------------------------------------
SC_DEFAULT_THRESHOLD = 20
SC_DEFAULT_GC_EVERY = 50  # probabilistic 1/N sweep so the scandir isn't paid every edit


def _scope_creep(data):
    try:
        if data.get("tool_name") not in ("Write", "Edit"):
            return None
        file_path = data.get("tool_input", {}).get("file_path", "")
        if not isinstance(file_path, str) or not file_path.strip():
            return None

        try:
            threshold = int(os.environ.get("SCOPE_CREEP_THRESHOLD", str(SC_DEFAULT_THRESHOLD)))
        except ValueError:
            threshold = SC_DEFAULT_THRESHOLD
        if threshold < 1:
            return None

        proj = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        session = str(data.get("session_id") or "nosession")
        state_dir = os.path.join(proj, ".claude", "state", "scope_creep")
        os.makedirs(state_dir, exist_ok=True)
        state_path = os.path.join(state_dir, session + ".json")

        state = {"files": [], "warned": False}
        try:
            with open(state_path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                state["files"] = [f for f in loaded.get("files", []) if isinstance(f, str)]
                state["warned"] = bool(loaded.get("warned"))
        except (OSError, json.JSONDecodeError, ValueError):
            pass

        files = set(state["files"])
        files.add(file_path)
        crossed = len(files) >= threshold and not state["warned"]
        state = {"files": sorted(files), "warned": state["warned"] or crossed}
        try:
            with open(state_path, "w", encoding="utf-8") as fh:
                json.dump(state, fh)
        except OSError:
            pass  # can't persist → still warn this once if crossed (best effort)

        # GC stale per-session state files (#554) via the shared helper. Probabilistic so the scandir
        # isn't paid every edit; this session's file was just rewritten (mtime=now) so it's never
        # pruned. STATE_GC_EVERY overrides the cadence (=1 forces a sweep, used by tests). Fail-open.
        gc_every = _gc_every("STATE_GC_EVERY", SC_DEFAULT_GC_EVERY)
        if _prune_stale and random.random() < 1.0 / gc_every:
            _prune_stale(state_dir)

        if crossed:
            return (
                f"Scope check: this session has edited {len(files)} distinct files (threshold "
                f"{threshold}). Changes are scattered — reconsider whether they all belong in one "
                "unit of work (R7/Ponytail: shortest diff that fully solves the task). If this is "
                "one coherent change, carry on; if not, consider splitting it."
            )
    except Exception:  # noqa: BLE001 - never brick a session
        return None
    return None


# ---- suite_overrun_nudge --------------------------------------------------------------------------
SO_DEFAULT_THRESHOLD = 3
# A full-suite run references the aggregate runner; a single case file (tests/test_<name>.sh) does not.
SO_FULL_SUITE_RE = re.compile(r"\brun\.sh\b")
# `run.sh --affected` runs a labelled subset, not the full suite — it never counts.
SO_AFFECTED_RE = re.compile(r"--affected\b")


def _so_threshold() -> int:
    raw = os.environ.get("SUITE_OVERRUN_THRESHOLD", "")
    try:
        return max(1, int(raw)) if raw.strip() else SO_DEFAULT_THRESHOLD
    except ValueError:
        return SO_DEFAULT_THRESHOLD


def _suite_overrun_nudge(data):
    try:
        if data.get("tool_name", "") != "Bash":
            return None
        tool_input = data.get("tool_input", {})
        command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
        if not command or not SO_FULL_SUITE_RE.search(command) or SO_AFFECTED_RE.search(command):
            return None

        threshold = _so_threshold()
        # session_id reaches a filename — strip anything but a safe charset so a crafted id can't
        # escape state_dir (R6 validate-external-input; mirrors loop_detector).
        raw_sid = data.get("session_id", "unknown") or "unknown"
        session_id = re.sub(r"[^A-Za-z0-9_-]", "", raw_sid) or "unknown"
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        state_dir = Path(project_dir) / ".claude" / "state" / "suite_overrun"
        state_file = state_dir / f"{session_id}.json"
        state = {"count": 0, "warned": False}
        try:
            loaded = json.loads(state_file.read_text())
            if isinstance(loaded, dict):
                state = {
                    "count": int(loaded.get("count", 0)),
                    "warned": bool(loaded.get("warned", False)),
                }
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            pass

        state["count"] += 1
        warn = state["count"] > threshold and not state["warned"]
        if warn:
            state["warned"] = True

        state_dir.mkdir(parents=True, exist_ok=True)
        # Atomic write (tmp+replace): parallel Bash calls in one message could race this file.
        tmp_file = state_dir / f"{session_id}.json.{os.getpid()}.tmp"
        tmp_file.write_text(json.dumps(state))
        os.replace(tmp_file, state_file)

        if warn:
            return (
                f"full test suite run {state['count']}× this session (>{threshold}). During "
                "fix-iteration run ONLY the affected standalone case files (lock-free) — e.g. "
                "`bash tests/test_<name>.sh` — and reserve `bin/test-lock -- bash tests/run.sh` "
                "for the integration gate once the batch is green (exit 75 = lock contention, "
                "back off and retry)."
            )
    except Exception:  # noqa: BLE001 - never brick a session
        return None
    return None


# ---- merge_autoff ---------------------------------------------------------------------------------
# After a `gh pr merge` tool call, safely ff the current repo's main checkout so a merged branch is
# immediately live (#fleet-freshness, Trigger A). Command-matched REGARDLESS of exit code — `gh pr
# merge` exits non-zero on local-cleanup failure even when the remote merge succeeded; the primitive
# self-guards (behind-check -> noop if nothing merged).
MA_GH_MERGE_RE = re.compile(r"\bgh\s+pr\s+merge\b")


def _merge_autoff(data):
    if ff_checkout_if_safe is None:
        return None
    if data.get("tool_name") != "Bash":
        return None
    ti = data.get("tool_input")  # truthy non-dict (e.g. "x", 5, [1]) -> no command (parity with .cjs)
    cmd = ti.get("command", "") if isinstance(ti, dict) else ""
    if not isinstance(cmd, str) or not MA_GH_MERGE_RE.search(cmd):
        return None
    # exit-0 stderr is invisible to the agent, so a declined post-merge ff must surface its reason as
    # part of the combined systemMessage (dispatch joins non-None returns); a genuine noop/ff is "".
    _verdict, reason = ff_checkout_if_safe(data.get("cwd") or os.getcwd())  # self-guarding
    return reason or None


MODULES = (
    ("skill_nudge", _skill_nudge),
    ("grill_nudge", _grill_nudge),
    ("parallel_nudge", _parallel_nudge),
    ("scope_creep", _scope_creep),
    ("suite_overrun_nudge", _suite_overrun_nudge),
    ("merge_autoff", _merge_autoff),  # network git — last, so a slow fetch never delays the nudges
)


def main(only=None) -> int:
    return dispatch("post_nudges", MODULES, only)


if __name__ == "__main__":
    sys.exit(main())

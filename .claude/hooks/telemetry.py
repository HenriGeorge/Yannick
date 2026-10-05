#!/usr/bin/env python3
# dependencies = []
"""PostToolUse `telemetry` — ONE process for everything that must see every tool call (hook
consolidation PR 4). Matcher "" (all tools).

Modules, in the retired hooks' wiring order:
  compact_suggester  — nudge /clear or /compact from the transcript's real token occupancy (#498)
  loop_detector      — warn when the last N tool calls are identical; loop rows to tool-events (#500/#511)
  tool_events        — metadata-only tool row to tool-events.jsonl (no bodies/prompts/diffs)
  capture_iterations — attempts-to-green per todo task → iterations.jsonl
  capture_failures   — classified failures + repeated-edit friction → failures.jsonl (redacted)

Every module keeps its sink, row format and stderr breadcrumb byte for byte (golden:
tests/test_hook_golden.sh). The retired <name>.py files forward here with main(only=<name>), so a
repo still wired to an old name behaves exactly as before. Fail-open: always exit 0.
"""
import hashlib
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from _dispatch import dispatch

try:
    from _telemetry_gate import telemetry_enabled
except Exception:  # noqa: BLE001 - degrade to enabled if the helper is missing
    def telemetry_enabled(_="."):  # type: ignore
        return True

# #554 — shared age-based state GC. Guarded: a missing module degrades to no-GC, never a crash.
try:
    from _state_prune import prune_stale as _prune_stale
except Exception:  # noqa: BLE001 - GC is best-effort; never block hook load
    _prune_stale = None


# ---- compact_suggester ----------------------------------------------------------------------------
CS_DEFAULT_WINDOW = 200000
CS_DEFAULT_FIRST_PCT = 70
CS_DEFAULT_STEP_PCT = 10
CS_CONTEXT_FIELDS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def _cs_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    try:
        return int(raw) if raw.strip() else default
    except ValueError:
        return default


def _cs_latest_context_tokens(transcript_path: str) -> int:
    """Context occupancy from the LAST assistant usage in the transcript (0 if none/unreadable)."""
    latest = 0
    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                usage = (rec.get("message") or {}).get("usage")
                if not isinstance(usage, dict):
                    continue
                tokens = sum(usage.get(k, 0) for k in CS_CONTEXT_FIELDS if isinstance(usage.get(k), int))
                if tokens:
                    latest = tokens  # last one wins
    except OSError:
        return 0
    return latest


def _compact_suggester(data):
    try:
        transcript_path = data.get("transcript_path", "")
        if not transcript_path or not Path(transcript_path).is_file():
            return None
        tokens = _cs_latest_context_tokens(transcript_path)
        if tokens <= 0:
            return None

        window = max(1, _cs_int_env("CONTEXT_COMPACT_WINDOW", CS_DEFAULT_WINDOW))
        first = _cs_int_env("CONTEXT_COMPACT_FIRST_PCT", CS_DEFAULT_FIRST_PCT)
        step = max(1, _cs_int_env("CONTEXT_COMPACT_STEP_PCT", CS_DEFAULT_STEP_PCT))
        pct = int(tokens * 100 / window)

        # basename so a crafted session_id ("../x", "a/b") can't escape the state dir
        session_id = os.path.basename(data.get("session_id") or "unknown") or "unknown"
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        state_dir = Path(project_dir) / ".claude" / "state" / "compact_suggester"
        state_file = state_dir / f"{session_id}.step"

        if pct < first:
            # below the first band (e.g. right after a /compact dropped occupancy) → re-arm: forget
            # the last step so the next climb past first% nudges again instead of staying silent
            # against a stale high-water step.
            try:
                state_file.unlink()
            except OSError:
                pass
            return None
        current_step = (pct - first) // step  # 0 at first band, 1 at first+step, ...

        last_step = -1
        try:
            last_step = int(state_file.read_text().strip())
        except (OSError, ValueError):
            last_step = -1
        if current_step <= last_step:
            return None

        state_dir.mkdir(parents=True, exist_ok=True)
        state_file.write_text(str(current_step))
        return (
            f"context ~{pct}% of the {window // 1000}k window — at a task boundary use "
            "/clear (fresh context, cheapest; the crumb is re-injected next session), or "
            "/compact to keep working this same task."
        )
    except Exception:  # noqa: BLE001 - never brick a session
        return None


# ---- loop_detector --------------------------------------------------------------------------------
LD_DEFAULT_WINDOW = 5
LD_GC_MAX_AGE_DAYS = 7  # prune per-session state files older than this
LD_DEFAULT_GC_EVERY = 50  # sweep on ~1/N calls to keep the hot path cheap


def _ld_window() -> int:
    raw = os.environ.get("LOOP_DETECT_WINDOW", "")
    try:
        return max(2, int(raw)) if raw.strip() else LD_DEFAULT_WINDOW
    except ValueError:
        return LD_DEFAULT_WINDOW


def _ld_gc_every() -> int:
    raw = os.environ.get("LOOP_DETECT_GC_EVERY", "")
    try:
        return max(1, int(raw)) if raw.strip() else LD_DEFAULT_GC_EVERY
    except ValueError:
        return LD_DEFAULT_GC_EVERY


def _ld_call_hash(tool_name: str, tool_input) -> str:
    try:
        params = json.dumps(tool_input, sort_keys=True, default=str)
    except (TypeError, ValueError):
        params = str(tool_input)
    return hashlib.md5(f"{tool_name}\0{params}".encode()).hexdigest()  # noqa: S324 - not security


def _loop_detector(data):
    try:
        tool_name = data.get("tool_name", "")
        if not tool_name:
            return None
        window = _ld_window()
        current = _ld_call_hash(tool_name, data.get("tool_input", {}))

        # session_id is external input reaching a filename — strip anything but a safe charset so a
        # crafted id (e.g. "../../x") can't escape state_dir (R6 validate-external-input; #518 review).
        raw_sid = data.get("session_id", "unknown") or "unknown"
        session_id = re.sub(r"[^A-Za-z0-9_-]", "", raw_sid) or "unknown"
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        state_dir = Path(project_dir) / ".claude" / "state" / "loop_detector"
        state_file = state_dir / f"{session_id}.json"
        state = {"ring": [], "warned": ""}
        try:
            loaded = json.loads(state_file.read_text())
            if isinstance(loaded, dict):
                state = {"ring": list(loaded.get("ring", [])), "warned": loaded.get("warned", "")}
        except (OSError, json.JSONDecodeError, ValueError):
            pass

        ring = (state["ring"] + [current])[-window:]
        warn = len(ring) >= window and all(h == current for h in ring) and state["warned"] != current
        state = {"ring": ring, "warned": current if warn else state["warned"]}

        # Persist the thrashing count (total occurrences of the current call in the sliding window) on
        # any detected repeat, so the /improve telemetry sees loops the warn-once gate would otherwise
        # hide. Best-effort — a failed write must never break the tool (#511). ts is epoch-int and the
        # row carries kind="loop" so the shared sink stays uniform with tool_events (#511 review).
        retry_count = sum(1 for h in ring if h == current)
        if retry_count >= 2 and telemetry_enabled(project_dir):
            try:
                tool_input = data.get("tool_input", {})
                row = {
                    "ts": int(datetime.now().timestamp()),
                    "kind": "loop",
                    "file": (tool_input.get("file_path", "") if isinstance(tool_input, dict) else ""),
                    "retry_count": retry_count,
                    "session_id": session_id,
                }
                tele_dir = Path(project_dir) / ".claude" / "telemetry"
                tele_dir.mkdir(parents=True, exist_ok=True)
                with open(tele_dir / "tool-events.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(row) + "\n")
            except Exception as e:  # noqa: BLE001 - best-effort; breadcrumb, never brick the tool
                print(f"loop_detector: telemetry write failed: {e}", file=sys.stderr)

        state_dir.mkdir(parents=True, exist_ok=True)
        # Atomic write (tmp+replace): this runs on EVERY tool call, so parallel calls in one message
        # race this file. Rename is atomic, so a concurrent reader never sees a torn write — worst
        # case a lost update (ring undercounts = a missed/late warning), tolerable for an advisory
        # warn-only module. ponytail: no lock; per-session lost-update is accepted (#518 review).
        tmp_file = state_dir / f"{session_id}.json.{os.getpid()}.tmp"
        tmp_file.write_text(json.dumps(state))
        os.replace(tmp_file, state_file)

        # GC leftover per-session files (#554) via the shared helper. Probabilistic so the scandir
        # isn't paid every call; the current session's file was just rewritten (mtime=now) so it's
        # never the one pruned. Guarded — a missing helper degrades to no-GC.
        if _prune_stale and random.random() < 1.0 / _ld_gc_every():
            _prune_stale(state_dir, LD_GC_MAX_AGE_DAYS)

        if warn:
            return (
                f"you may be stuck in a loop — the last {window} tool calls were identical "
                f"({tool_name}). Step back: re-read the goal, change approach, or ask."
            )
    except Exception:  # noqa: BLE001 - never brick a session
        return None
    return None


# ---- tool_events ----------------------------------------------------------------------------------
def _tool_events(data):
    # Coerce non-dict shapes to {} (a tool may deliver tool_response/tool_input as a string) — a bare
    # .get() on a str would raise and, since this fires on EVERY call, spam a traceback (#511 review).
    resp = data.get("tool_response")
    if not isinstance(resp, dict):
        resp = {}
    exit_code = resp.get("exit")
    if exit_code is None:
        exit_code = 1 if (resp.get("error") or resp.get("is_error")) else 0
    ti = data.get("tool_input")
    if not isinstance(ti, dict):
        ti = {}
    rec = {
        "ts": int(time.time()),
        "kind": "tool",                       # discriminator: this sink also carries loop_detector rows
        "tool": data.get("tool_name"),
        "exit": exit_code,
        "duration_ms": data.get("duration_ms"),
        "file": ti.get("file_path"),          # path only — never contents
        "retry_count": data.get("retry_count", 0),
        "session_id": data.get("session_id"),
    }
    try:
        proj = os.environ.get("CLAUDE_PROJECT_DIR", ".")
        if not telemetry_enabled(proj):
            return None
        out_dir = os.path.join(proj, ".claude", "telemetry")
        os.makedirs(out_dir, exist_ok=True)  # inside the guard — an unwritable path must not traceback
        with open(os.path.join(out_dir, "tool-events.jsonl"), "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception as e:  # noqa: BLE001 - best-effort; leave a breadcrumb, never brick the tool
        print(f"tool_events: telemetry write failed: {e}", file=sys.stderr)
    return None


# ---- capture_iterations ---------------------------------------------------------------------------
CI_TEST_RE = re.compile(r"\b(pytest|vitest|jest)\b|\btest\b|run\.sh")


def _ci_key(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]


def _ci_project_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR", "."))


def _ci_state_path(session_id: str) -> Path:
    return _ci_project_dir() / ".claude" / "state" / "session" / session_id / "iterations.json"


def _ci_load_state(session_id: str) -> dict:
    try:
        return json.loads(_ci_state_path(session_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _ci_save_state(session_id: str, state: dict) -> None:
    p = _ci_state_path(session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state), encoding="utf-8")


def _ci_clear_state(session_id: str) -> None:
    try:
        _ci_state_path(session_id).unlink()
    except OSError:
        pass


def _ci_finalize(session_id: str, state: dict) -> None:
    failed = int(state.get("tests_failed", 0))
    passed = bool(state.get("tests_passed", False))
    row = {
        "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "task_key": state.get("active_key", ""),
        "task_text": state.get("active_text", ""),
        "attempts": failed + (1 if passed else 0),
        "tests_failed": failed,
        "tests_passed": passed,
        "session_id": session_id,
    }
    if not telemetry_enabled(str(_ci_project_dir())):
        return
    out_dir = _ci_project_dir() / ".claude" / "telemetry"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "iterations.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _ci_handle_todo(session_id: str, todos: list, state: dict) -> None:
    completed = {
        _ci_key(t["content"])
        for t in todos
        if isinstance(t, dict) and t.get("status") == "completed" and isinstance(t.get("content"), str)
    }
    active_key = state.get("active_key")
    if active_key and active_key in completed:
        _ci_finalize(session_id, state)
        _ci_clear_state(session_id)
        state = {}

    for t in todos:
        if isinstance(t, dict) and t.get("status") == "in_progress" and isinstance(t.get("content"), str):
            content = t["content"]
            k = _ci_key(content)
            if state.get("active_key") != k:
                state = {"active_key": k, "active_text": content, "tests_failed": 0, "tests_passed": False}
            _ci_save_state(session_id, state)
            return


def _ci_handle_bash(session_id: str, tool_input: dict, tool_response, state: dict) -> None:
    if not state.get("active_key"):
        return
    command = tool_input.get("command", "")
    if not isinstance(command, str) or not CI_TEST_RE.search(command):
        return
    exit_code = None
    if isinstance(tool_response, dict):
        if isinstance(tool_response.get("exit"), int):
            exit_code = tool_response["exit"]
        else:
            exit_code = 1 if (tool_response.get("error") or tool_response.get("is_error")) else 0
    else:
        exit_code = 0
    if exit_code == 0:
        state["tests_passed"] = True
    else:
        state["tests_failed"] = int(state.get("tests_failed", 0)) + 1
    _ci_save_state(session_id, state)


def _capture_iterations(data):
    try:
        if data.get("hook_event_name") != "PostToolUse":
            return None
        session_id = data.get("session_id") or "unknown"
        tool_name = data.get("tool_name")
        tool_input = data.get("tool_input") or {}
        state = _ci_load_state(session_id)
        if tool_name == "TodoWrite":
            todos = tool_input.get("todos")
            if isinstance(todos, list):
                _ci_handle_todo(session_id, todos, state)
        elif tool_name in ("Bash", "PowerShell"):
            _ci_handle_bash(session_id, tool_input, data.get("tool_response"), state)
    except Exception as e:  # noqa: BLE001 - never brick a session
        print(f"capture_iterations: {e}", file=sys.stderr)
    return None


# ---- capture_failures -----------------------------------------------------------------------------
CF_RING_MAX = 8
CF_REPEAT_THRESHOLD = 3

CF_REDACTIONS = [
    re.compile(r"(ghp|gho|ghs|ghu)_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-(?:ant-|proj-)?[A-Za-z0-9-]{20,}"),  # hyphenated modern keys (sk-ant-…, sk-proj-…)
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(token|secret|password|api[_-]?key)\s*[=:]\s*\S+"),
]
CF_TEST_KWS = ("pytest", "vitest", "jest", "test")


def _cf_redact(text: str) -> str:
    for pat in CF_REDACTIONS:
        text = pat.sub("«redacted»", text)
    return text


def _cf_resp_exit(resp: dict):
    for k in ("exit", "exitCode", "returncode"):
        v = resp.get(k)
        if isinstance(v, int):
            return v
    return None


def _cf_classify(tool_name: str, tool_input: dict, resp: dict):
    """Return (kind, detail) for a failure, or None."""
    if tool_name in ("Bash", "PowerShell"):
        code = _cf_resp_exit(resp)
        errored = (code not in (0, None)) or bool(resp.get("error"))
        if not errored:
            return None
        cmd = str(tool_input.get("command", ""))
        low = cmd.lower()
        if "ruff" in low:
            kind = "lint_fail"
        elif "tsc" in low:
            kind = "type_fail"
        elif any(k in low for k in CF_TEST_KWS):
            kind = "test_fail"
        else:
            kind = "cmd_fail"
        detail = " | ".join(
            str(resp.get(k, "")) for k in ("error", "stderr", "stdout")
        ).strip(" |")
        return kind, (cmd + " :: " + detail).strip(" :")
    # non-Bash: a tool that returned an error is friction worth logging as blocked.
    if resp.get("error"):
        return "blocked", str(resp.get("error"))
    return None


def _cf_ring_repeated(project_dir: str, session_id: str, file_path: str) -> int:
    """Push file_path onto the per-session ring; return its consecutive-edit count in the last 8
    (the caller gates on CF_REPEAT_THRESHOLD and records the count in `detail`)."""
    state = (
        Path(project_dir) / ".claude" / "state" / "session" / session_id / "edits.json"
    )
    ring = []
    try:
        ring = json.loads(state.read_text(encoding="utf-8"))
        if not isinstance(ring, list):
            ring = []
    except (OSError, json.JSONDecodeError, ValueError):
        ring = []
    ring.append(file_path)
    ring = ring[-CF_RING_MAX:]
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps(ring), encoding="utf-8")
    except OSError:
        pass
    return ring.count(file_path)


def _capture_failures(data):
    try:
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input") or {}
        resp = data.get("tool_response")
        if not isinstance(resp, dict):
            resp = {}
        session_id = data.get("session_id", "unknown")
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or "."

        records = []
        hit = _cf_classify(tool_name, tool_input, resp)
        if hit:
            kind, detail = hit
            records.append(
                {
                    "kind": kind,
                    "tool": tool_name,
                    "file": tool_input.get("file_path", ""),
                    "detail": _cf_redact(str(detail)),
                }
            )

        if tool_name in ("Edit", "Write"):
            fp = tool_input.get("file_path")
            if fp:
                n = _cf_ring_repeated(project_dir, str(session_id), str(fp))
                if n >= CF_REPEAT_THRESHOLD:
                    records.append(
                        {"kind": "repeated_edit", "tool": tool_name, "file": fp, "detail": f"count={n}"}
                    )

        if not records:
            return None

        if not telemetry_enabled(project_dir):
            return None
        ts = int(time.time())  # epoch int — timezone/runtime-agnostic, matches the node twin + tool_events
        out_dir = Path(project_dir) / ".claude" / "telemetry"
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / "failures.jsonl", "a", encoding="utf-8") as f:
            for rec in records:
                rec = {"ts": ts, **rec, "session_id": session_id}
                f.write(json.dumps(rec) + "\n")
    except Exception as e:  # noqa: BLE001 — fail-open, never brick a session
        print(f"capture_failures: {e}", file=sys.stderr)  # breadcrumb so a real bug is diagnosable
    return None


MODULES = (
    ("compact_suggester", _compact_suggester),
    ("loop_detector", _loop_detector),
    ("tool_events", _tool_events),
    ("capture_iterations", _capture_iterations),
    ("capture_failures", _capture_failures),
)


def main(only=None) -> int:
    return dispatch("telemetry", MODULES, only)


if __name__ == "__main__":
    sys.exit(main())

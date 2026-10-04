#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Transparent, SAMPLED hook wrapper — capture a hook's DECISION without changing its behavior.

Invoked as:  hook_trace.py -- <real-hook argv...>

SAMPLING (issue #763). CLAUDE_HOOK_TRACE_SAMPLE is a float in [0,1] (default 0.0), the fraction of
invocations that are traced. Per call, sampled = random.random() < rate.

- NOT sampled (the default → ~zero steady-state overhead): FAST PATH — os.execvp REPLACES this
  process with the real hook. No subprocess, no capture, no trace row, no double-spawn. Transparent
  by construction (the hook owns the fds and the exit code). If execvp raises, fall back to the
  subprocess passthrough so the hook still runs (fail-open).
- Sampled: run the hook as a child, pass its stdout/stderr through BYTE-IDENTICAL, exit with its
  code, and record one metadata row to <CLAUDE_PROJECT_DIR>/.claude/telemetry/hook-events.jsonl
  (ts, event, hook, exit, decision, duration_ms, session_id). With CLAUDE_HOOK_TRACE=1 it also
  stores redacted stdin/stdout bodies.

Because it can wrap EVERY hook (incl. PreToolUse deny/allow), passthrough is verbatim and the
trace/sink is wrapped in try/except. Fail-open throughout — a broken sink OR sampler never breaks
or alters the wrapped hook's output or exit code.
"""
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    from _telemetry_gate import telemetry_enabled
except Exception:  # noqa: BLE001 - degrade to enabled if the helper is missing
    def telemetry_enabled(_="."):  # type: ignore
        return True

_MAX_BODY = 4096
_SECRET_RE = re.compile(
    r'(?i)(token|secret|password|api[_-]?key|authorization)("?\s*[:=]\s*"?)[^"\s,}]+'
)


def _redact(raw: bytes) -> str:
    s = raw.decode("utf-8", "replace")[:_MAX_BODY]
    return _SECRET_RE.sub(r"\1\2***", s)


def _derive_decision(exit_code: int, stdout: bytes) -> str:
    if exit_code == 2:
        return "deny"
    if exit_code == 0:
        s = stdout.decode("utf-8", "replace")
        if "decision" in s and "block" in s:
            return "block"
        if s.strip():
            return "inject"
        return "pass"
    if exit_code == 1:
        return "error"
    return "pass"


def _trace(child: list, stdin_bytes: bytes, proc, duration_ms: int) -> None:
    event = ""
    session_id = ""
    try:
        payload = json.loads(stdin_bytes.decode("utf-8", "replace") or "{}")
        if isinstance(payload, dict):
            event = payload.get("hook_event_name", "")
            session_id = payload.get("session_id", "")
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        pass

    row = {
        "ts": int(time.time()),  # epoch int — timezone/runtime-agnostic, matches the node twin
        "event": event,
        "hook": os.path.basename(child[0]) if child else "",
        "exit": proc.returncode,
        "decision": _derive_decision(proc.returncode, proc.stdout),
        "duration_ms": duration_ms,
        "session_id": session_id,
    }
    if os.environ.get("CLAUDE_HOOK_TRACE") == "1":
        row["stdin"] = _redact(stdin_bytes)
        row["stdout"] = _redact(proc.stdout)

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or "."
    if not telemetry_enabled(project_dir):
        return  # opt-out gate — an ADDITIONAL gate beyond _sampled(), not a sampling change
    out_dir = Path(project_dir) / ".claude" / "telemetry"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "hook-events.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _sample_rate() -> float:
    """CLAUDE_HOOK_TRACE_SAMPLE parsed defensively to [0,1]; any bad value → 0.0."""
    try:
        r = float(os.environ.get("CLAUDE_HOOK_TRACE_SAMPLE", ""))
    except (TypeError, ValueError):
        return 0.0
    if r != r:  # NaN
        return 0.0
    return 0.0 if r < 0 else 1.0 if r > 1 else r


def _sampled() -> bool:
    # Fail-open: if the sampler itself throws, treat as NOT sampled (the cheap fast path).
    try:
        return random.random() < _sample_rate()
    except Exception:  # noqa: BLE001
        return False


def _passthrough(child: list, do_trace: bool) -> None:
    """Run the hook as a child, re-emit its stdout/stderr byte-identical, exit with its code."""
    try:
        stdin_bytes = sys.stdin.buffer.read()
    except OSError:
        stdin_bytes = b""

    t0 = time.monotonic()
    proc = subprocess.run(child, input=stdin_bytes, capture_output=True)
    duration_ms = int((time.monotonic() - t0) * 1000)

    sys.stdout.buffer.write(proc.stdout)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(proc.stderr)
    sys.stderr.buffer.flush()

    if do_trace:
        # ANY trace/sink failure is swallowed so the child is still re-emitted verbatim.
        try:
            _trace(child, stdin_bytes, proc, duration_ms)
        except Exception:  # noqa: BLE001 - a broken sink must never break the wrapped hook
            pass

    sys.exit(proc.returncode)


def main():
    argv = sys.argv[1:]
    child = argv[argv.index("--") + 1:] if "--" in argv else argv
    if not child:
        sys.exit(0)

    if not _sampled():
        # FAST PATH — replace this process with the real hook: no capture, no trace, no double-spawn.
        try:
            os.execvp(child[0], child)  # never returns on success
        except OSError:
            pass  # exec failed — fall back to subprocess passthrough (fail-open, still no trace)
        _passthrough(child, do_trace=False)

    _passthrough(child, do_trace=True)


if __name__ == "__main__":
    main()

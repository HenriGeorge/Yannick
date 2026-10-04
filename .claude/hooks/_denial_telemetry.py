"""Shared denial-capture helper (issue #782) — imported by the deny-capable PreToolUse gate hooks.

A denied PreToolUse call aborts BEFORE tool_events.py logs anything, so the highest-friction events
(gate blocks + forced re-runs) are invisible to telemetry. This appends ONE metadata-only row to the
EXISTING #763 sink `.claude/telemetry/hook-events.jsonl` (schema-compatible with hook_trace) on each
deny — NOT a new sink, NOT the sampled hook_trace wrapper (which adds spawn overhead on the hot path
per #763/#764). Writing happens ONLY on the rare deny path → zero steady-state overhead.

Metadata only: the reason TEXT and command body are NEVER written — the reason is classified to a
stable `reason_class` label. `bypass_token` is a gate's canonical WORKFLOW/env sentinel (not a secret).
Fail-open: every write is wrapped so a broken sink can never affect the block decision or brick a hook.

Sibling import works because the plugin invokes hooks as `python3 .../hooks/<h>.py` (sys.path[0] is
the hooks dir); each importer guards the import so a missing module degrades to no-capture, never a crash.
"""
import json
import os
import time
from pathlib import Path

# Populated by set_context() from each hook's parsed stdin payload so the deny funnel (which usually
# lacks `data` in scope) can still attribute the row to a tool + session.
_CTX = {"tool": None, "session_id": None}

# reason_class classifier: ordered (substring, label), matched against the LOWERCASED reason. First
# match wins; unmatched → "guard-other". Most single-purpose gates are already identified by `hook`;
# this earns its keep for pre_tool_use's many sub-reasons. Harness worktree-isolation / auto-mode
# classifier denials fire pre-hook and are NOT capturable here (out of scope — #782 comment / #783).
_REASON_CLASSES = (
    ("bare alias", "model-alias"),
    ("rtk", "rtk-wrap"),
    ("worktree", "worktree-path"),
    ("secret", "secret-read"),
    ("rm -rf", "danger-rm"),
    ("read-only", "readonly-path"),
    ("readonly", "readonly-path"),
    ("reset --hard", "git-destructive"),
    ("force-push", "force-push"),
    ("grill findings", "grill-gate"),
    ("test change", "tdd-gate"),
    ("test-lock", "test-lock"),
    ("serialized per-repo", "test-lock"),
    ("parallelization", "parallel-gate"),
    ("interview", "plan-interview"),
    ("rebase", "stale-base"),
    ("nocommit", "nocommit"),
    ("do not commit", "nocommit"),
    ("design", "pr-design"),
    ("review", "pr-review"),
    ("security", "pr-security"),
)


def set_context(tool, session_id) -> None:
    _CTX["tool"] = tool or None
    _CTX["session_id"] = session_id or None


def classify_reason(reason: str) -> str:
    low = (reason or "").lower()
    for needle, label in _REASON_CLASSES:
        if needle in low:
            return label
    return "guard-other"


def emit_denial(hook: str, reason: str, bypass_token=None) -> None:
    """Append a metadata-only deny row to hook-events.jsonl. Best-effort — swallow every failure."""
    proj = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    try:
        from _telemetry_gate import telemetry_enabled
        if not telemetry_enabled(proj):
            return
    except Exception:  # noqa: BLE001 - degrade to enabled if the helper is missing
        pass
    try:
        row = {
            "ts": int(time.time()),
            "event": "PreToolUse",
            "hook": hook,
            "exit": 2,
            "decision": "deny",
            "tool": _CTX["tool"],
            "reason_class": classify_reason(reason),
            "bypass_token": bypass_token,
            "session_id": _CTX["session_id"],
        }
        out_dir = Path(proj) / ".claude" / "telemetry"
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / "hook-events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:  # noqa: BLE001 - best-effort; a broken sink must never affect the block
        pass

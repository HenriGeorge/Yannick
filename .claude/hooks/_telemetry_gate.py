#!/usr/bin/env python3
# dependencies = []
"""Shared opt-out gate for local telemetry writers (default ON — opt-OUT).

Resolution, first decisive wins: env CLAUDE_TELEMETRY (when set & non-empty) → worktrees.conf
TELEMETRY= → default enabled. Disabled only on an explicit falsy value (0/false/no/off); env
can re-enable over a conf disable. worktrees.conf is tracked, so it is present in the primary
AND every worktree — read it at <project_dir>/.claude/worktrees.conf.

Sibling import works because the plugin invokes hooks as `python3 .../hooks/<h>.py` (sys.path[0]
is the hooks dir); each importer guards the import so a missing module degrades to enabled.
Fail-open: any error → enabled (preserve today's behavior).
"""
import os
from pathlib import Path

_FALSY = ("0", "false", "no", "off")


def _is_disabled(val) -> bool:
    return str(val or "").strip().lower() in _FALSY


def _conf_telemetry(project_dir):
    try:
        path = Path(project_dir) / ".claude" / "worktrees.conf"
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("TELEMETRY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def telemetry_enabled(project_dir: str = ".") -> bool:
    try:
        env = os.environ.get("CLAUDE_TELEMETRY")
        if env is not None and env != "":
            return not _is_disabled(env)
        conf = _conf_telemetry(project_dir)
        if conf is not None:
            return not _is_disabled(conf)
    except Exception:  # noqa: BLE001 - fail-open to enabled
        return True
    return True

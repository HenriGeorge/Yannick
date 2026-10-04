"""Shared age-based GC for per-session hook state dirs (issue #554 generalized).

Several PostToolUse / UserPromptSubmit hooks write one file per session under
`.claude/state/<name>/` and never delete it, so the dir grows unbounded. This extracts
loop_detector's `_prune_stale` scandir+mtime+unlink pattern into ONE helper the un-pruned
state-writers (scope_creep, lesson_injector) call on a cheap probabilistic sweep.

FULLY fail-open: every OSError (and a missing dir) is swallowed — a broken GC must never affect a
hook's decision or crash it. The current session's own state file has mtime=now, so it is never the
one pruned.

Sibling import works because the plugin invokes hooks as `python3 .../hooks/<h>.py` (sys.path[0] is
the hooks dir); each importer guards the import so a missing module degrades to no-GC, never a crash.
"""
import os
from datetime import datetime


def prune_stale(state_dir, max_age_days=7, suffixes=(".json",)) -> None:
    """Unlink files directly under state_dir whose name ends with any of `suffixes` and whose mtime
    is older than max_age_days. Never recurses; never raises."""
    cutoff = datetime.now().timestamp() - max_age_days * 86400
    try:
        with os.scandir(state_dir) as it:
            for entry in it:
                if not entry.name.endswith(tuple(suffixes)):
                    continue
                try:
                    if entry.stat().st_mtime < cutoff:
                        os.unlink(entry.path)
                except OSError:
                    pass
    except OSError:
        pass


def gc_every(env_name, default=50) -> int:
    """Strict positive-int parse of a `1/N sweep` cadence knob (e.g. STATE_GC_EVERY). A non-numeric
    value (`"5x"`, `"abc"`) or absent/empty env falls back to `default`; a valid int is floored at 1.
    Shared so every GC caller rejects junk identically (py↔node twin parity — #797)."""
    raw = os.environ.get(env_name, "")
    try:
        return max(1, int(raw)) if raw.strip() else default
    except ValueError:
        return default

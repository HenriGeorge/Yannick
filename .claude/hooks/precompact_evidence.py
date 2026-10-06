#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""PreCompact hook — evidence snapshot for the Stop-time CLOSE gates (limitation #36).

Mid-session compaction rewrites the transcript, erasing the `gh pr merge` / `git commit` /
`/dev-reflect` / test-run / `gh issue create` events and bypass sentinels that the Stop gates scan
for at Stop — flipping their BLOCK/allow decisions. This hook fires BEFORE compaction (the last
moment the full transcript is readable), scans it via the shared `_lib.transcript` one-pass scanner
(hook consolidation PR 7 — the same scan stop_gate uses, so detection can no longer drift), and
persists the derived flags to a session-keyed snapshot:

    <cwd>/.claude/session-logs/compact-<session_id>.json

The Stop gate then OR this snapshot with its live transcript scan. Writes are merge-OR
(a later compaction's transcript has already lost the early events, so flags only ever
accumulate) and atomic (temp file + rename in the same directory). Snapshots older than 30
days are pruned (same policy as stop_log.py).

Never crashes: any exception, missing/unreadable transcript, or unwritable directory
silently exits 0 — the gates then degrade to exactly today's live-scan-only behavior.
"""

import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))  # -P / PYTHONSAFEPATH drops the script dir (PR 5 C2)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _lib.notice import fail_open_notice  # noqa: E402 — needs _HERE on sys.path first

# The 8 snapshot flag names, in lockstep with _lib.transcript.snapshot_flags.
FLAG_NAMES = (
    "made_commit", "did_merge", "ran_reflect", "ran_test",
    "filed_issue", "declared_none", "no_reflect", "no_verify",
)


def _sanitize(session_id):
    return re.sub(r"[^A-Za-z0-9._-]", "_", session_id)


def _prune_old(log_dir, keep_days=30):
    try:
        now = datetime.now(tz=timezone.utc).timestamp()
        for name in os.listdir(log_dir):
            if not (name.startswith("compact-") and name.endswith(".json")):
                continue
            p = os.path.join(log_dir, name)
            try:
                if now - os.path.getmtime(p) > keep_days * 86400:
                    os.unlink(p)
            except OSError:
                continue
    except OSError:
        pass


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    transcript_path = data.get("transcript_path")
    session_id = data.get("session_id")
    if not transcript_path or not isinstance(transcript_path, str):
        sys.exit(0)
    if not session_id or not isinstance(session_id, str):
        sys.exit(0)
    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else ""

    try:
        from _lib.test_cmd import _find_conf, _test_cmd
        from _lib.transcript import last_suite, parse_ts as _parse_ts, scan, snapshot_flags
        # Scan WITH test_cmd so "suite" means the SAME thing stop_gate judges (R1 HIGH-4).
        conf = _find_conf(cwd)
        s = scan(transcript_path, _test_cmd(conf) if conf else None)
    except Exception as e:  # noqa: BLE001 — never block compaction; make the fail-open VISIBLE (R2 MEDIUM-6)
        fail_open_notice(f"precompact_evidence: scan skipped ({e}) — the Stop gates "
                         "will fall back to their live transcript scan this session.")
        sys.exit(0)
    flags, first_ts, ls = snapshot_flags(s), s.first_ts, last_suite(s)

    log_dir = os.path.join(cwd or os.getcwd(), ".claude", "session-logs")
    snap_path = os.path.join(log_dir, f"compact-{_sanitize(session_id)}.json")

    # merge-OR with any existing snapshot — flags only ever accumulate; first_ts keeps the minimum
    prev_first_ts = None
    try:
        with open(snap_path, "r", encoding="utf-8") as f:
            prev = json.load(f)
        prev_flags = prev.get("flags") if isinstance(prev, dict) else None
        if isinstance(prev_flags, dict):
            for name in FLAG_NAMES:
                if prev_flags.get(name) is True:
                    flags[name] = True
        if isinstance(prev, dict):
            prev_first_ts = _parse_ts(prev.get("first_ts"))
            # keep the earlier scan's last_suite when THIS (post-compaction) scan lost it (R1 HIGH-4)
            if ls is None and isinstance(prev.get("last_suite"), dict):
                ls = prev.get("last_suite")
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    if prev_first_ts is not None and (first_ts is None or prev_first_ts < first_ts):
        first_ts = prev_first_ts

    snapshot = {
        "session_id": session_id,
        "updated": datetime.now(tz=timezone.utc).isoformat(),
        "flags": flags,
        "first_ts": first_ts.isoformat() if first_ts is not None else None,
        "last_suite": ls,
    }

    os.makedirs(log_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".compact-", suffix=".tmp", dir=log_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(snapshot, f)
        os.replace(tmp_path, snap_path)  # atomic within the same directory
    except OSError as e:
        fail_open_notice(f"precompact_evidence: snapshot write failed ({e}) — the "
                         "Stop gates degrade to their live transcript scan this session.")
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    _prune_old(log_dir)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - never brick a compaction
        sys.exit(0)

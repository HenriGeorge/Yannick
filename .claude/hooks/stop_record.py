#!/usr/bin/env python3
# dependencies = []
"""Stop `stop_record` — ONE process for the Stop-time recorders (hook consolidation PR 4).

Modules, in the retired hooks' wiring order:
  stop_log             — session summary row to .claude/session-logs/<date>.jsonl (30-day retention)
  cost_telemetry       — per-session token/cost row to .claude/telemetry/costs.jsonl (deduped by
                         message.id, #501)
  improvement_proposer — after a dev-reflect, stub ONE proposal for a recurring lesson signal

Empty stdin still runs every module with {} (the retired hooks parsed `stdin or "{}"`), so the stop
is logged; non-JSON stdin runs nothing, as before. Never blocks the stop. Every module keeps its sink, format and breadcrumb byte for byte (golden:
tests/test_hook_golden.sh). The retired <name>.py files forward here with main(only=<name>).
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from _dispatch import dispatch

try:
    from _telemetry_gate import telemetry_enabled
except Exception:  # noqa: BLE001 - degrade to enabled if the helper is missing
    def telemetry_enabled(_="."):  # type: ignore
        return True


# ---- stop_log -------------------------------------------------------------------------------------
def _stop_log(data):
    session_id = data.get("session_id", "unknown")
    stop_reason = data.get("stop_reason", "unknown")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_entry = {
        "timestamp": timestamp,
        "session_id": session_id,
        "stop_reason": stop_reason,
    }
    date_str = datetime.now().strftime("%Y-%m-%d")

    try:
        # Root at the project dir, not the CWD — a session whose cwd is elsewhere (e.g. inside a
        # docs/ subfolder) must not drop a stray .claude/session-logs/ there. Mirrors the Node twin.
        proj = os.environ.get("CLAUDE_PROJECT_DIR", ".")
        log_dir = Path(proj) / ".claude" / "session-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{date_str}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
        # Keep only last 30 days
        logs = sorted(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        for old in logs[:-30]:
            old.unlink()
    except OSError as e:
        # best-effort logging (never crash the Stop hook) — but leave a breadcrumb so a missing
        # log trail is diagnosable rather than silent.
        print(f"stop_log: could not write session log: {e}", file=sys.stderr)
    return None


# ---- cost_telemetry -------------------------------------------------------------------------------
CT_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def _ct_sum_transcript(transcript_path: str) -> dict:
    """Return deduped-by-message.id token totals from a transcript JSONL, or {} on any failure."""
    per_id: dict = {}
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
                msg = rec.get("message") or {}
                usage = msg.get("usage")
                mid = msg.get("id")
                if not isinstance(usage, dict) or not mid:
                    continue
                # last usage wins per message.id — blocks of one turn repeat identical usage.
                per_id[mid] = usage
    except OSError:
        return {}
    totals = {k: 0 for k in CT_USAGE_FIELDS}
    for usage in per_id.values():
        for k in CT_USAGE_FIELDS:
            v = usage.get(k, 0)
            if isinstance(v, int):
                totals[k] += v
    totals["messages"] = len(per_id)
    totals["total_tokens"] = sum(totals[k] for k in CT_USAGE_FIELDS)
    return totals


def _cost_telemetry(data):
    try:
        row = {
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "session_id": data.get("session_id", "unknown"),
        }
        transcript_path = data.get("transcript_path", "")
        if transcript_path and Path(transcript_path).is_file():
            row.update(_ct_sum_transcript(transcript_path))
        cost = data.get("cost") or {}
        if isinstance(cost, dict) and isinstance(cost.get("total_cost_usd"), (int, float)):
            row["cost_usd"] = cost["total_cost_usd"]
        # nothing measurable -> don't write a hollow row
        if "total_tokens" not in row and "cost_usd" not in row:
            return None

        project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        if not telemetry_enabled(project_dir):
            return None
        out_dir = Path(project_dir) / ".claude" / "telemetry"
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / "costs.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError as e:
        # best-effort telemetry — never brick the Stop hook, but leave a breadcrumb.
        print(f"cost_telemetry: could not write telemetry: {e}", file=sys.stderr)
    except Exception:  # noqa: BLE001 - never brick a session
        return None
    return None


# ---- improvement_proposer -------------------------------------------------------------------------
IP_N = 3
IP_ISSUE_RE = re.compile(r"#(\d{2,6})\b")
IP_SEEN_RE = re.compile(r"\*\*Seen\*\*:\s*(\d+)x", re.IGNORECASE)
IP_LESSON_START_RE = re.compile(r"^### ", re.MULTILINE)


def _ip_slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "signal"


def _ip_blocks(md):
    """-> list of (title, block_text) for each `### ` lesson block (title = heading minus `### `)."""
    out = []
    parts = IP_LESSON_START_RE.split(md)
    for chunk in parts[1:]:  # parts[0] is any preamble before the first `### `
        title = chunk.splitlines()[0].strip() if chunk.strip() else ""
        out.append((title, chunk))
    return out


def _ip_reflect_happened(proj):
    if os.environ.get("IMPROVE_FORCE_REFLECT"):
        return True
    # a docs(lessons): commit among this session's HEAD commits
    try:
        out = subprocess.run(["git", "-C", proj, "log", "--since=6 hours ago", "--pretty=%s"],
                             capture_output=True, text=True, timeout=5)
        return "docs(lessons)" in out.stdout
    except Exception:  # noqa: BLE001
        return False


def _improvement_proposer(data):
    try:
        proj = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        if not _ip_reflect_happened(proj):
            return None
        lessons = os.environ.get("LESSONS_PATH") or os.path.join(proj, "docs", "lessons.md")
        try:
            with open(lessons, encoding="utf-8", errors="replace") as fh:
                md = fh.read()
        except OSError:
            return None
        # count signals per block: distinct blocks citing an #issue + a **Seen**: Nx counter (N>=N)
        counts = {}
        for title, block in _ip_blocks(md):
            for num in set(IP_ISSUE_RE.findall(block)):  # a block counts once per issue it cites
                counts[f"#{num}"] = counts.get(f"#{num}", 0) + 1
            sm = IP_SEEN_RE.search(block)
            if sm and title:
                seen = int(sm.group(1))
                if seen >= IP_N:  # a Seen:Nx block is itself a recurring signal (signal = its title)
                    counts[title] = max(counts.get(title, 0), seen)
        # pick the highest-count signal >= N
        cand = [(c, sig) for sig, c in counts.items() if c >= IP_N]
        if not cand:
            return None
        cand.sort(reverse=True)
        count, sig = cand[0]
        outdir = os.path.join(proj, ".claude", "improvements")
        os.makedirs(outdir, exist_ok=True)
        path = os.path.join(outdir, _ip_slug(sig) + ".md")
        # idempotence: skip if draft exists and recorded-count >= count
        if os.path.exists(path):
            try:
                prev = open(path, encoding="utf-8").read()
                pm = re.search(r"recorded-count:\s*(\d+)", prev)
                if pm and int(pm.group(1)) >= count:
                    return None
            except OSError:
                pass
        conf = "High" if count >= 5 else "Med" if count >= 3 else "Low"
        body = (f"# Improvement proposal: {sig}\n\n"
                f"- observed: {sig} recurs {count}x in docs/lessons.md\n"
                f"- evidence: see the lesson blocks mentioning {sig}\n"
                f"- proposed change: TODO (human/agent) — promote to rule / hook / lint / test?\n"
                f"- confidence: {conf}\n"
                f"- recorded-count: {count}\n")
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
            sys.stderr.write(f"[improvement_proposer] drafted {path} ({sig} x{count})\n")
        except OSError:
            pass
    except Exception:  # noqa: BLE001 - never block the stop
        sys.stderr.write("[improvement_proposer] skipped (internal error)\n")
    return None


MODULES = (
    ("stop_log", _stop_log),
    ("cost_telemetry", _cost_telemetry),
    ("improvement_proposer", _improvement_proposer),
)


def main(only=None) -> int:
    # empty_ok: the retired Stop hooks parsed `stdin or "{}"`, so an empty payload still logged the stop.
    return dispatch("stop_record", MODULES, only, empty_ok=True)


if __name__ == "__main__":
    sys.exit(main())

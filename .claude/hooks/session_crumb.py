#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Write the re-grounding crumb before context is lost — on PreCompact AND SessionEnd(clear|normal).

Single responsibility: the crumb (branch · staged · last test · open questions). Guarded ONLY by
cwd — never behind the evidence-snapshot's session_id/transcript preconditions (the coupling bug
that made the old precompact-owned crumb silently skip). session_resume reads it on the next start.
Fail-open: any error → exit 0, silent. Never breaks a /clear or /compact.
"""
import json
import os
import re
import subprocess  # noqa: S404 - fixed argv git calls, shell=False
import sys
import tempfile
from datetime import datetime, timezone

# Re-grounding crumb (#504) — written for the SessionStart session_resume hook (#512) to read.
# Path MUST stay byte-identical to session_resume's default (SESSION_CRUMB_PATH override there).
CRUMB_REL = os.path.join(".claude", "state", "session_resume", "crumb.md")
CRUMB_LAST_TEST_MAX = 200  # chars — a command line, not a log

TEST_RUNNER_RE = re.compile(
    r"\b(pytest|npm\s+test|vitest|cargo\s+test|go\s+test|bash\s+tests/run\.sh|"
    r"npm\s+run\s+lint|ruff\s+check)\b"
)

NORMAL_END = {"clear", "other"}  # SessionEnd reasons we write a crumb for


def _git(root, args):
    """Run `git <args>` in root, return stripped stdout or "" (fail-silent — crumb is best-effort)."""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, shell=False, operator-controlled
            ["git", "-C", root, *args],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def last_test_from_transcript(path):
    """Return the last Bash command matching TEST_RUNNER_RE in the transcript, or None."""
    last_test = None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(event, dict) or event.get("type") != "assistant":
                continue
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if (isinstance(block, dict)
                        and block.get("type") == "tool_use"
                        and block.get("name") == "Bash"):
                    command = (block.get("input") or {}).get("command", "")
                    if isinstance(command, str) and TEST_RUNNER_RE.search(command):
                        last_test = command.strip()[:CRUMB_LAST_TEST_MAX]
    return last_test


def write_crumb(root, last_test):
    """Write a re-grounding crumb (branch · staged · last test · open questions) for #512 to read.

    Best-effort: any failure is swallowed by the caller. Overwrites atomically (temp + rename).
    """
    branch = _git(root, ["rev-parse", "--abbrev-ref", "HEAD"]) or "(unknown)"
    staged = _git(root, ["diff", "--cached", "--name-only"])
    staged_files = [ln for ln in staged.splitlines() if ln.strip()]

    lines = ["# Session crumb",
             f"Updated: {datetime.now(tz=timezone.utc).isoformat()}",
             f"Branch: {branch}"]
    if staged_files:
        shown = ", ".join(staged_files[:8]) + ("…" if len(staged_files) > 8 else "")
        lines.append(f"Staged: {len(staged_files)} file(s) — {shown}")
    else:
        lines.append("Staged: none")
    lines.append(f"Last test: {last_test or '(none observed this session)'}")

    # Open questions: surface the park sentinel if the session left one.
    needs_human = os.path.join(root, ".claude", "NEEDS-HUMAN.md")
    try:
        with open(needs_human, encoding="utf-8", errors="replace") as fh:
            nh = fh.read().strip()
        if nh:
            lines.append("\nOpen questions (.claude/NEEDS-HUMAN.md):\n" + nh)
    except OSError:
        pass

    crumb_path = os.path.join(root, CRUMB_REL)
    os.makedirs(os.path.dirname(crumb_path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".crumb-", suffix=".tmp", dir=os.path.dirname(crumb_path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.replace(tmp, crumb_path)  # atomic within the same directory
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    if not isinstance(data, dict):
        sys.exit(0)
    reason = data.get("reason")
    if reason is not None and reason not in NORMAL_END:   # SessionEnd we don't act on
        sys.exit(0)
    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else ""
    tp = data.get("transcript_path")
    last_test = None
    if isinstance(tp, str) and tp:
        try:
            last_test = last_test_from_transcript(tp)
        except Exception:  # noqa: BLE001
            last_test = None
    try:
        write_crumb(cwd or os.getcwd(), last_test)
    except Exception:  # noqa: BLE001
        pass
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        sys.exit(0)

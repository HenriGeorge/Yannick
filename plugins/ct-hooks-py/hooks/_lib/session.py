# dependencies = []
"""Session-role detection for SessionStart hooks (spec 2026-10-14-figma-launch-coordinator-only).

A teammate/subagent is a full `claude` process spawned with `--parent-session-id`; the harness
marks it with CLAUDE_CODE_CHILD_SESSION=1 and, for pane teammates, a tmux socket named
claude-swarm-<pid>. Side-effecting startup hooks (launch Figma, rewrite rules) must act only in the
coordinator. Pure env reads; every marker absent → coordinator, attended (today's behaviour)."""
import os


def is_child_session() -> bool:
    if os.environ.get("CLAUDE_CODE_CHILD_SESSION", "") == "1":
        return True
    return "claude-swarm" in os.environ.get("TMUX", "")


def is_unattended() -> bool:
    return os.environ.get("CLAUDE_CODE_SESSION_ATTENDED", "") == "0"

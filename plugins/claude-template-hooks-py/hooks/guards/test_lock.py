"""Test-lock guard: the per-repo suite must run under bin/test-lock. BOTH of today's checks, one
module (hook consolidation PR 5), each with its OWN wrapper-allow evaluated FIRST:
  check_runner   — old pre_tool_use H1: generic runner regex; CT_ALLOW_UNLOCKED_TESTS (process env
                   or a leading assignment of the matching segment).
  check_test_cmd — old test_lock_enforce: the project's .claude/worktrees.conf TEST_CMD.
pre_tool_use calls check_runner, test_lock_enforce calls check_test_cmd — no wiring change until
PR 6 runs both from pre_tool."""
import re

from _lib.shell import SHELL_SEGMENT_SPLIT_RE, _process_env_override, _segment_has_leading_override
from _lib.test_cmd import _find_conf, _strip_prefix, _test_cmd, is_runner_segment, runs_test_cmd

_HEAD_WRAPPERS = ("bin/test-lock", "test-lock", "./bin/test-lock")


def check_runner(ctx):
    command = ctx.command
    if not command.strip():
        return None
    if _process_env_override("CT_ALLOW_UNLOCKED_TESTS"):
        return None
    # #940: the wrapper must be the segment HEAD, not appear ANYWHERE in the command — a trailing
    # `test-lock` token (`npm test; echo test-lock`) must not disarm the deny. A test-lock-wrapped
    # run leads its segment with the wrapper, so is_runner_segment (head-anchored) is already False
    # for it; no whole-command wrapper allow is needed (and a global one was the bug).
    for segment in SHELL_SEGMENT_SPLIT_RE.split(command):
        if is_runner_segment(segment):
            # MED fix: the override must lead THIS segment, not any segment of the command.
            if _segment_has_leading_override(segment, "CT_ALLOW_UNLOCKED_TESTS"):
                continue
            return ("Blocked: bare test-runner invocation. Re-run via "
                    "`bin/test-lock -- <cmd>` to hold the per-repo test lock, or set "
                    "CT_ALLOW_UNLOCKED_TESTS=1 to override.")
    return None


def check_test_cmd(ctx):
    cmd = ctx.command.strip()
    if cmd.startswith("rtk "):
        cmd = cmd[4:].lstrip()
    head = cmd.split("&&")[0].split(";")[0].strip()
    if head.startswith(_HEAD_WRAPPERS):  # allow-wrapped BEFORE any deny (grill G4)
        return None
    conf = _find_conf(ctx.cwd)
    if not conf:
        return None
    test_cmd = _test_cmd(conf)
    if not test_cmd or not runs_test_cmd(cmd, test_cmd):
        return None
    # One override for both test-lock checks (hook consolidation PR 6, Q3): process env, or a leading
    # assignment on THE segment that runs TEST_CMD (same rule as check_runner).
    if _process_env_override("CT_ALLOW_UNLOCKED_TESTS"):
        return None
    runner0 = test_cmd.split()[0]
    if all(_segment_has_leading_override(seg, "CT_ALLOW_UNLOCKED_TESTS")
           for seg in re.split(r"[&;\n|()]", cmd)
           if _strip_prefix(seg.strip(), runner0).startswith(test_cmd)):
        return None
    return (f"Suite runs are serialized per-repo: run it as `bin/test-lock -- {test_cmd}` "
            "(the lock spans all worktrees of this repo; a contended run prints the holder).")

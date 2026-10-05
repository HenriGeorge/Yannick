"""What counts as a test-suite run — ONE definition (hook consolidation PR 5). Used by guards/test_lock
today; PR 7's stop_gate tests-passed check reuses it."""

import os
import re

from _lib.shell import SHELL_SEGMENT_SPLIT_RE, _strip_leading_tokens


TEST_LOCK_RE = re.compile(
    r"^(npm\s+run\s+test\b|npm\s+test\b|pytest\b|go\s+test\b|cargo\s+test\b|vitest\b|jest\b)"
)


_WRAPPERS = ("time", "env", "nice", "sudo")


def _strip_prefix(seg: str, runner0: str) -> str:
    """Strip leading `VAR=val` env-assignments and wrapper words (time/env/nice/sudo) — plus a
    wrapper's own flags and flag-arguments (`nice -n 10`, `sudo -u ci`) — so a wrapped raw run
    still exposes the runner. `runner0` (the runner's first token, e.g. `bash`) bounds the strip:
    we stop the moment we reach it, so a flag-value skip can never swallow the runner (#570, #667)."""
    toks = seg.split()
    i = 0
    saw_wrapper = False
    while i < len(toks):
        t = toks[i]
        if t == runner0:
            break
        if t in _WRAPPERS:
            saw_wrapper = True
            i += 1
        elif "=" in t and t.split("=", 1)[0].isidentifier():
            i += 1
        elif saw_wrapper and t.startswith("-"):
            i += 1
            # a wrapper flag may take a value (`-u ci`, `-n 10`) — skip it too, unless it's the
            # runner or the next flag.
            if i < len(toks) and toks[i] != runner0 and not toks[i].startswith("-"):
                i += 1
        else:
            break
    return " ".join(toks[i:])


def _find_conf(start: str) -> str | None:
    """Walk up from `start` to the first .claude/worktrees.conf (the repo marker)."""
    d = os.path.abspath(start or os.getcwd())
    while True:
        p = os.path.join(d, ".claude", "worktrees.conf")
        if os.path.isfile(p):
            return p
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _test_cmd(conf_path: str) -> str | None:
    try:
        with open(conf_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("TEST_CMD="):
                    val = line.split("=", 1)[1].strip()
                    # Parse like bash sources it: a quoted value ends at its close quote (any
                    # trailing ` # comment` is ignored); an unquoted value is cut at the first `#`.
                    # Every other worktrees.conf key carries an inline comment, so TEST_CMD may too.
                    if val[:1] in ('"', "'"):
                        q = val[0]
                        end = val.find(q, 1)
                        val = val[1:end] if end != -1 else val[1:]
                    else:
                        val = val.split("#", 1)[0].strip()
                    return val or None
    except OSError:
        return None
    return None


def is_runner_segment(segment):
    """True if `segment` LEADS with a generic test runner (old pre_tool_use H1)."""
    return bool(TEST_LOCK_RE.match(_strip_leading_tokens(segment.strip()).strip()))


def runs_test_cmd(cmd, test_cmd):
    """True if `test_cmd` LEADS any segment of `cmd` (issue #570/#667: split on &;\\n|() and strip
    env/wrapper prefixes; a mere mention in prose is not a run)."""
    runner0 = test_cmd.split()[0]
    return any(_strip_prefix(seg.strip(), runner0).startswith(test_cmd)
               for seg in re.split(r"[&;\n|()]", cmd))


# A suite run as stop_gate sees it: bare OR wrapped. The guard asks "is this an UNWRAPPED run?" (so
# it allows the wrapper first); stop_gate asks "did the suite run?" — same definition, wrapper and a
# leading `rtk ` stripped first (hook consolidation PR 7).
_LOCK_WRAPPER_RE = re.compile(r"^(?:\S*/)?test-lock\s+--\s+")
_RUNNER_HINT_RE = re.compile(r"npm|pnpm|yarn|pytest|go\s+test|cargo|vitest|jest|python|uv\s+run|bash\s+tests/run\.sh")
# Launchers that front a runner: `uv run pytest`, `python -m pytest`. Peeled before the runner check.
_SUITE_LAUNCHER_RE = re.compile(r"^(?:uv\s+run\s+|python3?\s+-m\s+)")
# Suite forms the generic runner regex (TEST_LOCK_RE, kept in lockstep with the test-lock guard)
# doesn't lead with: pnpm/yarn test, and `bash tests/run.sh` even when TEST_CMD is unset. (PR 7 HIGH-6)
_SUITE_EXTRA_RE = re.compile(r"^(?:pnpm|yarn)\s+(?:run\s+)?test\b|^bash\s+tests/run\.sh\b")


def is_suite_run(cmd, test_cmd):
    if not (_RUNNER_HINT_RE.search(cmd) or (test_cmd and test_cmd in cmd)):
        return False  # cheap prefilter: most commands (heredocs, greps) never reach the split
    for seg in SHELL_SEGMENT_SPLIT_RE.split(cmd):
        s = seg.strip()
        if s.startswith("rtk "):
            s = s[4:].lstrip()
        s = _LOCK_WRAPPER_RE.sub("", s, count=1)
        peeled = _SUITE_LAUNCHER_RE.sub("", s, count=1)  # `uv run pytest` / `python -m pytest`
        if (is_runner_segment(s) or is_runner_segment(peeled) or _SUITE_EXTRA_RE.match(s)
                or (test_cmd and runs_test_cmd(s, test_cmd))):
            return True
    return False

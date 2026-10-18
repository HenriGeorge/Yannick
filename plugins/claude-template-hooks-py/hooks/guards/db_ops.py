"""Block destructive DB operations unless that command itself dry-runs (hook consolidation PR 5)."""
import re

from _lib.shell import SHELL_SEGMENT_SPLIT_RE

DANGEROUS_DB_OPS = [
    "DROP TABLE", "DROP DATABASE", "TRUNCATE",
    "ALTER TABLE", "DROP INDEX",
]


def check(ctx):
    # Block destructive DB operations — match on WORD BOUNDARIES (prose "trunca-TED"/"ALTERed"
    # no longer trips; every executed op still matches) after scrubbing quoted strings inside a
    # `git commit …` segment ONLY (a commit message cannot execute; the scrub stops at the first
    # ;|&| separator so `git commit -m "x" && psql -c "DROP TABLE y"` still trips). Deliberately
    # NO heredoc stripping: heredocs are an execution path (`psql <<SQL`) — a live probe showed
    # stripping them lets a real prod DROP through (ADR 0008: never narrow toward false
    # negatives; the workaround for citing SQL in prose is the Edit/Write tool, not Bash).
    scrubbed = re.sub(
        r"\bgit\s+commit\b[^\n;&|]*",
        lambda m: re.sub(r"(['\"]).*?\1", " ", m.group(0)),
        ctx.command,
    )
    # #320/#330/#331 — the `--dry-run` exemption is PER-COMMAND and DECOUPLED from op-matching.
    # Whole-command scanning let a `--dry-run` anywhere exempt everything (#320). Split into shell
    # commands (INCLUDING `\n`), DROP any command that itself dry-runs, then match the op against
    # the remaining commands rejoined with `\n`. This (a) keeps a real op split across `\n` inside
    # ONE kept command matchable (`DROP\nTABLE` in a heredoc, #330), (b) stops a `--dry-run` on
    # one command bleeding across a newline to exempt a real op on the next (#331), and (c) strips
    # shell comments (`# --dry-run`) before the dry-run check so a trailing comment can't bypass
    # the guard (#331-trailing). Rejoin can only over-block (the safe direction), never under-block.
    # (Byte-parity with the JS twin.)
    _kept_cmds = "\n".join(
        s
        for s in SHELL_SEGMENT_SPLIT_RE.split(scrubbed)
        if "--dry-run" not in re.sub(r"\s+#[^\n]*", "", s)
    )
    for pattern in DANGEROUS_DB_OPS:
        if re.search(r"\b" + pattern.replace(" ", r"\s+") + r"\b", _kept_cmds, re.IGNORECASE):
            return (f"Blocked: destructive DB operation '{pattern}' — use --dry-run first.")
    return None

"""H2 — conventional-commit grammar for every inline `git commit -m` (hook consolidation PR 5)."""

import re

from _lib.git import GIT_COMMIT_INVOCATION_RE
from _lib.shell import _bare_shell_mask


# H2 — conventional-commit: permissive `type(scope)!: subject` grammar for an inline `git commit -m`.
# Types are matched case-sensitively lowercase-only per the conventional-commits spec (so "Feat: x"
# is denied, not silently normalized).
CONVENTIONAL_COMMIT_RE = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([^)]*\))?!?:\s+\S.*$"
)


# Merge-commit default messages are exempt — git generates these, not the agent, and they don't
# follow (nor should be forced into) conventional-commit grammar.
MERGE_COMMIT_MSG_RE = re.compile(r"^Merge (branch|remote-tracking branch|pull request)\b")


# #230 — flag grammar shared by all three message-source regexes below. The pre-#230 patterns
# required a separator (`=` or whitespace) after a BARE `-m`, which silently missed the two most
# common real-world spellings and turned this BLOCK gate into a no-op for them:
#   * attached value  — `-m"subject"` (the shell strips the quotes; git sees -m with that value)
#   * bundled shorts  — `-am "subject"` / `-vam …` (git allows short flags to cluster, the last
#                       one taking the value; `-am` is arguably the single most common form)
# So the short form is `-[A-Za-z]*m` (m as the value-taking tail of a cluster) with the separator
# OPTIONAL, while the long form keeps requiring `=`/whitespace. `--message`/`--amend` can't collide
# with the short arm: after the leading `-` the next char is `-`, which `[A-Za-z]*` cannot match.
#
# The greedy `[A-Za-z]*` backtracks, so `-msg` still resolves to -m with value "sg" (git's own
# reading). A hypothetical `-format`-style flag would mis-read as -m + "at", but git commit has no
# such flag and, per ADR 0008, a false POSITIVE is the safe direction for a guard — never narrow
# toward false negatives to buy tidiness.
_MSG_FLAG = r"(?:--message(?:=|\s+)|-[A-Za-z]*m(?:=|\s*))"


_FILE_FLAG = r"(?:--file(?:=|\s+)|-[A-Za-z]*F(?:=|\s*))"


# Quoting follows POSIX shell, and the two quote styles differ — matching them the same way was a
# real bypass. Inside DOUBLE quotes the shell does process `\`, so `\"` keeps the string open.
# Inside SINGLE quotes it processes nothing: the string ends at the very next `'`, full stop.
# Treating `\'` as an escaped quote ran the match PAST the real terminator and swallowed whatever
# followed — including a chained second invocation, which was then skipped as already-consumed and
# never graded. So: `\\.` on the double arm only, a flat `[^']*` on the single arm.
_QUOTED_OR_BARE = r'("(?:[^"\\]|\\.)*"|\'[^\']*\'|\S+)'


COMMIT_M_FLAG_RE = re.compile(r"(?:^|\s)" + _MSG_FLAG + _QUOTED_OR_BARE)


COMMIT_F_FLAG_RE = re.compile(r"(?:^|\s)" + _FILE_FLAG + r"\S+")


# #190 (upstreamed from the ableton fork after the un-fork lost it): `git commit -m "$(cat <<'EOF'
# ... EOF)"` is shell command substitution wrapping a heredoc — COMMIT_M_FLAG_RE's quoted-string
# alternative terminates at the first embedded straight quote in the BODY, garbling the "message".
# A heredoc is effectively file-shaped (like -F) — recognize the shape explicitly and pull the
# SUBJECT from just the heredoc's own first content line. Tolerates `<<`/`<<-`, quoted/bare delimiter.
#
# The body ends at the first DELIMITER LINE, which is all POSIX requires — it does NOT have to be
# followed by the substitution close `)"`. Demanding `)"` made the match skip the real terminator
# and run on to a later one, and that over-read span then swallowed a chained second invocation,
# which the consumed-span skip dropped unchecked. Unlike the quoted arms (which only ever
# under-extend, a safe over-block), this one carried a VALID subject, so the first commit passed
# and the second vanished — a genuine MISS. `[ \t]*` rather than `\s*` around the delimiter because
# a delimiter line's indentation (`<<-` uses tabs) never spans newlines.
HEREDOC_M_FLAG_RE = re.compile(
    r"(?:^|\s)" + _MSG_FLAG + r"\"\$\(\s*cat\s+<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1\s*\r?\n"
    r"([\s\S]*?)\r?\n[ \t]*\2[ \t]*(?:\r?\n|$)"
)


def _first_commit_source(tail: str):
    """First message source in `tail`, as (subject_or_None, end_offset), or None if there is none.

    `tail` runs to the END of the command and is never truncated — truncating it is what broke the
    first attempt at #230, since a scope boundary landing inside a quoted message cut that message
    in half and the guard then judged a fragment.

    #230: all three message sources are resolved by POSITION, because that is exactly how git
    picks the subject — the FIRST message-bearing flag wins, and later ones only append further
    paragraphs. Ordering is what makes the three cases fall out of one rule instead of three:
      * `-m "bad" -F real.txt`  → -m is first, so git's subject is "bad"  → CHECK it
      * `-F real.txt -m "bad"`  → the file is first, subject comes from it → EXEMPT
      * `-m "bad --file=x"`     → the `--file=` sits INSIDE -m's own quoted value, so it can only
                                  match LATER than the -m → CHECK, no quote-awareness needed
    That last one is the pre-#230 `-F`-anywhere bypass: the old code early-returned on a `--file`
    found anywhere in the command, including one that was merely part of a commit message.

    A `file` source returns subject None (exempt, nothing to grade) but still reports its end
    offset, because the caller needs the span either way — see _check_conventional_commit.
    """
    heredoc = HEREDOC_M_FLAG_RE.search(tail)
    plain = COMMIT_M_FLAG_RE.search(tail)
    file_src = COMMIT_F_FLAG_RE.search(tail)
    # (position, rank, match) — rank breaks a tie at the SAME position, where the heredoc and plain
    # forms both anchor on the identical `-m`; the heredoc parse is the accurate one, so it wins.
    cands = [
        (m.start(), rank, kind, m)
        for m, rank, kind in ((heredoc, 0, "heredoc"), (plain, 1, "plain"), (file_src, 1, "file"))
        if m is not None
    ]
    if not cands:
        return None  # no inline -m → interactive/editor commit, don't block
    _, _, kind, m = min(cands, key=lambda c: (c[0], c[1]))
    if kind == "file":
        return (None, m.end())  # -F/--file supplies the subject — exempt, same as before #230
    if kind == "heredoc":
        # See #190: the grammar check only needs the SUBJECT (first line) anyway — take it
        # straight from the heredoc body rather than regex-parsing the whole substitution.
        return (m.group(3).split("\n")[0], m.end())
    msg = m.group(1)
    if len(msg) >= 2 and msg[0] in "\"'" and msg[-1] == msg[0]:
        msg = msg[1:-1]
    return (msg, m.end())


def _check_conventional_commit(command: str):
    # #230: check EVERY `git commit` in the command, not just the first — `git commit -m "chore: ok"
    # && git commit -m "bad"` used to validate only the leading one. Each match owns the span up to
    # the next one, so a flag can't be read as belonging to a different invocation.
    #
    # Deliberately NOT split on shell operators (SHELL_SEGMENT_SPLIT_RE, as the sibling guards do):
    # that splits on `;` and `|` too, which would tear apart a heredoc body containing either and
    # break the #190 parse.
    #
    # Two earlier attempts each failed in one direction, which is what this shape is built around:
    #   1. Slice at every textual match, scope ends at the next match — a match INSIDE a quoted
    #      message cut that message in half, so a VALID subject was judged as a fragment (`'"docs:'`).
    #   2. Only treat command-position matches as boundaries — `then`/`do`/`{` put a real second
    #      invocation at an unrecognized position, so its bad message went UNCHECKED. Enumerating
    #      shell keywords is unbounded; the next one not on the list reopens the same hole.
    #
    # So: keep the BROAD match list (it never misses a real invocation), never truncate the tail
    # (nothing can cut a message in half), and drop a boundary that turns out to sit INSIDE the
    # message a previous invocation already consumed — which is precisely what a phrase quoted in a
    # commit message is. The span does the disambiguation that shell-grammar guessing could not, and
    # it needs no list of keywords to stay correct.
    consumed_end = -1
    bare = _bare_shell_mask(command)  # #482: skip a `git commit` merely quoted / heredoc-embedded
    for start in [m.start() for m in GIT_COMMIT_INVOCATION_RE.finditer(command)]:
        if not bare[start]:
            continue  # inside a quote / heredoc body of another command — inert text, not a dispatch
        if start < consumed_end:
            continue  # inside an earlier invocation's message VALUE — prose, not a real invocation
        found = _first_commit_source(command[start:])
        if found is None:
            continue  # no inline -m → interactive/editor commit, don't block
        msg, end_offset = found
        consumed_end = start + end_offset
        if msg is None:
            continue  # -F/--file supplies the subject — exempt
        if MERGE_COMMIT_MSG_RE.match(msg.strip()):
            continue  # merge-commit default message — exempt
        if not CONVENTIONAL_COMMIT_RE.match(msg.strip()):
            return (
                f"Blocked: commit message {msg!r} doesn't match conventional-commit grammar "
                "`type(scope)!: subject` (types: feat|fix|docs|style|refactor|perf|test|build|"
                "ci|chore|revert)."
            )


def check(ctx):
    return _check_conventional_commit(ctx.command)

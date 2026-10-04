"""nocommit_guard as a pre_tool guard (hook consolidation PR 6) — the old hook's body, moved verbatim.
Block committing obvious leftover artifacts.

Fires on a `git commit` (regex detection, flag-tolerant, `git -C <path>`-safe — same segment-split /
`-C`-resolution pattern as tdd_gate.py). BLOCKs when the staged diff ADDS a merge-conflict marker, a
`NOCOMMIT` / `DO NOT COMMIT` sentinel, or a `.DS_Store` file. Bypass: `WORKFLOW:no-nocommit`.

Floor patterns (always on) use only the py/node common regex subset so the twin (nocommit_guard.cjs)
matches byte-for-byte. Extra per-repo patterns are OPT-IN via `NOCOMMIT_PATTERNS` (env, comma-sep
regexes) or a `NOCOMMIT_PATTERNS=...` line in `.claude/worktrees.conf` (env wins). A bad opt-in regex
is skipped (fail-open) with a stderr breadcrumb — one typo never wedges commits.

Scans ADDED lines only (`+`, never the `+++`/`---` headers), so a pre-existing marker on an untouched
context line never blocks a later unrelated commit. NO `--amend`/merge exemption — a leftover marker
must never enter history regardless. Fail-open (exit 0) on any git error / exception / timeout: a
broken guard never wedges a commit — but a git-error fail-open leaves a stderr breadcrumb (an
UNSCANNED allow is not a clean allow).

Plan-parsing/logic is inlined (hooks run standalone under `uv run --script` and cannot import
siblings) — same reason docs_gate copied tdd_gate's logic.
"""
import os
import re
import sys

from _lib.git import run_memo
from _lib.vendor_lock import sha_matches, vendored_paths

SHELL_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||;|\n|\|")
BYPASS_SENTINEL = "WORKFLOW:no-nocommit"
# git global options that CONSUME the following token as their value — skipped when locating the
# subcommand so `git -C <path> commit` / `git -c k=v commit` resolve to subcommand `commit`.
GIT_OPTS_WITH_ARG = ("-C", "-c", "--git-dir", "--work-tree", "--namespace",
                     "--exec-path", "--super-prefix")


def _tokenize(segment):
    """Whitespace-split honoring single/double quotes — byte-identical algorithm to the node twin's
    `tokenize` (nocommit_guard.cjs) so a commit segment tokenizes the SAME across twins (#491). Quotes
    are stripped and quoted runs joined to their neighbours (`git c"o"mmit` -> `git commit`,
    `-C "a b"` -> [`-C`, `a b`]).
    ponytail: no backslash-escape handling — git commit commands don't use \\-escaped paths; the two
    twins staying identical matters more than POSIX-completeness for a fail-open guard.
    """
    out = []
    cur = None
    i, n = 0, len(segment)
    while i < n:
        c = segment[i]
        if c in " \t\r\n":
            if cur is not None:
                out.append(cur)
                cur = None
            i += 1
            continue
        if c in "\"'":
            q = c
            i += 1
            start = i
            while i < n and segment[i] != q:
                i += 1
            cur = (cur or "") + segment[start:i]
            i += 1  # skip closing quote (unterminated -> i>n, loop ends)
            continue
        cur = (cur or "") + c
        i += 1
    if cur is not None:
        out.append(cur)
    return out


def _is_git_commit(segment):
    """True if `segment` invokes `git commit` — flag-tolerant, `git -C <path> commit`-safe."""
    toks = _tokenize(segment)
    i = 0
    while i < len(toks) and toks[i] != "git":
        i += 1
    i += 1  # step past 'git' (or past end -> loop below returns False)
    while i < len(toks):
        t = toks[i]
        if t in GIT_OPTS_WITH_ARG:
            i += 2
            continue
        if t.startswith("-"):  # any other option (incl. --opt=val) takes no separate token
            i += 1
            continue
        return t == "commit"
    return False

# Floor patterns — common py/node regex subset (identical semantics in `re` and RegExp).
MARKER_RE = re.compile(r"^\+(?:<{7}|>{7})(?:\s|$)")          # an ADDED conflict marker line
# #1015: a plain `\b` word boundary treats `-` as non-word, so `no-nocommit` (the bypass token's own
# name, e.g. in `WORKFLOW:no-nocommit`) still matched `\bNOCOMMIT\b` — any doc mentioning the bypass
# token tripped the guard it names. Review fix-round: an earlier version widened the excluded-neighbor
# class to ANY `-`/`_`, which also silently let real markers like `NOCOMMIT-later` / `pre-NOCOMMIT`
# through. Narrowed instead to a negative lookbehind for the literal `no-` prefix (the bypass token's
# own spelling) — the standalone `\b...\b` boundaries are otherwise unchanged, so a bare `NOCOMMIT`
# or a hyphen-adjacent one (other than `no-nocommit`) still blocks.
SENTINEL_RE = re.compile(r"(?<!no-)\b(?:NOCOMMIT|DO NOT COMMIT)\b", re.IGNORECASE)
DS_STORE = ".DS_Store"


def _run_git(cwd, *args):
    # #743: this guard's own breadcrumb pattern, now the SHARED runner. color_off=True keeps the
    # diff-scan seeing uncolored +/- prefixes (the machine may set color.ui=always globally). A scan
    # that couldn't run is a blind allow, not a clean allow — the shared runner leaves the trace.
    return run_memo("nocommit_guard", cwd, ["git", *args], timeout=8, color_off=True)


def _resolve_git_cwd(segment, cwd):
    # Only a `-C <path>` BEFORE the subcommand is git's global cwd flag — a `-C <ref>` at/after
    # `commit` is commit's reuse-message flag, not a cwd (#672). Walk global options from `git` and
    # stop at the first non-option token (the subcommand); mirrors _is_git_commit's walk. The
    # tokenizer keeps a spaced quoted path whole (#491), so `git -C "a b" commit` resolves to `a b`.
    toks = _tokenize(segment)
    i = 0
    while i < len(toks) and toks[i] != "git":
        i += 1
    i += 1  # step past 'git'
    target = None
    while i < len(toks):
        t = toks[i]
        if t == "-C" and i + 1 < len(toks):
            target = toks[i + 1]
            break
        if t in GIT_OPTS_WITH_ARG:
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        break  # subcommand reached — any later -C is not the cwd flag
    if target is None:
        return cwd
    return target if os.path.isabs(target) else os.path.join(cwd or ".", target)


def _commit_segment(command):
    """The first shell segment that invokes `git commit`, or None if none does."""
    return next(
        (s for s in SHELL_SEGMENT_SPLIT_RE.split(command) if _is_git_commit(s)),
        None,
    )


def _opt_in_patterns(cwd):
    val = os.environ.get("NOCOMMIT_PATTERNS")
    if val is None:
        conf_path = os.path.join(cwd or ".", ".claude", "worktrees.conf")
        try:
            with open(conf_path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            text = ""
        m = re.search(r'^NOCOMMIT_PATTERNS\s*=\s*"?([^"\n]*)"?', text, re.MULTILINE)
        val = m.group(1) if m else ""
    compiled = []
    for raw in val.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            compiled.append(re.compile(raw))
        except re.error:
            sys.stderr.write(f"nocommit_guard: skipping bad NOCOMMIT_PATTERNS regex: {raw}\n")
    return compiled


def _ds_store_hit(cwd):
    # --diff-filter=AM: added/modified only — never block DELETING a committed .DS_Store.
    out = _run_git(cwd, "diff", "--cached", "--name-only", "--diff-filter=AM")
    if not out:
        return None
    for path in out.split("\n"):  # split on \n only — parity with node's out.split('\n')
        path = path.strip()
        if path and os.path.basename(path) == DS_STORE:
            return path
    return None


def _content_hit(cwd, opt_in, vendored=None):
    vendored = vendored or {}
    out = _run_git(cwd, "diff", "--cached")
    if not out:
        return None
    current = "?"
    current_vendored = False
    for line in out.split("\n"):  # split on \n only — parity with node's out.split('\n')
        # Only real file headers (`+++ b/path`, or `+++ /dev/null` on a deletion). An ADDED content
        # line whose text is `++ foo` renders as `+++ foo` in the diff — it must fall through to the
        # `+`-content scan, NOT be mistaken for a header and skipped (would hide a sentinel).
        if line.startswith("+++ b/") or line == "+++ /dev/null":
            current = line[6:] if line.startswith("+++ b/") else line[4:]
            norm = current.replace("\\", "/")  # same normalization as tdd_gate's vendored lookup
            current_vendored = norm in vendored and sha_matches(cwd, norm, vendored[norm])
            continue
        if line.startswith("---") or not line.startswith("+"):
            continue
        if current_vendored:  # vendored content is reviewed upstream, not re-gated here
            continue
        if MARKER_RE.search(line):
            return ("merge-conflict marker", current)
        content = line[1:]  # strip the leading '+'
        if SENTINEL_RE.search(content):
            return ("NOCOMMIT / DO NOT COMMIT sentinel", current)
        for pat in opt_in:
            if pat.search(content):
                return (f"opt-in pattern /{pat.pattern}/", current)
    return None


def check(ctx):
    command = ctx.command
    cwd = ctx.data.get("cwd", "")
    commit_seg = _commit_segment(command)
    if commit_seg is None:
        return None
    if BYPASS_SENTINEL in command:
        return None
    git_cwd = _resolve_git_cwd(commit_seg, cwd)
    ds = _ds_store_hit(git_cwd)
    if ds:
        return (f"Blocked: staged `.DS_Store` ({ds}). Unstage it, or add "
                f"'{BYPASS_SENTINEL}' to the commit command.")
    vendored, note = vendored_paths(git_cwd)
    if note:
        ctx.notes.append(f"nocommit_guard: {note}")
    hit = _content_hit(git_cwd, _opt_in_patterns(git_cwd), vendored)
    if hit:
        what, where = hit
        return (f"Blocked: {what} in an added line of `{where}`. Remove it, or add "
                f"'{BYPASS_SENTINEL}' to the commit command.")
    return None

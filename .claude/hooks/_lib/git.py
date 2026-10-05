"""Git-command parsing + read-only git queries shared by the PreToolUse guards (hook consolidation
PR 5). Not the flat `_git.py` runner other hooks use — PR 6 folds that in here."""

import os
import re
import shlex
import subprocess


# Global options between `git` and the subcommand (`-C <path>`, `-c <cfg>`, `--git-dir[=| ]<path>`),
# repeatable. Defined here because H2 and H7 both need it; H7's own guards (issue #123, the
# `git -c core.pager=cat clean -fd` config-bypass class) consume it further down.
# Structural skip, NOT a whitelist. It used to name exactly `-C`, `-c` and `--git-dir`, which meant
# every other git global option smuggled a subcommand straight past the guards that use this:
# `git --no-pager clean -fd` and `git --no-optional-locks branch -D x` both went UNBLOCKED, and git
# has a good dozen more (`--paginate`/`-P`, `--bare`, `--literal-pathspecs`, `--exec-path=`,
# `--work-tree=`, `--namespace=`, …). Enumerating an open set is how that hole stayed open; matching
# the SHAPE of an option closes the family in one move. Order matters: the arms that take a SEPARATE
# argument come first so the argument is consumed with the flag, otherwise the trailing value would
# be left where the subcommand is expected.
#
# RESIDUAL, and it is structural rather than an oversight: the separate-argument arm still has to
# NAME its options, because nothing in the text of `--foo bar` says whether `bar` is that option's
# value or the subcommand. The list covers git's real set as of 2.50; a future git option taking a
# separate argument would reopen this one gap, in the safe-looking direction (the destroyer stops
# being matched). Pinned as H7-LIMIT-230 in tests/test_pretooluse_h7h8.sh so it can't be mistaken
# for handled — the attached `--foo=bar` spelling of ANY option is always caught by the generic arm.
_GIT_GLOBAL_OPT = (
    r"(?:"
    r"-C\s+\S+\s+|-c\s+\S+\s+"
    r"|--(?:git-dir|work-tree|namespace|exec-path|super-prefix|attr-source|config-env)"
    r"(?:=\S+|\s+\S+)\s+"
    r"|--[A-Za-z][A-Za-z-]*(?:=\S+)?\s+"
    r"|-[A-Za-z]\S*\s+"
    r")*"
)


# The commit-detection regex shared by EVERY commit-touching guard — H2 (message grammar), H3
# (secret scan), H6 (docs-staleness), H9 (giant-file), H10 (secret-file). `git -C <path> commit` /
# `git -c <cfg> commit` are REAL commits whose tokens aren't adjacent, so a bare `\bgit\s+commit\b`
# misses them — and this repo's own suite + cross-worktree workflow commit that way as the normal
# path. Widening to _GIT_GLOBAL_OPT closes the blind spot for all of them: #230 gave H2 this trigger;
# #237 extended it to H3/H6/H9/H10, which previously used the bare adjacency form. A guard that then
# needs the commit's TARGET repo resolves it via _resolve_git_cwd (the `-C` target), not the session
# cwd.
GIT_COMMIT_INVOCATION_RE = re.compile(r"\bgit\s+" + _GIT_GLOBAL_OPT + r"commit\b(?!-)")  # #744(3): (?!-) so `git commit-tree`/`commit-graph` plumbing don't over-trigger the commit guards


# H8 — protected-branch: `git commit` blocks unconditionally when the CURRENT branch (via `git
# rev-parse --abbrev-ref HEAD` in the payload's cwd, or a `-C <path>` repo if given) is
# main/master — a commit always lands on the current branch. `git push` is TARGET-aware (2nd
# fix-up, HIGH-1 still open after the 1st pass): it blocks ONLY when the push's actual
# DESTINATION resolves to main/master, not merely because you happen to be sitting on main —
# `git push origin feature-x` while on main must ALLOW. Fail-open if not a repo / detached HEAD /
# the subprocess errors. Override CT_ALLOW_PROTECTED=1 (segment-scoped).
PROTECTED_BRANCHES = ("main", "master")


# `git -C <path>`/`--git-dir=`/`--work-tree=` retarget a DIFFERENT repo than the payload's own cwd —
# honor them so `git -C other-repo commit` (and the --git-dir forms) is checked against the target
# repo's index/branch, not cwd's. These regexes run ONLY over the invocation HEAD (see
# _git_option_head), never the whole segment, so a flag embedded in a `-m <message>` can't redirect
# resolution to an attacker-named path (#367 review).
GIT_DASH_C_RE = re.compile(r"(?:^|\s)-C\s+(\S+)")


GIT_WORKTREE_RE = re.compile(r"--work-tree(?:=|\s+)(\S+)")


GIT_GITDIR_RE = re.compile(r"--git-dir(?:=|\s+)(\S+)")


# #371.3 — env-var redirect: a leading `GIT_DIR=… git commit` / `GIT_WORK_TREE=… git commit` points
# git at a DIFFERENT repo just like the flags do. Only assignment tokens BEFORE the `git` token count
# (see _git_env_prefix), so a `GIT_DIR=` inside a `-m <message>` can't redirect resolution.
GIT_ENV_ASSIGN_RE = re.compile(r"^(GIT_DIR|GIT_WORK_TREE)=(.*)$")


# git global options that take a SEPARATE-argument value (next token, not attached with `=`) — so
# _git_option_head consumes the value WITH the flag and never mistakes it for the subcommand.
GIT_VALUE_OPTS = frozenset({
    "-C", "-c", "--git-dir", "--work-tree", "--namespace",
    "--exec-path", "--super-prefix", "--attr-source", "--config-env",
})


# `git push` with an optional `-C <path>` — shared by _push_candidates and H8 (protected_branch).
GIT_PUSH_WITH_DASH_C_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?push\b(.*)$")

# H9 — giant-file: block staging a file over CT_MAX_FILE_MB (default 10) via `git add`/`git
# commit`. Override CT_ALLOW_BIGFILE=1 (segment-scoped). HIGH fix: the hook fires PRE-execution —
# at hook-check time NOTHING has actually been staged yet, so `git add -A`/`.`/`-u` (no explicit
# path on the command line) must be resolved to what `git status` says WOULD be staged, not just
# the literal path arguments (which for -A/-u is nothing, and for a bare `.` is a directory H9's
# os.path.isfile check silently skips) — closes the `git add -A && git commit` bypass.
GIT_ADD_RE = re.compile(r"\bgit\s+add\b")


ADD_STAGES_EVERYTHING_FLAGS = ("-A", "--all", "-u", "--update")


def _git_option_head(segment: str) -> str:
    """The global-option region between the leading `git` and its subcommand, joined back to a
    string. Everything from the subcommand onward (notably a `-m <message>`) is EXCLUDED, so a
    `-C`/`--git-dir=` sitting inside a commit message can't redirect cwd resolution (#367 review).
    Whitespace-split — a flag value containing spaces isn't handled (same limit as the old regex)."""
    toks = segment.split()
    try:
        i = toks.index("git") + 1  # first standalone `git` token = the real invocation
    except ValueError:
        return ""
    head = []
    while i < len(toks) and toks[i].startswith("-"):
        t = toks[i]
        head.append(t)
        i += 1
        if "=" not in t and t in GIT_VALUE_OPTS and i < len(toks):
            head.append(toks[i])  # this option's separate-argument value
            i += 1
    return " ".join(head)


def _git_env_prefix(segment: str) -> dict:
    """`GIT_DIR=…`/`GIT_WORK_TREE=…` assignment tokens that PRECEDE the `git` token — the env-var
    equivalents of `--git-dir`/`--work-tree` (#371.3). Stops at the first `git` token, so a
    `GIT_DIR=` sitting inside the commit message (which is after the subcommand, after `git`) is
    never read — same message-injection safety as _git_option_head."""
    out = {}
    for t in segment.split():
        if t == "git":
            break
        m = GIT_ENV_ASSIGN_RE.match(t)
        if m:
            out[m.group(1)] = m.group(2).strip("'\"")
    return out


def _resolve_git_cwd(segment: str, cwd: str) -> str:
    """`git -C <path>`/`--git-dir=`/`--work-tree=` and the `GIT_DIR=`/`GIT_WORK_TREE=` env prefixes
    target a DIFFERENT repo than the payload's own cwd — resolve it (relative to cwd if not absolute)
    and use THAT for the index/branch checks, instead of cwd's own repo (or failing open because cwd
    itself isn't a repo at all).

    Precedence (#367): `--git-dir` wins — it, not `--work-tree`, locates the index (`git diff
    --cached`) and HEAD that every consumer reads; then `-C` (explicit chdir); then `--work-tree`
    (best-effort); else cwd. A command-line flag beats its env-var equivalent (git's own precedence);
    repeated `-C x -C y` is applied cumulatively, as git does (#371.4). `--git-dir` resolves to the
    `.git`'s parent for the common `.git`-inside-worktree layout; a bare/linked/submodule git-dir
    whose basename isn't `.git` is used AS ITS OWN cwd — git discovers the correct index from inside
    it (verified for linked worktrees; a bare repo legitimately has no staged content to scan, #377).
    Only the invocation HEAD + the pre-`git` env prefix are scanned, never the message."""
    head = _git_option_head(segment)
    env = _git_env_prefix(segment)
    g = GIT_GITDIR_RE.search(head)
    gitdir = g.group(1).strip("'\"") if g else env.get("GIT_DIR")
    if gitdir:
        gitdir = gitdir if os.path.isabs(gitdir) else os.path.join(cwd or ".", gitdir)
        return os.path.dirname(gitdir) if os.path.basename(gitdir) == ".git" else gitdir
    target = None
    for m in GIT_DASH_C_RE.finditer(head):  # cumulative: each -C chdirs relative to the last (#371.4)
        t = m.group(1).strip("'\"")
        target = t if os.path.isabs(t) else os.path.join(target if target else (cwd or "."), t)
    if target is None:
        w = GIT_WORKTREE_RE.search(head)
        wt = w.group(1).strip("'\"") if w else env.get("GIT_WORK_TREE")
        if wt:
            target = wt if os.path.isabs(wt) else os.path.join(cwd or ".", wt)
    return target if target is not None else cwd


def _current_branch(cwd: str) -> str | None:
    """Best-effort current branch name; None on ANY failure (not a repo, detached HEAD, git
    missing, timeout) — shared by H7 (implicit force-push target) and H8 (protected-branch check);
    both callers fail OPEN when this returns None.

    #433: with no concrete cwd we cannot attribute the command to any repo. Running git anyway lets
    it inherit the HOOK PROCESS's own cwd (for the plugin, a claude_template checkout on `main`),
    which falsely blocked a plain `git commit` for an unrelated feature-branch repo as if it were on
    'main'. No cwd → fail open, never guess from the process's own branch."""
    if not cwd:
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=_clamp(3), check=False,
        )
    except Exception:  # noqa: BLE001
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    if not branch or branch == "HEAD":  # detached HEAD prints the literal string "HEAD"
        return None
    return branch


def _staged_names(cwd: str) -> list:
    """`git diff --cached --name-only`, fail-open (empty list) on any error. Shared by H6 (docs-
    staleness), H9 (giant-file at commit time), and H10 (secret-file at commit time). Routed through
    the per-call memo (hook consolidation PR 6) so the commit gates read the staged set once."""
    out = run_memo("pre_tool_use", cwd, ["git", "diff", "--cached", "--name-only"], timeout=5)
    return [p.strip() for p in out.splitlines() if p.strip()] if out else []


def _push_candidates(segment: str, cwd: str):
    """ALL candidate destination branches a `git push` in THIS segment could update, each paired
    with whether THAT specific ref is force-pushed — `[(branch, is_forced), ...]`. SHARED by H7
    (only cares about FORCED candidates) and H8 (2nd fix-up: cares about ALL candidates, forced or
    not — direct-to-protected-branch is the concern regardless of force). 3rd fix-up (narrow
    refspec bypasses the auditor's deeper probe found):
      1. A single push can update MULTIPLE refs at once (`git push origin main feature`) — only
         checking the LAST non-flag token missed an EARLIER protected one
         (`git push origin main feature` let `main` through). Every non-flag token AFTER the
         remote is now evaluated as its own candidate.
      2. git's short per-ref force marker — a leading `+` directly on a ref, e.g. `+main` — is
         EXACTLY as dangerous as `--force ... main` but carries no `--force`/`-f` flag anywhere in
         the command at all, so the old "is there a force flag present" check alone missed it
         (`+refs/heads/main`, the LONG form, was accidentally caught because splitting on `/` and
         taking the last segment happened to still land on `main`; the SHORT form `+main` was
         not — `+` was never stripped before the comparison). Each token's leading `+` is now
         stripped before deriving the branch name, and that per-ref `+` ALSO counts as forced for
         THAT ref even with no `--force`/`-f` flag anywhere else in the command.
    `HEAD` resolves to the CURRENT branch; a `src:dst` refspec is evaluated on its `dst` side.
    Returns `[]` if this isn't a `git push` at all, or if it's a tags/all-branches push with no
    single identifiable branch destination (`--tags`/`-t`/`--all` and no other ref arg)."""
    m = GIT_PUSH_WITH_DASH_C_RE.search(segment)
    if not m:
        return []
    rest = m.group(1)
    tokens = rest.split()
    non_flag_tokens = [tok for tok in tokens if not tok.startswith("-")]
    if not non_flag_tokens and any(f in tokens for f in ("--tags", "-t", "--all")):
        return []  # pushes tags / all branches — no single branch destination to protect
    global_force = bool(
        re.search(r"--force(?:-with-lease)?\b|(?:^|\s)-[a-zA-Z]*f[a-zA-Z]*(?:\s|$)", rest)
    )
    if len(non_flag_tokens) >= 2:
        # non_flag_tokens[0] is the remote; EVERY token after it is a candidate ref destination —
        # a push can update more than one ref at once, and each must be checked independently.
        candidates = []
        for tok in non_flag_tokens[1:]:
            forced = global_force or tok.startswith("+")
            ref = tok[1:] if tok.startswith("+") else tok  # strip the short force-refspec marker
            name = ref.split(":")[-1].split("/")[-1]
            branch = _current_branch(cwd) if name == "HEAD" else name
            candidates.append((branch, forced))
        return candidates
    # 0 or 1 non-flag tokens (no explicit branch/refspec — just maybe a bare remote name) — this
    # push targets the CURRENT branch by default (real git push.default semantics).
    return [(_current_branch(cwd), global_force)]


def _extract_add_paths(segment: str):
    """Non-flag argument tokens after `git add` — shlex-tokenized so a quoted path with spaces
    round-trips; falls back to a plain split on a shlex error (unbalanced quote, etc.)."""
    m = re.search(r"\bgit\s+add\b(.*)$", segment)
    if not m:
        return []
    try:
        tokens = shlex.split(m.group(1))
    except ValueError:
        tokens = m.group(1).split()
    return [t for t in tokens if t and not t.startswith("-")]


def _add_segment_stages_everything(segment: str) -> bool:
    """True for `git add -A`/`--all`/`-u`/`--update`, or a bare `.`/`./` path — any form that
    stages more than the literal path arguments on the command line."""
    m = re.search(r"\bgit\s+add\b(.*)$", segment)
    if not m:
        return False
    try:
        tokens = shlex.split(m.group(1))
    except ValueError:
        tokens = m.group(1).split()
    if any(t in ADD_STAGES_EVERYTHING_FLAGS for t in tokens):
        return True
    non_flag = [t for t in tokens if t and not t.startswith("-")]
    return any(p in (".", "./") for p in non_flag)


def _would_be_staged_by_add_all(cwd: str):
    """Enumerates what `git status --porcelain` reports as changed (tracked-modified + all
    untracked, following .gitignore) — the set of paths a `git add -A`/`.`/`-u` WOULD stage.
    Fail-open ([]) on any error. HIGH fix: the hook fires PRE-execution, so at hook-check time
    nothing has actually been staged by a `git add -A` in the SAME command yet — checking only
    literal path arguments (empty for -A/-u, a bare directory for `.`) missed this entirely,
    letting `git add -A && git commit ...` evade both H9 (giant-file) and H10 (secret-file)."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=cwd or None, capture_output=True, text=True, timeout=_clamp(5), check=False,
        )
    except Exception:  # noqa: BLE001
        return []
    if result.returncode != 0:
        return []
    paths = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        rest = line[3:].strip()
        if " -> " in rest:  # rename: "old -> new" — the NEW path is what add would (re-)stage
            rest = rest.split(" -> ", 1)[1].strip()
        if len(rest) >= 2 and rest[0] == '"' and rest[-1] == '"':
            rest = rest[1:-1]
        if rest:
            paths.append(rest)
    return paths


def _add_command_targets(segment: str, cwd: str):
    """Files a `git add` in THIS segment would actually stage — either the explicit path
    arguments, or (for -A/--all/-u/--update/a bare '.') everything `git status` reports as
    changed. The single call site H9 and H10 both use instead of `_extract_add_paths` directly."""
    if _add_segment_stages_everything(segment):
        return _would_be_staged_by_add_all(cwd)
    return _extract_add_paths(segment)


def _git_show_toplevel(cwd: str) -> str:
    """`git rev-parse --show-toplevel` from cwd; '' on ANY failure (not a repo, cwd gone, git
    missing, timeout, non-zero) — the H8 cwd-assertion backstop fails OPEN on all of these."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd or None, capture_output=True, text=True, timeout=_clamp(3), check=False,
        )
    except Exception:  # noqa: BLE001
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


from _git import clamp as _clamp  # noqa: E402 — #979 clamp direct git calls to the entry deadline
from _git import run as _git_run  # noqa: E402 — the shared fail-open runner (#743)

# Read-only index / work-tree facts several commit gates ask for in the same hook call (hook
# consolidation PR 6: `git diff --cached --name-only` used to run in 7 processes per commit). One
# hook process == one tool call, so a module-level memo is per-call. Only side-effect-free
# subcommands are memoized; fetch / rev-list / merge-base always run fresh.
_MEMO_SUBCMDS = frozenset({"diff", "status", "show"})
_memo = {}

# Labels of the memoized read-only git queries (diff/status/show) that FAILED this call. A failure
# fails-open (the guard allows without verifying) and used to be invisible on exit-0 stdout — the
# entry reads this and surfaces it (silent-failure-hunter #979/M-H1). Per-process == per-call.
failed_labels = []


def run_memo(label, cwd, argv, *, timeout, color_off=False, record=True):
    # record=False: this call has a legitimate FALLBACK (e.g. `git show :<path>` of a staged blob,
    # which fails by design for a path not in the index and the guard then reads the worktree file),
    # so its failure is NOT a blind-allow worth surfacing (#979/item2 — no false "git state unavailable").
    if argv[1:2] and argv[1] in _MEMO_SUBCMDS:
        key = (os.path.realpath(cwd or "."), tuple(argv), color_off)
        if key not in _memo:
            _memo[key] = _git_run(label, cwd, argv, timeout=timeout, color_off=color_off)
            if _memo[key] is None and record:  # the shared read failed → record it (reader dedups)
                failed_labels.append(label)
        return _memo[key]
    return _git_run(label, cwd, argv, timeout=timeout, color_off=color_off)

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""PreToolUse pr-gate — dispatches on the `gh pr …` subcommand.

`gh pr create` on a `feat/*` branch with NO spec/plan ADDED ON THE BRANCH (design-before-code,
GATE 1) → BLOCK. Bypass: `WORKFLOW:no-design` in the command. The check is branch-scoped — it diffs
against the merge-base with the trunk branch, NOT a repo-wide `git ls-files` — so a spec/plan that
was merged to trunk by an earlier PR does not silently satisfy every subsequent branch forever
(fix-round 1, CRITICAL-2).

`gh pr merge` whose CI isn't green or whose PR isn't cleanly mergeable (merge-safety, P7) → BLOCK.
Bypass: `WORKFLOW:force-merge` in the command. Fails OPEN (allows) whenever `gh` is
offline/unauthenticated/unparseable — this gate must never wedge a legitimate merge just because
the network or `gh` auth is unavailable.

`gh pr create` also emits a non-blocking WARN nudge ("dispatch a code-reviewer before merge") on
every successful (non-blocked) create — auto-review-on-pr Layer 2, docs/superpowers/specs/
2026-08-10-auto-review-on-pr-design.md. That nudge additionally carries a PR-ROUTER suggestion
(#508): one `gh pr list --json …,files` call finds any OTHER open PR touching the same files and
SUGGESTS pushing there instead of opening a new PR — suggest, never force (over-batching hurts
review/revert granularity). Fully fail-open — no suggestion on any git/gh hiccup.

`gh pr merge` additionally BLOCKS unless THREE marker axes are all satisfied — code-review,
security-review (Deliverable K) and test-quality (Deliverable L). All three go through ONE
head-bound evaluator, `_axis_status`: it reads `<!-- {prefix}:VERDICT@<sha> -->` comment markers
(and, for the code-review axis only, any `reviews` entry with `state == "APPROVED"`, whose
`commit.oid` is its sha), takes the LATEST event by ISO timestamp, and counts it ONLY when the
verdict is acceptable (code-review: APPROVE; security/test-quality: PASS or attended WAIVED) AND
its sha is a full 40-char sha equal to `headRefOid` — i.e. the review covers the CURRENT head. A
post-review push invalidates every axis. The block message is SPECIFIC to the failing condition:
no marker found, wrong verdict, a bare marker with no sha (old pre-head-binding format), an
abbreviated sha, or a marker reviewing an older commit (with how many commits back) — each pointing
at the exact `gh pr comment … @<headRefOid>` string to post. Bypasses are independent:
`WORKFLOW:no-review` / `WORKFLOW:no-security` / `WORKFLOW:no-test-quality` (and `WORKFLOW:force-merge`
for CI/mergeable); a merge failing several axes needs each matching token, and the block reason
always lists every currently-failing condition, not just the first.

A `WAIVED` marker carrying `reason=docs-only` (`<!-- {prefix}:WAIVED@<sha> reason=docs-only -->`,
posted by /pr-open on a tier-0 PR, #926) counts ONLY if the gate itself confirms, from
`files`/`changedFiles` in the same `gh pr view` call, that every changed path is tier-0 (the predicate
mirrored from bin/pr-tier): the list must be complete, contain no rename/copy, and every path must be
docs-only markdown. Otherwise it BLOCKS, naming the first offending path. Any other `reason=` on a
WAIVED blocks as unrecognized. A reason-less WAIVED is unchanged (attended consent; #937).

The three marker axes fail **CLOSED** on a missing/wrong/stale marker — but only once `gh pr view`
itself succeeded; if `gh` is unreachable (`pr is None`) the WHOLE gate still fails OPEN (a gate that
wedges every merge on a network blip is its own outage). The `autonomy: unattended` non-waivable
clause for WAIVED is DEFERRED; author-binding (the PR author can self-post a verdict — G12) is not
enforced here.

Detection is TOKEN-based, not a rigid `\\bgh\\s+pr\\s+(create|merge)\\b` regex — a global `gh` flag
between the program and the subcommand (`gh --repo org/repo pr merge 123`, `gh -R org/repo pr
create`) is common (routine in a multi-worktree setup where cwd's tracking is ambiguous) and must
not slip past detection (fix-round 1, CRITICAL-1). Any `--repo`/`-R`/`--hostname` flag found before
`pr` is preserved and forwarded to the internal `gh pr view` lookup so the merge-safety check
queries the SAME repo the merge itself targets.

Mirrors hooks/grill_gate.py's segment-split + fail-open patterns.
"""
import base64
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.parse

from _git import run as _git_run  # #743 — shared git-runner: fail-open BUT leave a stderr breadcrumb
from _lib.shell import SHELL_SEGMENT_SPLIT_RE as _BASE_SEGMENT_SPLIT_RE  # #1091 — ONE shared split base

# #782 — shared denial-capture helper (sibling module). Guarded: missing module → no-capture, never crash.
try:
    from _denial_telemetry import emit_denial as _emit_denial, set_context as _set_denial_context
except Exception:  # noqa: BLE001 - capture is best-effort; never block hook load
    _emit_denial = None
    _set_denial_context = None

# #1091 — the base boundaries are the ONE shared definition (_lib.shell, carrying the `(?<!>)` that
# keeps a `>|` noclobber redirect joined). pr_gate ALONE also splits a bare `&`: a lone `&`
# (backgrounding) starts a new command, so `sleep 1 & gh pr merge` must put `gh` at index 0 of its
# own segment for command-position detection (#447 fix-round). `&` is LAST and `&&` is FIRST so `&&`
# matches whole (never splits into two empty `&` segments).
SHELL_SEGMENT_SPLIT_RE = re.compile(_BASE_SEGMENT_SPLIT_RE.pattern + r"|&")
NO_DESIGN_BYPASS = "WORKFLOW:no-design"
FORCE_MERGE_BYPASS = "WORKFLOW:force-merge"
NO_REVIEW_BYPASS = "WORKFLOW:no-review"
NO_SECURITY_BYPASS = "WORKFLOW:no-security"
NO_TESTQUALITY_BYPASS = "WORKFLOW:no-test-quality"
NO_SUITE_BYPASS = "WORKFLOW:no-suite"
SPEC_PATHS = ("docs/superpowers/specs", "docs/superpowers/plans")
# All three merge-gate marker axes share ONE head-bound evaluator (`_axis_status`). A marker is
# `<!-- {prefix}:VERDICT@<sha> -->`; the `@<sha>` is optional in the regex so a bare (old-format)
# marker is DETECTED and rejected with a specific "needs a sha" message rather than silently ignored.
# The distinct per-axis prefix means no regex cross-matches another axis.
# `reason=` is optional. Only WAIVED reason=docs-only is machine-checked (`_docs_only_violation`); any
# other reason on a WAIVED blocks as unrecognized, so a typo can't quietly become an attended waiver.
MARKER_RE_TMPL = r"<!--\s*{prefix}:(\w+)(?:@([0-9a-f]+))?(?:\s+reason=([\w-]+))?\s*-->"
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
AUTO_WAIVER_REASON = "docs-only"
# #1073: a test-quality waiver for prose-only prompt-code markdown (commands/agents/rules) — prompt-code
# keeps security review, but prose has no testable behavior, so test-quality is machine-waived. Valid
# ONLY on the test-quality axis (a security:WAIVED reason=no-testable-behavior still blocks).
NO_TESTABLE_BEHAVIOR = "no-testable-behavior"
# Tier-0 (docs-only) path predicate, copied byte-for-byte from bin/pr-tier (#926). tests/test_pr_tier.sh
# PT-DRIFT pins the three copies (bash, py, node) equal. Keep to portable ERE syntax. Case-INSENSITIVE:
# macOS checkouts are case-insensitive, so `.Claude/x.md` loads exactly like `.claude/x.md`.
TIER0_DOC_RE = re.compile(r"\.md$", re.IGNORECASE)
TIER0_DENY_RE = re.compile(r"(^|/)(rules|commands|agents|global-agents|skills|hooks|\.claude|\.github)/|(^|/)(CLAUDE|CLAUDE\.local|project-context|SKILL)\.md$|(^|/)GATES[^/]*\.md$|\.template\.md$|(^|/)docs/lessons[^/]*\.md$|(^|/)plugins/[^/]+/docs/", re.IGNORECASE)
# #1073: prompt-prose predicate, also copied byte-for-byte from bin/pr-tier (pinned by PT-DRIFT). A .md
# under a plugin's prompt-code dirs (commands/agents/rules) or top-level rules/ — prose with no testable
# behavior, so the no-testable-behavior test-quality waiver is valid when every changed path is prose.
PROMPT_PROSE_RE = re.compile(r"(^|/)plugins/[^/]+/(commands|agents|rules)/.*\.md$|(^|/)rules/.*\.md$", re.IGNORECASE)
# changeType values whose `path` is the WHOLE story. RENAMED/COPIED hide the old path; anything else
# (missing, null, unknown) can't be verified — both fail closed.
VERIFIABLE_CHANGE_TYPES = ("ADDED", "MODIFIED", "DELETED", "CHANGED")
# Human-readable axis names for the "nothing found" message (AT-5: the code-review axis must read
# "no code review found …"). Other branches keep the raw marker prefix so the user sees the exact
# string to post.
DISPLAY_NAMES = {
    "code-review": "code review",
    "security-review": "security review",
    "test-quality": "test-quality review",
}
# Verdicts that satisfy the security axis. WAIVED = an attended human risk-acceptance (reason
# authored in the PR body by /pr-open — goodwill, not machine-checked here; the autonomy:unattended
# hard-reject of WAIVED is DEFERRED). PASS = a clean review.
SECURITY_OK_VERDICTS = {"PASS", "WAIVED"}
# Test-quality axis (Deliverable L): verifies the plan-named acceptance tests are green at head +
# ≥1 is mutation-proven able to fail.
TESTQUALITY_OK_VERDICTS = {"PASS", "WAIVED"}
# Suite axis (Task 1, suite merge-gate axis): active ONLY where CI is not required — where it is,
# the CI axis itself owns regression and the suite axis stays inert (see _check_merge).
SUITE_OK_VERDICTS = {"PASS", "WAIVED"}
CREATE_NUDGE = (
    "PR opened — run /pr-open to AUTO-DISPATCH the review panel + docs-impact (a command can spawn "
    "agents; this hook cannot). A panel is dispatched only through `/pr-open` — a hand-dispatched "
    "panel skips docs-impact and the round bookkeeping, so it is not a panel (agent-delegation.md). "
    "Reminder only, never blocks — the merge itself is gated on an APPROVE review marker."
)
FEAT_BRANCH_RE = re.compile(r"^feat/")
CI_FAILING_CONCLUSIONS = {
    "FAILURE", "CANCELLED", "TIMED_OUT", "ERROR", "STARTUP_FAILURE", "ACTION_REQUIRED",
}
# statusCheckRollup entries reporting one of these (in either `conclusion` or the legacy
# commit-status `state` field) are still IN PROGRESS — not green, but not "failing" either. Without
# this, a check with conclusion="" + state="PENDING" fell through both existing branches and was
# silently treated as OK (fix-round 1, MEDIUM).
CI_NON_TERMINAL_STATES = {"PENDING", "QUEUED", "IN_PROGRESS", "REQUESTED", "WAITING"}
# When CI is REQUIRED (#942), a `tests` check reporting one of these is NOT a pass — a skipped or
# neutral required check means CI effectively did not run, so the merge fails closed.
CI_SKIP_CONCLUSIONS = {"SKIPPED", "NEUTRAL"}
GH_VALUE_FLAGS = {"-R", "--repo", "--hostname"}
GH_TIMEOUT_S = 8  # the merge-path `gh pr view` (same budget the shared runner used)
# Tokens that may legitimately PRECEDE `gh` while `gh` is still the command being run — exec
# wrappers and shell keywords. Anything else before `gh` (echo/grep/prose/a heredoc-body line)
# means `gh` is an ARGUMENT or a mention, not the program invoked, so detection must skip it
# (command-vs-mention conflation, #447).
COMMAND_PREFIX_WRAPPERS = {
    "sudo", "env", "command", "exec", "nice", "nohup", "time", "stdbuf", "xargs",
    "then", "do", "else", "builtin",
}
_ASSIGN_RE = re.compile(r"^\w+=")


def _in_command_position(tokens: list, prog_index: int) -> bool:
    """True iff the token at prog_index is the command being run in its segment, not an argument.

    Every preceding token in the segment must be a `VAR=val` assignment or a known exec-wrapper.
    ponytail: wrapper flags/values aren't parsed (e.g. `sudo -u u gh …`) — such a prefix fails the
    check and falls through as fail-OPEN (misses the gate), never a false-block; bare `gh …`,
    `sudo gh …`, and `env VAR=v gh …` (the real-world merge invocations) all stay gated.
    """
    for tok in tokens[:prog_index]:
        if _ASSIGN_RE.match(tok) or tok in COMMAND_PREFIX_WRAPPERS:
            continue
        return False
    return True


def _tokenize(segment: str) -> list:
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def _skip_flags(tokens: list, i: int, value_flags: set) -> int:
    """Advance past a run of recognized flag tokens starting at i (never past a non-flag token)."""
    while i < len(tokens) and tokens[i].startswith("-") and tokens[i] != "-":
        tok = tokens[i]
        if "=" in tok:
            i += 1
        elif tok in value_flags:
            i += 2
        else:
            i += 1
    return i


def _subcommand_match(tokens: list, prog: str, path: tuple, value_flags: set):
    """Find `prog` (optionally preceded/followed by recognized flags) → `path` tokens in order.

    Returns (prefix_flags, end_index) for the first match — prefix_flags are the flag tokens found
    between `prog` and the FIRST path token (e.g. `["--repo", "org/x"]`), end_index is the token
    index right after the last matched path token. Returns None if no match.
    """
    for i, t in enumerate(tokens):
        if t != prog or not _in_command_position(tokens, i):
            continue
        j = i + 1
        prefix_start = j
        prefix_end = j
        ok = True
        for pos, expected in enumerate(path):
            j = _skip_flags(tokens, j, value_flags)
            if pos == 0:
                prefix_end = j
            if j >= len(tokens) or tokens[j] != expected:
                ok = False
                break
            j += 1
        if ok:
            return tokens[prefix_start:prefix_end], j
    return None


def _run(cwd: str, args: list, timeout: int = 8) -> str | None:
    # #743: delegate to the shared runner (fail-open WITH a breadcrumb). args is the full command
    # (git OR gh — the #508 router runs `gh pr list` through this same runner).
    return _git_run("pr_gate", cwd, args, timeout=timeout)


def _current_branch(cwd: str) -> str | None:
    out = _run(cwd, ["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return out.strip() if out else None


def _resolve_trunk(cwd: str) -> str | None:
    """Best-effort trunk ref to diff against: origin's default branch, else local main/master.

    Widened (fix-round 2, #142(b)) for repos whose trunk isn't `main`/`master` and have no
    `origin/HEAD` set (common when a remote's default-branch ref was never fetched/configured) — a
    repo trunked on e.g. `develop` used to resolve to None here, and `_has_spec_or_plan` fails OPEN
    on an unknown trunk, silently disabling the design-before-code gate for every `gh pr create`
    forever. Two additional, best-effort signals, tried in order:
      1. the CURRENT branch's own configured upstream (`@{u}`) — a feature branch created with
         tracking against the real trunk (`git checkout -b feat/x --track develop`) names it exactly;
      2. the repo-configured default branch name (`git config init.defaultBranch`), tried as both a
         remote-tracking ref and a local branch.
    Still returns None (fail open) if none of these resolve — see the claude-template-core plugin (docs/workflow/ENFORCEMENT.md) "Known
    limitations" for that residual case.
    """
    ref = _run(cwd, ["git", "symbolic-ref", "refs/remotes/origin/HEAD"])
    if ref:
        parts = ref.strip().split("/")
        if len(parts) >= 2:
            return "/".join(parts[-2:])
    for candidate in ("origin/main", "origin/master", "main", "master"):
        if _run(cwd, ["git", "rev-parse", "--verify", "--quiet", candidate]) is not None:
            return candidate
    upstream = _run(cwd, ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if upstream and upstream.strip():
        upstream = upstream.strip()
        # Reject a SELF push-upstream: `git push -u origin <branch>` (by far the most common way
        # @{u} gets set) makes @{u} resolve to the branch's OWN remote-tracking ref
        # (origin/<branch>), not the repo's trunk. Using it as trunk diffs HEAD against a ref
        # that's normally in sync with it (merge-base == HEAD), so the spec/plan diff is always
        # empty regardless of what the branch actually contains — a fail-CLOSED false-block on the
        # single most common git workflow (adversarial review, fix-round 2 CRITICAL). Strip the
        # leading remote-name segment and compare to the current branch to detect this case.
        branch = _current_branch(cwd)
        upstream_tail = upstream.split("/", 1)[1] if "/" in upstream else upstream
        if not branch or upstream_tail != branch:
            return upstream
    default_branch = _run(cwd, ["git", "config", "init.defaultBranch"])
    if default_branch and default_branch.strip():
        default_branch = default_branch.strip()
        for candidate in (f"origin/{default_branch}", default_branch):
            if _run(cwd, ["git", "rev-parse", "--verify", "--quiet", candidate]) is not None:
                return candidate
    return None


def _has_spec_or_plan(cwd: str, branch: str) -> bool:
    """Branch-scoped: did THIS branch add a spec/plan since it diverged from trunk?

    Diffs against the merge-base with trunk — NOT a repo-wide `git ls-files` — so a spec/plan
    merged to trunk by an earlier PR doesn't silently satisfy every later branch forever
    (fix-round 1, CRITICAL-2). Fails open (True — don't block on an unknown) whenever trunk can't be
    resolved or the diff can't be computed.
    """
    trunk = _resolve_trunk(cwd)
    if not trunk or trunk == branch:
        return True  # can't determine a distinct trunk -> fail open
    base = _run(cwd, ["git", "merge-base", "HEAD", trunk])
    if not base:
        return True  # unrelated histories / can't compute -> fail open
    base = base.strip()
    out = _run(cwd, ["git", "diff", "--name-only", f"{base}..HEAD", "--", *SPEC_PATHS])
    if out is None:
        return True
    return any(p.strip() for p in out.splitlines())


# Systemessages accumulated across ALL shell segments — emitted as EXACTLY ONE JSON object at the
# end of main (#968). A multi-segment command (`gh pr merge … && gh pr merge …`) must never print
# two JSON objects: two objects are invalid hook JSON, so the second silently drops the first's
# systemMessage (e.g. the "merge NOT checked" fail-open breadcrumb).
_MESSAGES: list = []


class _Block(Exception):
    """A segment decided to BLOCK. Carries the reason up to main, which emits the single block
    object (merged with any accumulated systemMessages) and exits 2."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _msg(text: str) -> None:
    if text:
        _MESSAGES.append(text)


def _block(reason: str):
    if _emit_denial is not None:  # #782 — metadata-only deny row; reason_class carries which pr sub-gate
        _emit_denial("pr_gate", reason)
    raise _Block(reason)


def _branch_files(cwd: str, branch: str) -> set | None:
    """Files this branch changed since diverging from trunk, or None if undeterminable (fail open)."""
    trunk = _resolve_trunk(cwd)
    if not trunk or trunk == branch:
        return None
    base = _run(cwd, ["git", "merge-base", "HEAD", trunk])
    if not base:
        return None
    out = _run(cwd, ["git", "diff", "--name-only", f"{base.strip()}..HEAD"])
    if out is None:
        return None
    return {p.strip() for p in out.splitlines() if p.strip()}


def _core_version_warning(cwd: str, files: set, trunk: str) -> str | None:
    """Non-blocking cache-lag WARN: claude-template-core content changed but the core plugin
    version was NOT bumped. Projects read the CACHED core version, so an un-bumped change never
    reaches the fleet. Fail-open (returns None on any git/parse error). ADVISORY only — the caller
    appends it to the create nudge's systemMessage; it never changes the decision.
    """
    CORE = "plugins/claude-template-core/"
    VER = CORE + ".claude-plugin/plugin.json"
    touched = [f for f in files
               if f.startswith(CORE)
               and f != VER
               and "/GENERATED" not in f
               and not f.endswith("GENERATED")]
    if not touched:
        return None

    def _ver(ref: str):
        out = _run(cwd, ["git", "show", f"{ref}:{VER}"])
        try:
            return json.loads(out).get("version") if out else None
        except Exception:  # noqa: BLE001 - fail open
            return None
    head, base = _ver("HEAD"), _ver(trunk)
    if head is None or base is None or head != base:
        return None  # bumped, or undeterminable -> stay silent (fail-open)
    return ("WARN: claude-template-core content changed but its version was not bumped — "
            "projects read the cached version, so this won't reach the fleet until you bump "
            "plugins/claude-template-core/.claude-plugin/plugin.json + marketplace.json.")


def _create_suggestion(cwd: str, branch: str | None) -> str:
    """PR-router (#508): SUGGEST an existing open PR that touches the same files. Never forces.

    Best-effort and fully fail-open: any git/gh failure or missing data yields no suggestion, so
    the normal create nudge is unchanged. One `gh pr list` call (with the `files` field) covers all
    open PRs — no per-PR round-trip.
    """
    if not branch:
        return ""
    mine = _branch_files(cwd, branch)
    if not mine:
        return ""
    out = _run(cwd, [
        "gh", "pr", "list", "--state", "open", "--limit", "50",
        "--json", "number,headRefName,files",
    ])
    if not out:
        return ""
    try:
        prs = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return ""
    hits = []
    for pr in prs if isinstance(prs, list) else []:
        if pr.get("headRefName") == branch:
            continue  # this branch's own PR, if any
        their = {f.get("path") for f in (pr.get("files") or []) if f.get("path")}
        overlap = mine & their
        if overlap:
            hits.append((len(overlap), pr.get("number") or 0))
    if not hits:
        return ""
    hits.sort(reverse=True)  # most-overlapping first; ties break by PR number desc (matches node)
    listed = "; ".join(f"#{num} ({n} shared file{'s' if n != 1 else ''})" for n, num in hits[:3])
    return (
        f" PR-router: {len(hits)} open PR(s) already touch these files — {listed}. Consider "
        "pushing there instead of opening a new PR (SUGGESTION, never forced — over-batching "
        "hurts review and revert granularity; open a separate PR if the concern is unrelated)."
    )


def _nudge_create(suffix: str = "") -> None:
    _msg(CREATE_NUDGE + suffix)


def _check_create(command: str, cwd: str) -> None:
    branch = _current_branch(cwd)
    suffix = _create_suggestion(cwd, branch)
    trunk = _resolve_trunk(cwd)
    files = _branch_files(cwd, branch) if branch else None
    if files and trunk:
        core_warn = _core_version_warning(cwd, files, trunk)
        if core_warn:
            suffix += " " + core_warn
    if NO_DESIGN_BYPASS in command:
        _nudge_create(suffix)
        return
    if not branch or not FEAT_BRANCH_RE.match(branch):
        _nudge_create(suffix)
        return
    if _has_spec_or_plan(cwd, branch):
        _nudge_create(suffix)
        return
    _block(
        f"Blocked: `gh pr create` on '{branch}' with no design artifact ADDED ON THIS BRANCH — "
        "GATE 1 requires a spec (docs/superpowers/specs/**) or plan (docs/superpowers/plans/**) "
        "from brainstorming/writing-plans before a PR. For a genuinely trivial change, add "
        f"'{NO_DESIGN_BYPASS}' to the command."
    )


def _collect_repo_flags(tokens: list, value_flags: set) -> list:
    """Collect every `--repo`/`-R`/`--hostname` flag(+value) anywhere in `tokens`, in order.

    Unlike `prefix_flags` (only flags found BEFORE the matched subcommand), this scans the whole
    segment — a `--repo`/`-R` placed AFTER `pr merge` (e.g. `gh pr merge --repo org/x 12 --squash`)
    is just as valid a persistent `gh` flag and must reach the internal `gh pr view` safety lookup,
    or merge-safety silently evaluates the CWD's default repo instead (fix-round 2, MEDIUM).
    """
    out = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in value_flags:
            if i + 1 < len(tokens):
                out.extend([tok, tokens[i + 1]])
            i += 2
        elif any(tok.startswith(f + "=") for f in value_flags):
            out.append(tok)
            i += 1
        else:
            i += 1
    return out


def _pr_json(cwd: str, tokens: list, end: int) -> tuple:
    """(pr_dict, None) on success, else (None, reason). The reason (gh exit + stderr, timeout, parse
    error) is what the merge path shows the user when it has to fail open (#955 / #936 item 1)."""
    args = ["gh", *_collect_repo_flags(tokens, GH_VALUE_FLAGS), "pr", "view"]
    j = _skip_flags(tokens, end, GH_VALUE_FLAGS)
    if j < len(tokens) and not tokens[j].startswith("-"):
        args.append(tokens[j])
    args += ["--json",
             "statusCheckRollup,mergeable,baseRefName,comments,reviews,headRefOid,commits,number,"
             "files,changedFiles"]
    try:
        r = subprocess.run(args, cwd=cwd or None, capture_output=True, text=True,
                           timeout=GH_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        return None, f"gh timed out after {GH_TIMEOUT_S}s"
    except Exception as exc:  # noqa: BLE001 - fail open, but carry the reason to the user
        return None, f"gh failed to run: {exc}"
    if r.returncode != 0:
        err = [ln.strip() for ln in (r.stderr or "").splitlines() if ln.strip()]
        return None, f"gh exited {r.returncode}" + (f": {err[-1]}" if err else "")
    try:
        pr = json.loads(r.stdout)
    except (json.JSONDecodeError, ValueError):
        return None, "gh returned invalid JSON"
    if not isinstance(pr, dict):
        return None, "gh returned an unexpected JSON shape"
    return pr, None


def _pr_label(tokens: list, end: int) -> str:
    j = _skip_flags(tokens, end, GH_VALUE_FLAGS)
    if j < len(tokens) and not tokens[j].startswith("-"):
        return f"PR {tokens[j]}"
    return "the current branch's PR"


def _run3(cwd: str, args: list) -> tuple:
    """(rc, stdout, stderr) for a short probe. rc is None if the command could not be launched.
    Used for the base-CI probe where the CALLER classifies rc/stderr into present/absent/unknown —
    so a gh/git ERROR is never silently collapsed into "no workflow" (#942 round-3, silent-failure)."""
    try:
        r = subprocess.run(args, cwd=cwd or None, capture_output=True, text=True,
                           timeout=GH_TIMEOUT_S, check=False)
    except Exception as exc:  # noqa: BLE001 — couldn't even launch
        return None, "", str(exc)
    return r.returncode, r.stdout or "", r.stderr or ""


def _last_err(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def _repo_flag_value(tokens: list, end: int) -> str | None:
    """The `--repo`/`-R` value from the merge command, if any (so base detection targets the right
    repo under `-R org/x`). `--hostname` is collected by the shared scanner but is not a repo."""
    flat = _collect_repo_flags(tokens, GH_VALUE_FLAGS)
    i = 0
    while i < len(flat):
        tok = flat[i]
        if tok in ("--repo", "-R") and i + 1 < len(flat):
            return flat[i + 1]
        if tok.startswith("--repo="):
            return tok.split("=", 1)[1]
        i += 1
    return None


def _normalize_repo(value: str) -> tuple:
    """(owner/repo, host|None) from a `-R` value that may be a bare `owner/repo`, a `host/owner/repo`,
    a full URL (`https://host/o/r.git`), or the scp form (`git@host:o/r.git`) — so a bad contents
    path can't masquerade as a 404 and read as 'absent' (code-review round-4)."""
    v = re.sub(r'^[a-zA-Z][a-zA-Z0-9+.\-]*://', '', (value or "").strip())  # strip scheme
    v = re.sub(r'^[^@/]+@([^:/]+):', r'\1/', v)  # scp form git@host:o/r -> host/o/r
    v = re.sub(r'\.git$', '', v.rstrip('/'))     # drop a trailing slash then a `.git` suffix
    parts = [p for p in v.split('/') if p]
    if len(parts) >= 3:
        return f"{parts[-2]}/{parts[-1]}", parts[-3]
    if len(parts) == 2:
        return f"{parts[0]}/{parts[1]}", None
    return v, None


def _wf_name(content: str) -> str:
    """The workflow's `name:` (stripped of quotes), or "" if present-but-unnamed."""
    m = re.search(r'(?m)^[ \t]*name:[ \t]*(.+?)[ \t]*$', content or "")
    return m.group(1).strip().strip('"').strip("'") if m else ""


def _require_ci_override(cwd: str):
    """Explicit CI-required override: True (force on) / False (opt out) / None (unset → base decides).
    Env `REQUIRE_CI` wins, else a `REQUIRE_CI=` line in `.claude/worktrees.conf`. An EMPTY value is
    UNSET. The conf regex anchors on the SAME line (no `\\s*` swallowing a newline) and strips an inline
    `# comment` (code-review review). Non-UTF-8 conf is swallowed, not raised (silent-failure review)."""
    val = os.environ.get("REQUIRE_CI")
    if val is None:
        conf_path = os.path.join(cwd or ".", ".claude", "worktrees.conf")
        try:
            with open(conf_path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except (OSError, ValueError):  # ValueError covers UnicodeDecodeError — never fail open on it
            text = ""
        m = re.search(r'^[ \t]*REQUIRE_CI[ \t]*=[ \t]*"?([^"\n#]*?)"?[ \t]*(?:#.*)?$', text, re.MULTILINE)
        val = m.group(1) if m else None
    if val is None or val.strip() == "":  # unset or empty -> let the base branch decide
        return None
    return val.strip().lower() not in ("0", "false", "no")


def _base_ci_status(cwd: str, tokens: list, end: int, base: str) -> tuple:
    """(status, wf_name, err, note) where status ∈ {'present','absent','unknown'} (#942). Read from
    the PR BASE ref, never the worktree. 'unknown' (a gh/git error, no resolvable ref, a timeout, a
    parse failure, OR a bare-local-ref fallback that lacks the file) must NOT be mistaken for 'no CI'
    — it fails CLOSED on an empty rollup. Only a real HTTP 404 / a resolved remote-tracking ref
    missing the path is 'absent'. An EMPTY workflow file counts as 'present'. `note` is an optional
    breadcrumb emitted on the (authoritative) origin-absent path."""
    if not base:
        return "unknown", None, "the PR has no base branch", ""
    repo = _repo_flag_value(tokens, end)
    if repo:
        owner_repo, host = _normalize_repo(repo)
        args = ["gh", "api"]
        if host:
            args += ["--hostname", host]
        ref_q = urllib.parse.quote(base, safe="")  # a base with `/` etc. must not break the path
        args.append(f"repos/{owner_repo}/contents/.github/workflows/test.yml?ref={ref_q}")
        rc, out, err = _run3(cwd, args)
        if rc is None:
            return "unknown", None, (err or "gh failed to run"), ""
        if rc != 0:
            if "HTTP 404" in err:  # the ONLY gh failure that means "no workflow" (match exactly)
                return "absent", None, "", ""
            return "unknown", None, (_last_err(err) or f"gh exited {rc}"), ""
        try:
            parsed = json.loads(out)
        except Exception as exc:  # noqa: BLE001
            return "unknown", None, f"unparseable gh api response ({exc})", ""
        if not isinstance(parsed, dict):  # a non-object body is undeterminable, not present-empty (twin parity)
            return "unknown", None, "gh api returned a non-object response", ""
        try:
            content = base64.b64decode(parsed.get("content") or "").decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            return "unknown", None, f"undecodable gh api content ({exc})", ""
        return "present", _wf_name(content), "", ""
    # local git path: resolve the base ref first, THEN probe the path in it.
    ref = None
    for cand in (f"origin/{base}", base):
        rc, out, err = _run3(cwd, ["git", "rev-parse", "--verify", "--quiet", f"{cand}^{{commit}}"])
        if rc == 0 and out.strip():
            ref = cand
            break
        if rc not in (0, 1):  # None (couldn't launch) / 128 (not a repo, git error) → undeterminable
            return "unknown", None, (_last_err(err) or f"git exited {rc}"), ""
    if ref is None:
        return "unknown", None, f"base ref not resolvable (origin/{base} or {base})", ""
    # `git ls-tree` distinguishes absent (rc 0, EMPTY output) from a git error (corrupt object, a
    # failed partial-clone fetch) — which `cat-file -e` collapsed into "absent" and silently turned
    # CI off (silent-failure round-4). A git error is UNKNOWN, not absent.
    rc, out, err = _run3(cwd, ["git", "ls-tree", "--full-tree", ref, "--",
                               ".github/workflows/test.yml"])  # --full-tree: path is root-relative (subdir cwd)
    if rc != 0:
        return "unknown", None, (_last_err(err) or f"git ls-tree exited {rc}"), ""
    if not out.strip():
        # Path not in the resolved ref. A remote-tracking `origin/<base>` is authoritative enough to
        # call ABSENT (with a not-fetched breadcrumb); the bare local `<base>` fallback is NOT — it
        # may be stale or a partial branch, so its "absence" is UNDETERMINABLE (silent-failure round-5).
        if ref == f"origin/{base}":
            note = (f"pr_gate: no .github/workflows/test.yml on local {ref} (not fetched) — "
                    "CI not enforced; re-fetch if the base has CI")
            return "absent", None, "", note
        return ("unknown", None, f"no .github/workflows/test.yml on local {ref} and origin/{base} "
                "did not resolve — treating as undeterminable", "")
    rc, out, err = _run3(cwd, ["git", "show", f"{ref}:.github/workflows/test.yml"])
    if rc != 0:
        return "unknown", None, (_last_err(err) or "could not read the base workflow"), ""
    return "present", _wf_name(out), "", ""


def _ci_required(pr: dict, tokens: list, end: int, cwd: str) -> tuple:
    """(mode, wf_name) where mode ∈ {'required','not','unknown'}. Decided from the PR BASE (#942).
    An explicit REQUIRE_CI override wins both ways; an opt-out, an origin-absent base, and an unknown
    base each emit a visible systemMessage."""
    status, wf_name, err, note = _base_ci_status(cwd, tokens, end, pr.get("baseRefName") or "")
    override = _require_ci_override(cwd)
    if override is True:
        return "required", wf_name
    if override is False:
        _msg("pr_gate: CI requirement disabled via REQUIRE_CI=0 opt-out — CI NOT enforced for this merge.")
        return "not", wf_name
    if status == "present":
        return "required", wf_name
    if status == "absent":
        if note:
            _msg(note)
        return "not", None
    _msg(f"pr_gate: could not determine base CI requirement for '{pr.get('baseRefName') or '?'}' "
         f"({err}) — failing closed on an empty check list. Opt out with REQUIRE_CI=0, or add "
         "WORKFLOW:force-merge if this merge is safe. (The base ref is read without fetching, so a "
         "stale local ref can misreport — re-fetch if unsure.)")
    return "unknown", wf_name


def _ci_ok(pr: dict, mode: str, wf_name=None) -> tuple:
    """(ok, reason). An empty/partial rollup is permissive UNLESS CI is required (#942): then a check
    named `tests` whose `workflowName` matches the base workflow must report SUCCESS for the head —
    missing/SKIPPED/NEUTRAL fail CLOSED. `mode='unknown'` fails CLOSED only on an EMPTY rollup; with a
    non-empty GREEN rollup it warns (message already emitted) and allows."""
    rollup = pr.get("statusCheckRollup") or []
    for check in rollup:
        conclusion = (check.get("conclusion") or "").upper()
        state = (check.get("state") or "").upper()
        if conclusion in CI_FAILING_CONCLUSIONS or state in CI_FAILING_CONCLUSIONS:
            return False, "CI checks are not all green"
        if state in CI_NON_TERMINAL_STATES:
            return False, "CI checks are not all green"
        if not conclusion and not state:
            return False, "CI checks are not all green"  # still pending → not yet green
    if mode == "not":
        return True, ""
    if mode == "unknown":
        if not rollup:
            return False, ("the base CI requirement is undeterminable and no checks were reported — "
                           "failing closed (set REQUIRE_CI=0 to opt out, or add WORKFLOW:force-merge "
                           "if this merge is safe)")
        return True, ""  # non-empty & green (passed the scan above) → warn-only, do not block
    tests = []
    for c in rollup:
        if str(c.get("name") or c.get("context") or "").lower() != "tests":
            continue
        wfn = str(c.get("workflowName") or "")
        # Constrain by the base workflow's name ONLY when both sides carry one — a stray CheckRun named
        # `tests` from another workflow is excluded, while a legacy commit status (no workflowName) still
        # counts (security LOW + silent-failure LOW).
        if wf_name and wfn and wfn != wf_name:
            continue
        tests.append(c)
    if not tests:
        return False, ("no passing `tests` CI check reported for this base (CI is required — set "
                       "REQUIRE_CI=0 to opt out)")
    for c in tests:
        concl = (c.get("conclusion") or c.get("state") or "").upper()  # a commit status uses `state`
        if concl in CI_SKIP_CONCLUSIONS:
            return False, f"the required `tests` CI check reported {concl}, not SUCCESS"
        if concl != "SUCCESS":
            return False, f"the required `tests` CI check is {concl or 'incomplete'}, not SUCCESS"
    return True, ""


def _mergeable_ok(pr: dict) -> bool:
    mergeable = (pr.get("mergeable") or "").upper()
    return mergeable != "CONFLICTING"


def _match_head_commit_value(tokens: list) -> str | None:
    """The value of a `--match-head-commit <sha>` / `--match-head-commit=<sha>` flag anywhere in
    `tokens`, or None if the flag is absent. Scans the WHOLE segment (like `_collect_repo_flags`) —
    the flag is valid anywhere in a `gh pr merge` invocation, not just before the subcommand."""
    for i, tok in enumerate(tokens):
        if tok == "--match-head-commit":
            return tokens[i + 1] if i + 1 < len(tokens) else ""
        if tok.startswith("--match-head-commit="):
            return tok.split("=", 1)[1]
    return None


def _match_head_ok(pr: dict, tokens: list) -> tuple:
    """(#956) Closes the race between the review-marker check and the actual merge: a push landing
    in between must not silently merge a head nobody reviewed. Requires the merge command to carry
    `--match-head-commit <headRefOid>` — GitHub itself then refuses the merge if the head moved
    between this check and the real `gh pr merge` call. Missing or mismatched -> BLOCK naming the
    exact flag+sha to add."""
    head = pr.get("headRefOid") or ""
    value = _match_head_commit_value(tokens)
    if value is None:
        return False, (
            f"the merge command is missing `--match-head-commit {head}` — this closes the race "
            "between the review check and the merge (a push could land in between); re-run with "
            f"`--match-head-commit {head}` added"
        )
    if value != head:
        if value.startswith("$") or "$(" in value:
            return False, (
                f"--match-head-commit {value} looks like an unexpanded shell variable — pr_gate reads "
                "the raw command string and can't expand it, so the LITERAL 40-character sha must be "
                f"pasted in, not a variable reference; the current head is {head} (pass "
                f"`--match-head-commit {head}` literally)"
            )
        return False, (
            f"--match-head-commit {value} does not match the PR's current head {head} — the head "
            "moved since this was written; re-run with the current sha"
        )
    return True, ""


def _commit_distance(pr: dict, old: str, head: str) -> str:
    commits = pr.get("commits")
    oids = [c.get("oid") or "" for c in (commits if isinstance(commits, list) else [])
            if isinstance(c, dict)]
    if old in oids and head in oids:
        n = oids.index(head) - oids.index(old)
        if n > 0:
            return f"{n} commit{'s' if n != 1 else ''} later"
    return "an older commit, not in this PR's history (force-pushed?)"


def _fix_hint(pr: dict, prefix: str) -> str:
    num = pr.get("number") or "<n>"
    head = pr.get("headRefOid") or "<headRefOid>"
    return (f"Re-run /pr-open, or post: gh pr comment {num} --body "
            f"'<!-- {prefix}:<VERDICT>@{head} -->'")


def _axis_status(pr: dict, prefix: str, ok_verdicts: set, use_reviews: bool) -> tuple:
    """(ok, reason) for one marker axis. Latest event (by ISO timestamp) decides.

    An event is (ts, VERDICT, sha_or_None). Markers come from comments; when use_reviews, an
    APPROVED GitHub review adds ("APPROVE", commit.oid). ok iff the latest verdict is in
    ok_verdicts AND its sha is a full 40-hex sha equal to headRefOid.
    """
    rx = re.compile(MARKER_RE_TMPL.format(prefix=re.escape(prefix)))
    events = []
    comments = pr.get("comments")
    for c in comments if isinstance(comments, list) else []:
        if not isinstance(c, dict):
            continue
        m = rx.search(str(c.get("body") or ""))
        ts = str(c.get("createdAt") or "")
        if m and ts:
            events.append((ts, m.group(1).upper(), m.group(2), m.group(3)))
    if use_reviews:
        reviews = pr.get("reviews")
        for r in reviews if isinstance(reviews, list) else []:
            if not isinstance(r, dict):
                continue
            ts = str(r.get("submittedAt") or "")
            if str(r.get("state") or "").upper() == "APPROVED" and ts:
                commit = r.get("commit")
                oid = commit.get("oid") if isinstance(commit, dict) else None
                events.append((ts, "APPROVE", str(oid) if oid else None, None))
    head = pr.get("headRefOid") or ""
    if not events:
        disp = DISPLAY_NAMES.get(prefix, prefix)
        return False, f"no {disp} found for the current head. {_fix_hint(pr, prefix)}"
    events.sort(key=lambda e: e[0])
    _, verdict, sha, reason = events[-1]
    if verdict not in ok_verdicts:
        return False, f"the latest {prefix} is {verdict}, not {'/'.join(sorted(ok_verdicts))}"
    if sha is None:
        return False, (f"found {prefix}:{verdict} without a commit sha (old format). "
                       f"{_fix_hint(pr, prefix)}")
    if not FULL_SHA_RE.match(sha):
        return False, (f"{prefix} sha {sha} is abbreviated; it must be the full 40-char "
                       f"headRefOid. {_fix_hint(pr, prefix)}")
    if not head or sha != head:
        return False, (f"{prefix} is for {sha[:7]}, but the PR head is now {head[:7]} "
                       f"({_commit_distance(pr, sha, head)}). {_fix_hint(pr, prefix)}")
    if verdict == "WAIVED" and reason is not None:
        if reason == AUTO_WAIVER_REASON:
            bad = _docs_only_violation(pr)
            if bad:
                return False, (f"{prefix}:WAIVED reason={AUTO_WAIVER_REASON} is only valid on a docs-only "
                               f"PR, but {bad}. Run the {prefix} reviewer (/pr-open --full). "
                               f"{_fix_hint(pr, prefix)}")
        elif reason == NO_TESTABLE_BEHAVIOR and prefix == "test-quality":
            # #1073: prose-only prompt-code markdown has no testable behavior. Valid ONLY here — any
            # other axis falls through to the unrecognized-reason reject below.
            bad = _prose_only_violation(pr)
            if bad:
                return False, (f"{prefix}:WAIVED reason={NO_TESTABLE_BEHAVIOR} is only valid on a "
                               f"prose-only PR (all changed paths markdown under docs or "
                               f"commands/agents/rules), but {bad}. Run the {prefix} reviewer "
                               f"(/pr-open --full). {_fix_hint(pr, prefix)}")
        else:
            return False, (f"{prefix}:WAIVED carries an unrecognized reason={reason} (this axis "
                           f"machine-checks only reason={AUTO_WAIVER_REASON}"
                           f"{f'/{NO_TESTABLE_BEHAVIOR}' if prefix == 'test-quality' else ''}). "
                           f"{_fix_hint(pr, prefix)}")
    return True, ""


def _docs_only_violation(pr: dict) -> str | None:
    """None iff the gate can SEE that every changed path is tier-0. Otherwise, the first problem.

    Fails closed on every shape it can't verify: missing/odd `files`, a truncated list (gh caps
    `files`, so `changedFiles` must equal len(files)), or a rename/copy (its old path isn't in `files`).
    """
    files = pr.get("files")
    if not isinstance(files, list) or not files:
        return "the gate could not read the PR's changed files"
    total = pr.get("changedFiles")
    if not isinstance(total, int) or isinstance(total, bool) or total != len(files):
        return f"the PR's file list is incomplete ({len(files)} of {total} files returned)"
    for f in files:
        path = f.get("path") if isinstance(f, dict) else None
        if not isinstance(path, str) or not path:
            return "a changed file has no path"
        ctype = str(f.get("changeType") or "").upper()
        if ctype in ("RENAMED", "COPIED"):
            return f"{path} is a rename/copy (its old path is not visible to the gate)"
        if ctype not in VERIFIABLE_CHANGE_TYPES:
            return (f"{path} has changeType {ctype or 'missing'} (only "
                    f"{'/'.join(VERIFIABLE_CHANGE_TYPES)} can be verified)")
        if not TIER0_DOC_RE.search(path) or TIER0_DENY_RE.search(path):
            return f"{path} is not a docs-only path"
    return None


def _prose_only_violation(pr: dict) -> str | None:
    """None iff every changed path is prose markdown with no testable behavior (#1073). Otherwise,
    the first problem. Prose = markdown that is either a tier-0 doc OR prompt-code markdown under
    commands/agents/rules (PROMPT_PROSE_RE). Any non-.md, or a .md that is neither (e.g. a hook's
    README), blocks. Fails closed on the same unverifiable shapes as _docs_only_violation.
    """
    files = pr.get("files")
    if not isinstance(files, list) or not files:
        return "the gate could not read the PR's changed files"
    total = pr.get("changedFiles")
    if not isinstance(total, int) or isinstance(total, bool) or total != len(files):
        return f"the PR's file list is incomplete ({len(files)} of {total} files returned)"
    for f in files:
        path = f.get("path") if isinstance(f, dict) else None
        if not isinstance(path, str) or not path:
            return "a changed file has no path"
        ctype = str(f.get("changeType") or "").upper()
        if ctype in ("RENAMED", "COPIED"):
            return f"{path} is a rename/copy (its old path is not visible to the gate)"
        if ctype not in VERIFIABLE_CHANGE_TYPES:
            return (f"{path} has changeType {ctype or 'missing'} (only "
                    f"{'/'.join(VERIFIABLE_CHANGE_TYPES)} can be verified)")
        if not TIER0_DOC_RE.search(path):
            return f"{path} is not markdown (prose has no testable behavior; code does)"
        # a .md is prose iff it's a tier-0 doc OR prompt-code markdown (commands/agents/rules)
        if TIER0_DENY_RE.search(path) and not PROMPT_PROSE_RE.search(path):
            return f"{path} is markdown but not prose-only prompt-code (commands/agents/rules)"
    return None


def _worktree_merge_warning(cwd: str) -> str | None:
    """Non-blocking: warn if a `gh pr merge` will hit the 'branch already used by worktree'
    local-cleanup failure (#179/#196). Fail-open (returns None on any git error). ADVISORY only —
    the caller appends it as a systemMessage on the ALLOW path; it never changes the decision.
    """
    out = _run(cwd, ["git", "worktree", "list", "--porcelain"])
    if not out:
        return None
    checked_out = set()
    for line in out.splitlines():
        if line.startswith("branch refs/heads/"):
            checked_out.add(line[len("branch refs/heads/"):].strip())
    trunk = _resolve_trunk(cwd) or ""
    trunk_local = trunk.rsplit("/", 1)[-1] if trunk else ""
    if any(t in checked_out for t in (trunk_local, "main", "master") if t):
        return (
            "⚠ pr_gate: main/master is checked out in a worktree — `gh pr merge` will complete the "
            "REMOTE merge but its LOCAL cleanup may fail ('branch already used by worktree'). "
            "Don't re-merge: confirm `git log origin/main` shows the squash commit, remove the "
            "holding worktree, then finish by hand (#179/#196)."
        )
    return None


def _emit_merge_warning(cwd: str) -> None:
    _msg(_worktree_merge_warning(cwd))


def _check_merge(command: str, tokens: list, end: int, cwd: str) -> None:
    force_bypass = FORCE_MERGE_BYPASS in command
    review_bypass = NO_REVIEW_BYPASS in command
    security_bypass = NO_SECURITY_BYPASS in command
    testquality_bypass = NO_TESTQUALITY_BYPASS in command
    suite_bypass = NO_SUITE_BYPASS in command
    # ponytail: always fetch (dropped the old `force_bypass and review_bypass → return` short-circuit).
    # With a THIRD axis it was a fail-OPEN hole — a `force-merge + no-review` command would skip the
    # fetch and never evaluate security. One `gh pr view` is cheap; removing the special case removes
    # the hole (plan GK2).
    pr, why = _pr_json(cwd, tokens, end)
    if pr is None:
        # gh offline/unauthenticated/unparseable → fail open (WHOLE gate, all axes) — but VISIBLY: the
        # user must see that nothing was checked (#955 / #936 item 1). ONE systemMessage on stdout (the
        # advisory worktree warn folded in) plus a stderr copy.
        msg = (f"pr_gate: could not read {_pr_label(tokens, end)} via gh pr view ({why}) — "
               "merge NOT checked (CI/review/security/test-quality)")
        warn = _worktree_merge_warning(cwd)
        _msg(msg + (" " + warn if warn else ""))
        return
    ci_mode, wf_name = _ci_required(pr, tokens, end, cwd)
    ci_ok, ci_why = _ci_ok(pr, ci_mode, wf_name)
    ci_ok = ci_ok or force_bypass
    mergeable_ok = _mergeable_ok(pr) or force_bypass
    review_ok, review_why = _axis_status(pr, "code-review", {"APPROVE"}, True)
    security_ok, security_why = _axis_status(pr, "security-review", SECURITY_OK_VERDICTS, False)
    testquality_ok, testquality_why = _axis_status(pr, "test-quality", TESTQUALITY_OK_VERDICTS, False)
    if ci_mode != "required":
        suite_ok, suite_why = _axis_status(pr, "suite", SUITE_OK_VERDICTS, False)
        suite_ok = suite_ok or suite_bypass
    else:
        suite_ok, suite_why = True, ""  # CI axis owns regression where CI is required
    match_head_ok, match_head_why = _match_head_ok(pr, tokens)
    review_ok = review_ok or review_bypass
    security_ok = security_ok or security_bypass
    testquality_ok = testquality_ok or testquality_bypass
    match_head_ok = match_head_ok or force_bypass
    if ci_ok and mergeable_ok and match_head_ok and review_ok and security_ok and testquality_ok and suite_ok:
        _emit_merge_warning(cwd)  # advisory, additive — emitted ONLY on the ALLOW path
        return
    reasons = []
    if not ci_ok:
        reasons.append(ci_why or "CI checks are not all green")
    if not mergeable_ok:
        reasons.append("the PR is not cleanly mergeable (conflicting with its base)")
    if not match_head_ok:
        reasons.append(match_head_why)
    if not review_ok:
        reasons.append(review_why)
    if not security_ok:
        reasons.append(security_why)
    if not testquality_ok:
        reasons.append(testquality_why)
    if not suite_ok:
        reasons.append(suite_why)
    _block(
        "Blocked: `gh pr merge` — " + " and ".join(reasons) + ". Fix the underlying issue, or "
        f"if this merge is genuinely safe, add '{FORCE_MERGE_BYPASS}' (CI/mergeable) and/or "
        f"'{NO_REVIEW_BYPASS}' (review) and/or '{NO_SECURITY_BYPASS}' (security) and/or "
        f"'{NO_TESTQUALITY_BYPASS}' (test-quality) and/or '{NO_SUITE_BYPASS}' (suite) to the command "
        "as appropriate."
    )


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    if _set_denial_context is not None:  # #782 — attribute a later deny to tool + session
        _set_denial_context(data.get("tool_name", ""), data.get("session_id", ""))
    if data.get("tool_name", "") not in ("Bash", "PowerShell"):
        sys.exit(0)
    command = data.get("tool_input", {}).get("command", "")
    cwd = data.get("cwd", "")
    block_reason = None
    try:
        for segment in SHELL_SEGMENT_SPLIT_RE.split(command):
            tokens = _tokenize(segment)
            m = _subcommand_match(tokens, "gh", ("pr", "create"), GH_VALUE_FLAGS)
            if m is not None:
                _check_create(command, cwd)
                continue
            m = _subcommand_match(tokens, "gh", ("pr", "merge"), GH_VALUE_FLAGS)
            if m is not None:
                _, end = m
                _check_merge(command, tokens, end, cwd)
    except _Block as b:
        block_reason = b.reason  # first BLOCK stops the scan; merged into the single object below
    except Exception as e:  # noqa: BLE001 - never brick a session; fail open with a visible breadcrumb
        _msg(f"pr_gate: internal error ({type(e).__name__}: {e}) — failing open, merge NOT checked")
    _emit(block_reason)


def _emit(block_reason):
    """Print EXACTLY ONE JSON object (#968): a block decision and/or a merged systemMessage.
    Exit 2 on a block (dual-form block JSON + stderr feedback), else exit 0."""
    out = {}
    if block_reason is not None:
        # Dual-form block JSON: top-level `decision` is DEPRECATED upstream; the current form is
        # hookSpecificOutput.permissionDecision=deny. Emit BOTH so older harnesses keep working.
        out["decision"] = "block"
        out["reason"] = block_reason
        out["hookSpecificOutput"] = {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": block_reason,
        }
    if _MESSAGES:
        out["systemMessage"] = " ".join(_MESSAGES)
    if out:
        print(json.dumps(out))  # noqa: T201 — the ONE object
    if block_reason is not None:
        # exit-2 feedback channel: the harness ignores stdout JSON on exit 2, so the accumulated
        # detail (gh/git error, earlier fail-open notices, the REQUIRE_CI notice) MUST ride stderr
        # alongside the block reason (silent-failure round-4).
        tail = (" " + " ".join(_MESSAGES)) if _MESSAGES else ""
        print(block_reason + tail, file=sys.stderr)  # noqa: T201
        sys.exit(2)
    if _MESSAGES:
        # #955 dual-channel: the fail-open / breadcrumb messages are ALSO copied to stderr (the
        # single-object refactor must not drop the stderr copy the comments promise).
        print(" ".join(_MESSAGES), file=sys.stderr)  # noqa: T201
    sys.exit(0)


if __name__ == "__main__":
    main()

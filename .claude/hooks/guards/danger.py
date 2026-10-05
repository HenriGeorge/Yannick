"""H7 — danger guard: rm -rf on sensitive paths, force-push to main/master, reset --hard to a
remote ref, the #111 destroyers, and clobbering another agent's worktree (hook consolidation PR 5)."""

import os
import re
import subprocess

from _git import clamp as _git_clamp  # #979 — clamp this guard's git to the entry's hard deadline
from _lib.git import PROTECTED_BRANCHES, _GIT_GLOBAL_OPT, _push_candidates, _resolve_git_cwd
from _lib.shell import _bare_shell_mask, _has_short_flag, _process_env_override, _segment_has_bare_command, _segment_has_leading_override, _segments_with_offsets, _strip_shell_quotes


# H7 — danger-guard: force-push to main/master, `git reset --hard <remote>/<branch>`, and `rm -rf`
# on sensitive/parent paths (extends the existing READONLY_PATHS rm-rf check above). Nudge-grade —
# same heuristic-not-shell-parser limitation as H1. Override CT_ALLOW_DANGER=1 — SEGMENT-SCOPED
# via `_segment_has_leading_override` (the #1 rule from the H1/H3 override-bypass saga: never a
# bare substring, never leak across a different shell segment).
SENSITIVE_RM_RF_TARGETS = (
    "/", "/*", "~", "~/", "$HOME", "..", "../", "/etc", "/etc/", "/usr", "/usr/",
    "/bin", "/bin/", "/var", "/var/", "/System", "/System/", "/Users", "/Users/",
    "/home", "/home/", "$env:USERPROFILE", "$env:HOME",
)


# #744(1): match `git reset` then capture the REST; the old `reset\s+--hard\s+(\S+)` required `reset`
# adjacent to `--hard` and grabbed the next token as target, so an interspersed flag slipped a
# destructive remote-ref reset (`git reset -q --hard origin/main`, `git reset --hard --quiet …`) toward
# ALLOW. _reset_hard_remote_target now finds the `--hard` token and takes the first NON-flag token after it.
RESET_REST_RE = re.compile(r"\bgit\s+reset\b(.*)$")


# issue #111 — more working-tree/branch destroyers that discard uncommitted or unpushed work with no
# reflog recovery: `git clean -f[d]` (deletes untracked files), `git branch -D` (force-delete an
# unmerged branch), `git checkout .` / `git restore .` (discard ALL working-tree changes). Each is a
# block-with-safe-alternative, same nudge-grade heuristic as the rest of H7. We do NOT block ordinary
# `git push`. Global options between `git` and the subcommand (`-C <path>`, `-c <cfg>`,
# `--git-dir[=| ]<path>`) are tolerated so they can't smuggle a destroyer past the guard (issue #123 —
# closes the `git -c core.pager=cat clean -fd` config-bypass class). Still a raw-string heuristic, not
# a shell tokenizer: a QUOTED flag/pathspec (`git clean '-f'`, `git checkout "."`) slips past — that
# gap is pinned in the H7-123-LIMIT tests as an intentional, known limitation.
GIT_CLEAN_RE = re.compile(r"\bgit\s+" + _GIT_GLOBAL_OPT + r"clean\b")


GIT_BRANCH_RE = re.compile(r"\bgit\s+" + _GIT_GLOBAL_OPT + r"branch\b")


GIT_CHECKOUT_REST_RE = re.compile(r"\bgit\s+" + _GIT_GLOBAL_OPT + r"checkout\b(.*)$")


GIT_RESTORE_REST_RE = re.compile(r"\bgit\s+" + _GIT_GLOBAL_OPT + r"restore\b(.*)$")


# issue #980 — raw disk-device writes: a shell redirect / `tee` / `dd of=` straight to a block
# device, or a destructive format/erase command, destroys the WHOLE disk with no reflog/trash to
# recover from — the user-settings deny rule that was supposed to catch this doesn't ship to fleet
# repos or cloud sessions (and was silently broken by a glob/prefix syntax mix-up). DEVICE_RE
# matches only the sd*/nvme*/disk*/rdisk* families, so /dev/null, /dev/stdout, /dev/stderr,
# /dev/tty and /dev/fd/* never match it — no separate allow-list check is needed.
DEVICE_RE = r"/dev/(?:sd|nvme|disk|rdisk)\w*"
# #980 fix round 1 — `>|` is the shell's noclobber-override redirect (bash/zsh); it still writes to
# the device just like a plain `>`.
REDIRECT_TO_DEVICE_RE = re.compile(r">>?\|?\s*(" + DEVICE_RE + r")\b")
TEE_TO_DEVICE_RE = re.compile(r"\btee\b(?:\s+-\S+)*\s+(" + DEVICE_RE + r")\b")
DD_OF_DEVICE_RE = re.compile(r"\bdd\b.*\bof=(" + DEVICE_RE + r")\b")
# #980 fix round 2 — round 1 anchored this to a FIXED command position (start of segment, behind
# only sudo/env/command), which was itself a regression: `(mkfs /dev/sdb)`, `{ mkfs /dev/sdb; }`,
# `time mkfs /dev/sdb`, `nohup mkfs /dev/sdb`, `exec mkfs /dev/sdb` all push the real command off
# position 0 and slipped past — all denied before #980. Match anywhere in the segment again (as
# before #980; also covers macOS `newfs_apfs`/`newfs_hfs`/etc.), and use a BLOCK-LIST of read-only
# INSPECTOR leads (see `INSPECTOR_LEAD_RE`) to keep `man mkfs`/`which wipefs`/`echo mkfs` allowed.
MKFS_WIPEFS_RE = re.compile(r"\b(mkfs(?:\.\w+)?|wipefs|newfs_\w+)\b")
# #980 fix round 2 — the segment's OWN lead command (after optional sudo/env) is a read-only
# lookup, so a disk-op command NAME merely mentioned as an ARGUMENT to it (`man mkfs`, `echo mkfs`)
# is not a real invocation.
INSPECTOR_LEAD_RE = re.compile(
    r"^\s*(?:(?:sudo|env)\s+)*(?:man|which|type|whatis|apropos|info|help|command\s+-v|echo|printf)\b"
)
DISKUTIL_DESTRUCTIVE_RE = re.compile(
    r"\bdiskutil\s+(eraseDisk|eraseVolume|partitionDisk|zeroDisk|randomDisk|secureErase)\b"
)


def _disk_device_write(segment: str):
    """(label, device-or-None) for a raw disk-device write in THIS segment, or None (issue #980).
    `mkfs`/`wipefs`/`diskutil` name the device by searching the whole segment for a DEVICE_RE
    match — their device argument isn't always right after the command name."""
    segment = _strip_shell_quotes(segment)
    m = REDIRECT_TO_DEVICE_RE.search(segment)
    if m:
        return ("shell redirect", m.group(1))
    m = TEE_TO_DEVICE_RE.search(segment)
    if m:
        return ("tee", m.group(1))
    m = DD_OF_DEVICE_RE.search(segment)
    if m:
        return ("dd", m.group(1))
    m = MKFS_WIPEFS_RE.search(segment)
    if m and not INSPECTOR_LEAD_RE.match(segment):
        dev = re.search(DEVICE_RE, segment)
        return (m.group(1), dev.group(0) if dev else None)
    m = DISKUTIL_DESTRUCTIVE_RE.search(segment)
    if m:
        dev = re.search(DEVICE_RE, segment)
        return (f"diskutil {m.group(1)}", dev.group(0) if dev else None)
    return None


def _has_dot_pathspec(rest: str) -> bool:
    """True if a bare `.` / `./` pathspec token appears in the args after the subcommand — the
    'discard EVERYTHING in the working tree' form of checkout/restore."""
    return any(tok in (".", "./") for tok in rest.split())


def _destructive_worktree_op(segment: str):
    """(label, safe-alternative) for a #111 destroyer in THIS segment, or None. `git clean` only
    acts with a force flag (and not in `-n`/--dry-run preview mode); `git branch -D` (or an explicit
    `--delete --force`) force-deletes; `git checkout .`/`git restore .` discard the whole worktree."""
    # #240 — strip single-quote, double-quote and backslash before matching so a QUOTED/ESCAPED
    # subcommand (`git "clean" -fd`, `git \clean -fd`, `git cle"an" -fd`), flag (`git clean "-fd"`)
    # or pathspec (`git checkout "."`) can't slip past the destroyer regexes. The shell dispatches
    # every one of these as the real destroyer. LOCAL to H7's destructive-op only — H2's frozen
    # `git "commit"` scope (shared `_GIT_GLOBAL_OPT`) is deliberately untouched. Byte-parity with the
    # JS twin's `segment.replace(/['"\\]/g, '')`.
    segment = _strip_shell_quotes(segment)
    if GIT_CLEAN_RE.search(segment):
        forced = _has_short_flag(segment, "f") or "--force" in segment
        preview = _has_short_flag(segment, "n") or "--dry-run" in segment
        if forced and not preview:
            return ("git clean -f", "irrecoverably deletes untracked files — preview with "
                    "`git clean -n` or save them with `git stash -u` first")
    if GIT_BRANCH_RE.search(segment):
        if _has_short_flag(segment, "D") or ("--delete" in segment and "--force" in segment):
            return ("git branch -D", "force-deletes a branch even if unmerged — use `git branch -d` "
                    "(refuses to drop unmerged work) or confirm it's merged/pushed first")
    m = GIT_CHECKOUT_REST_RE.search(segment)
    if m and _has_dot_pathspec(m.group(1)):
        return ("git checkout .", "discards ALL uncommitted working-tree changes — stash them "
                "(`git stash`) or restore specific files by name instead")
    m = GIT_RESTORE_REST_RE.search(segment)
    if m and _has_dot_pathspec(m.group(1)):
        rest = m.group(1)
        staged = "--staged" in rest or _has_short_flag(rest, "S")
        worktree = "--worktree" in rest or _has_short_flag(rest, "W")
        # S1 fix (#111): `git restore` defaults to the WORKING TREE unless --staged/-S is given.
        # `git restore --staged .` only unstages (index-only, working tree untouched) — the standard
        # "unstage everything", NOT destructive. It's destructive only when the working tree is
        # actually touched: an explicit --worktree/-W, or the default (no --staged).
        if worktree or not staged:
            return ("git restore .", "discards ALL uncommitted working-tree changes — stash them "
                    "(`git stash`) or restore specific files by name instead")
    return None


# MED fix: `@{upstream}`/`@{u}` are remote-tracking shorthand too, not just an explicit `origin/x`.
RESET_HARD_UPSTREAM_SHORTHAND = ("@{upstream}", "@{u}")


def _is_rm_rf(segment: str) -> bool:
    """Best-effort rm -rf / -fr / --recursive+--force detector — a nudge-grade guard, not a shell
    parser; doesn't try to see through `bash -c` or aliases (same class of limitation as H1)."""
    segment = _strip_shell_quotes(segment)  # #251 — a quoted/escaped `-rf` must not slip past
    if not re.search(r"\brm\b", segment):
        return False
    has_r = bool(re.search(r"(?:^|\s)-[a-zA-Z]*r[a-zA-Z]*(?:\s|$)", segment)) or "--recursive" in segment
    has_f = bool(re.search(r"(?:^|\s)-[a-zA-Z]*f[a-zA-Z]*(?:\s|$)", segment)) or "--force" in segment
    return has_r and has_f


def _rm_rf_sensitive_target(segment: str):
    if not _is_rm_rf(segment):
        return None
    segment = _strip_shell_quotes(segment)  # #251 — match a quoted target (`rm -rf "/"`) too
    for target in SENSITIVE_RM_RF_TARGETS:
        # #908: PowerShell `$env:` names are case-insensitive — fold just those targets, so
        # `rm -rf $env:userprofile` is caught like `$env:USERPROFILE` (POSIX targets stay exact).
        flags = re.IGNORECASE if target.startswith("$env:") else 0
        if re.search(r"(?:^|\s)" + re.escape(target) + r"(?:\s|$)", segment, flags):
            return target
    # PR 8 (#908): Windows drive roots — IGNORECASE, since the Windows FS (and the Windows/Users
    # literals) is case-insensitive; without it `c:/windows` lowercase slips past this check.
    m = re.search(r"(?:^|\s)([A-Za-z]:/(?:\*|Windows/?|Users/?)?)(?:\s|$)", segment, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def _worktree_roots(cwd: str):
    """(own_realpath, {all worktree roots}) from git; ('', set()) on ANY error (fail-open)."""
    def _git(args):
        try:
            p = subprocess.run(["git", *args], cwd=cwd or None,
                               capture_output=True, text=True, timeout=_git_clamp(3), check=False)
            return p.stdout if p.returncode == 0 else ""
        except Exception:  # noqa: BLE001
            return ""
    roots = {os.path.normcase(os.path.realpath(ln[len("worktree "):].strip()))
             for ln in _git(["worktree", "list", "--porcelain"]).splitlines()
             if ln.startswith("worktree ")}
    top = _git(["rev-parse", "--show-toplevel"]).strip()
    own = os.path.normcase(os.path.realpath(top)) if top else ""
    return own, roots


def _worktree_remove_clobber(segment: str, cwd: str):
    """The path arg of a FORCED `git worktree remove` targeting a linked worktree that is NOT the
    caller's own — or None. Fail-open when the target can't be resolved to a known worktree."""
    m = re.search(r"\bworktree\s+remove\b(.*)", segment)
    if not m:
        return None
    tokens = m.group(1).split()
    if not any(t in ("-f", "--force") for t in tokens):
        return None
    paths = [t.strip("'\"") for t in tokens if not t.startswith("-")]
    if not paths:
        return None
    effective = _resolve_git_cwd(segment, cwd)
    own, roots = _worktree_roots(effective)
    if not own:
        return None
    for p in paths:
        target = os.path.normcase(os.path.realpath(p if os.path.isabs(p) else os.path.join(effective or ".", p)))
        if target in roots and target != own:
            return p
    return None


def _rm_rf_worktree_target(segment: str, cwd: str):
    """An `rm -rf` token whose realpath is a linked worktree root ≠ the caller's own — or None."""
    if not _is_rm_rf(segment):
        return None
    own, roots = _worktree_roots(cwd)
    if not own:
        return None
    for tok in segment.split():
        if tok.startswith("-") or "=" in tok or tok in ("rm",):
            continue
        cand = tok.strip("'\"")
        target = os.path.normcase(os.path.realpath(cand if os.path.isabs(cand) else os.path.join(cwd or ".", cand)))
        if target in roots and target != own:
            return cand
    return None


def _reset_hard_remote_target(segment: str):
    segment = _strip_shell_quotes(segment)  # #251 — a quoted `"--hard"`/target must not slip past
    m = RESET_REST_RE.search(segment)
    if not m:
        return None
    toks = m.group(1).split()
    if "--hard" not in toks:  # a soft/mixed reset (or no --hard at all) discards nothing unrecoverable
        return None
    after = toks[toks.index("--hard") + 1:]              # #744(1): flags may sit before AND after --hard
    target = next((t for t in after if not t.startswith("-")), None)  # first NON-flag token = the ref
    if not target:
        return None
    if target in RESET_HARD_UPSTREAM_SHORTHAND:  # MED fix: @{upstream} / @{u}
        return target
    return target if re.match(r"^[\w.-]+/[\w.-]+$", target) else None


def _check_danger_guard(command: str, cwd: str):
    # KNOWN LIMITATION, deliberately NOT solved (Increment-4 audit, LOW-MED): `cd / && rm -rf *`
    # evades `_rm_rf_sensitive_target` — we don't track cwd across `&&`-joined segments, and a
    # bare glob (`*`) isn't in SENSITIVE_RM_RF_TARGETS at all. Solving the first half needs a real
    # cwd-tracking state machine across segments (out of scope for a nudge-grade guard); solving
    # the second half by treating a bare `*` as sensitive would false-positive on completely
    # ordinary cleanup like `rm -rf build/*` or `rm -rf dist/*`. Pinned by
    # tests/test_pretooluse_h7h8.sh's "H7-LIMIT" case (asserts this is NOT detected) so the gap
    # stays a documented, intentional choice rather than a silent regression waiting to be found.
    if _process_env_override("CT_ALLOW_DANGER"):
        return
    bare = _bare_shell_mask(command)  # #889: an op merely quoted / heredoc-embedded is inert text
    for segment, seg_off in _segments_with_offsets(command):
        # #889: every danger detector is git- or rm-based and quote-STRIPS before matching, so a
        # fully-quoted op (`--body "... git branch -D ..."` / a heredoc body) would still match the
        # stripped substring. Skip a segment whose only git/rm token is inside a quote/heredoc — it is
        # inert text, not a dispatched command. A real op (incl. #240/#251 quoted-flag forms) keeps a
        # BARE `git`/`rm` base token, so this never disarms a genuine destroyer.
        # issue #980 — "dd"/"tee"/"mkfs"/"wipefs"/"diskutil" are disk-device op base commands, same
        # bare-token convention as git/rm; "dev" catches a plain shell REDIRECT (no command word of
        # its own) because every device path matched by DEVICE_RE contains the literal word "dev"
        # from its /dev/ prefix.
        if not _segment_has_bare_command(
            segment, seg_off, bare,
            words=("git", "rm", "dd", "tee", "mkfs", "wipefs", "diskutil", "dev"),
        ):
            continue
        reason = None
        rm_target = _rm_rf_sensitive_target(segment)
        if rm_target is not None:
            reason = (
                f"Blocked: 'rm -rf' targeting a sensitive/parent path ('{rm_target}') looks "
                "catastrophic, not a normal cleanup."
            )
        else:
            forced_protected = next(
                (b for b, forced in _push_candidates(segment, cwd) if forced and b in PROTECTED_BRANCHES),
                None,
            )
            if forced_protected is not None:
                reason = (
                    f"Blocked: force-push to protected branch '{forced_protected}'. Force-pushing "
                    "to main/master rewrites shared history."
                )
            else:
                reset_target = _reset_hard_remote_target(segment)
                if reset_target is not None:
                    reason = (
                        f"Blocked: 'git reset --hard {reset_target}' discards local commits "
                        "relative to a remote-tracking ref — likely destroys unpushed work."
                    )
                else:
                    dop = _destructive_worktree_op(segment)  # issue #111
                    if dop is not None:
                        label, advice = dop
                        reason = f"Blocked: '{label}' {advice}."
        if reason is None:
            disk = _disk_device_write(segment)  # issue #980
            if disk is not None:
                label, device = disk
                if device:
                    reason = (f"Blocked: '{label}' writes directly to disk device '{device}' — "
                              "this can destroy the entire disk with no recovery.")
                else:
                    reason = f"Blocked: '{label}' can destroy a disk with no recovery."
        if reason is None:
            wt = _worktree_remove_clobber(segment, cwd)
            if wt is not None:
                reason = (f"Blocked: 'git worktree remove --force {wt}' force-removes a DIFFERENT "
                          "agent's live worktree — the concurrent-worktree data-loss vector (#483). "
                          "Use plain `git worktree remove` (git refuses a dirty tree) or confirm "
                          "that agent is done.")
        if reason is None and rm_target is None:
            wt_rm = _rm_rf_worktree_target(segment, cwd)
            if wt_rm is not None:
                reason = (f"Blocked: 'rm -rf {wt_rm}' deletes a DIFFERENT agent's live worktree "
                          "directory — the concurrent-worktree data-loss vector (#483). Use "
                          "`git worktree remove` from the primary checkout, or confirm it's stale.")
        if reason is None:
            continue
        if _segment_has_leading_override(segment, "CT_ALLOW_DANGER"):
            continue
        return (reason + " Set CT_ALLOW_DANGER=1 to override.")


def check(ctx):
    return _check_danger_guard(ctx.command, ctx.cwd)

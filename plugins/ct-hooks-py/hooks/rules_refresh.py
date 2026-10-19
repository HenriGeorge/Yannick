#!/usr/bin/env python3
# dependencies = []
"""SessionStart hook — refresh always-core rule files from the plugin's bundled copy.

Fires ONLY when source == "startup" (self-filtered here, not via settings matchers).
Byte-compares each rule the plugin ships (${CLAUDE_PLUGIN_ROOT}/rules/*.md) against the
repo's .claude/rules/; if any differ or are missing repo-side AND the git tree is clean,
writes them, stages .claude/rules/, and commits `chore(rules): sync from plugin <ver>`.
Dirty tree (any staged/unstaged TRACKED change) → warn + skip. Fail-open, silent on error.
"""
import glob
import json
import os
import subprocess
import sys

from _lib.session import is_child_session


def _read_source():
    """Best-effort SessionStart `source` from stdin JSON; None on anything unreadable."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return None
        source = json.loads(raw).get("source")
        return source if isinstance(source, str) else None
    except Exception:
        return None


def _run(args, cwd, timeout=5):
    """subprocess.run wrapper that never raises — None on any failure."""
    try:
        return subprocess.run(args, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    except Exception:
        return None


def _plugin_version(plugin_root):
    try:
        with open(os.path.join(plugin_root, ".claude-plugin", "plugin.json")) as fh:
            return json.load(fh).get("version") or "unknown"
    except Exception:
        return "unknown"


def _imported_rule_names(project_dir):
    """Basenames the project CLAUDE.md @imports from .claude/rules/ (empty set if unreadable)."""
    try:
        with open(os.path.join(project_dir, "CLAUDE.md")) as fh:
            text = fh.read()
    except Exception:
        return set()
    out = set()
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("@.claude/rules/") and s.endswith(".md"):
            out.add(s[len("@.claude/rules/"):])
    return out


def _cites_global_rules(project_dir):
    """True if CLAUDE.md still names the removed machine-global ~/.claude/rules source (#857)."""
    try:
        with open(os.path.join(project_dir, "CLAUDE.md")) as fh:
            return "~/.claude/rules" in fh.read()
    except Exception:
        return False


def _rules_dir_ignored(project_dir):
    """True if git ignores .claude/rules — a committed stub with no tracked rule files would be
    silent context loss on a fresh clone (#194), so bootstrap must skip rather than commit it."""
    # Probe a path INSIDE the dir: a trailing-slash pattern (.claude/rules/) won't match the bare
    # non-existent dir path, but it does match a file under it.
    r = _run(["git", "check-ignore", os.path.join(".claude", "rules", "probe.md")], project_dir, timeout=3)
    return r is not None and r.returncode == 0


def _ensure_conventions_stub(project_dir, basenames):
    """Ensure CLAUDE.md carries the '## Conventions (always-core)' @import block, appended after ALL
    existing content (so it lands past any tool-managed block such as RTK's). The @import list is
    DERIVED from the rule basenames (sorted) — a rule can't be silently omitted (#856).

    Returns True if the stub is PRESENT after the call — whether we just appended it OR it was already
    there (possibly from an earlier bootstrap whose commit failed; the caller still stages CLAUDE.md so
    that uncommitted stub lands). Returns False ONLY on a read/write error, which the caller treats as
    a hard abort — never commit rule files without their loading stub (the #194 silent-loss class)."""
    path = os.path.join(project_dir, "CLAUDE.md")
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        return False
    if "## Conventions (always-core)" in text:
        return True  # already present (maybe uncommitted) — caller still stages CLAUDE.md
    imports = "\n".join("@.claude/rules/%s" % n for n in sorted(basenames))
    block = "%s\n\n## Conventions (always-core)\n\n%s\n" % (text.rstrip("\n"), imports)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(block)
    except Exception:
        return False
    return True


def _tree_dirty(project_dir):
    """True if any STAGED or unstaged TRACKED change exists. Untracked (?? lines) do NOT count."""
    r = _run(["git", "status", "--porcelain"], project_dir, timeout=5)
    if r is None or r.returncode != 0:
        return True  # can't tell → treat as dirty (safe: skip rather than risk a bad commit)
    for line in r.stdout.splitlines():
        if line and not line.startswith("??"):
            return True
    return False


def _warn_unresolved_imports(project_dir):
    """LOUD WARN when CLAUDE.md @imports a .claude/rules/ file that doesn't resolve — silent context
    loss (#194). Runs AFTER _sync_heal, so a repo whose imports auto-healed (or that has no @import
    block at all) stays quiet; only a genuinely-broken load surfaces. Fail-open."""
    names = _imported_rule_names(project_dir)
    if not names:
        return
    missing = [n for n in sorted(names)
               if not os.path.isfile(os.path.join(project_dir, ".claude", "rules", n))]
    if not missing:
        return
    print("⚠ [rules] always-core rules NOT loaded: CLAUDE.md @imports %d rule file(s) missing from "
          ".claude/rules/ — %s. Silent context loss (#194): those rules are absent from context this "
          "session. Fix: run `setup.sh --update-hooks --init-missing` (or propagate.sh), or restart on "
          "a clean tree to auto-heal." % (len(missing), ", ".join(missing)))


def _sync_heal(plugin_root, project_dir):
    plugin_rules = os.path.join(plugin_root, "rules")
    repo_rules = os.path.join(project_dir, ".claude", "rules")
    if not os.path.isdir(plugin_rules):
        return
    inside = _run(["git", "rev-parse", "--is-inside-work-tree"], project_dir, timeout=3)
    if inside is None or inside.returncode != 0:
        return
    # BOOTSTRAP is keyed on git-TRACKED emptiness, NOT the on-disk dir: the hook creates the dir
    # mid-run, so an on-disk check would mis-classify a half-finished bootstrap (files written, stub
    # or commit failed) as "done" and never append the stub — silently inert on downstream clones
    # (#857 review). No tracked rule files → still a bootstrap, so a partial run re-fires cleanly.
    bootstrap = False
    ls = _run(["git", "ls-files", "--", os.path.join(".claude", "rules")], project_dir, timeout=3)
    repo_rules_tracked = ls is not None and ls.returncode == 0 and bool(ls.stdout.strip())
    if not repo_rules_tracked:
        # Self-heal ONLY an old-model repo — one whose CLAUDE.md still cites the removed
        # machine-global ~/.claude/rules source. A repo that never referenced it is left untouched
        # (no imposing rules it never wanted). #857
        if not _cites_global_rules(project_dir):
            return
        if _rules_dir_ignored(project_dir):
            print("[rules] .claude/rules is gitignored; bootstrap skipped (a committed @import stub "
                  "with no tracked rule files is silent context loss, #194). Un-ignore it, then restart.")
            return
        bootstrap = True

    basenames = [os.path.basename(s) for s in sorted(glob.glob(os.path.join(plugin_rules, "*.md")))]
    stale = []  # (dst_path, src_bytes)
    created = []  # basenames absent repo-side → newly created this run (#399 stub check)
    for name in basenames:
        src = os.path.join(plugin_rules, name)
        dst = os.path.join(repo_rules, name)
        try:
            with open(src, "rb") as f:
                src_bytes = f.read()
        except Exception:
            continue
        try:
            with open(dst, "rb") as f:
                dst_bytes = f.read()
        except FileNotFoundError:
            dst_bytes = None
        except Exception:
            continue
        if dst_bytes is None or src_bytes != dst_bytes:
            stale.append((dst, src_bytes))
            if dst_bytes is None:
                created.append(name)
    # A bootstrap with nothing stale can still have committing to do (files on disk untracked from a
    # prior failed run), so only the non-bootstrap refresh path may short-circuit here.
    if not stale and not bootstrap:
        # #860: a prior add-ok/commit-failed run leaves .claude/rules STAGED but uncommitted — git
        # ls-files then sees it (repo_rules_tracked=true → bootstrap=false), and with on-disk matching
        # the plugin `stale` is empty, so we'd return here WITHOUT a word, never reaching _tree_dirty.
        # Detect a non-empty staged .claude/rules index and leave a breadcrumb instead.
        cached = _run(["git", "diff", "--cached", "--name-only", "--", os.path.join(".claude", "rules")], project_dir, timeout=5)
        if cached is not None and cached.returncode == 0 and cached.stdout.strip():
            print("[rules] .claude/rules has a staged-but-uncommitted change (a prior sync's commit "
                  "likely failed); nothing synced this run. Commit or `git restore --staged .claude/rules`, "
                  "then restart.")
        return

    ver = _plugin_version(plugin_root)
    if _tree_dirty(project_dir):
        print("[rules] stale vs plugin %s; refresh skipped (working tree dirty). "
              "Commit/stash and restart, or run propagate.sh." % ver)
        return

    for dst, src_bytes in stale:
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)  # bootstrap: .claude/rules may not exist yet
            with open(dst, "wb") as f:
                f.write(src_bytes)
        except Exception:
            return  # partial-write: stop; next clean startup retries the rest
    if bootstrap:
        # Abort WITHOUT committing if the stub can't be written — never commit rule files with no
        # loading stub (#194). A next run (rules still untracked) retries.
        if not _ensure_conventions_stub(project_dir, basenames):
            return
        # Stage ALL plugin rules (not just this run's stale set) so a prior run's on-disk-but-
        # untracked files also get tracked, plus CLAUDE.md for the stub.
        add_paths = [os.path.join(repo_rules, n) for n in basenames]
        add_paths.append(os.path.join(project_dir, "CLAUDE.md"))
    else:
        add_paths = [dst for dst, _ in stale]
    add = _run(["git", "add", "--"] + add_paths, project_dir)
    if add is None or add.returncode != 0:
        return
    # Nothing actually staged (e.g. bootstrap re-run after everything already committed) → no-op,
    # never an empty commit. `git diff --cached --quiet` exits 0 when the index matches HEAD.
    staged = _run(["git", "diff", "--cached", "--quiet"], project_dir, timeout=5)
    if staged is not None and staged.returncode == 0:
        return
    msg = ("chore(rules): bootstrap always-core rules from plugin %s" % ver) if bootstrap \
        else ("chore(rules): sync from plugin %s" % ver)
    commit = _run(["git", "commit", "-m", msg], project_dir, timeout=10)
    if commit is None or commit.returncode != 0:
        return
    if bootstrap:
        print("[rules] bootstrapped %d rule file(s) + @import stub from plugin %s; committed." % (len(basenames), ver))
    else:
        print("[rules] refreshed %d file(s) from plugin %s; committed." % (len(stale), ver))
    # #399: a NEW rule file lands here, but its CLAUDE.md @import stub isn't auto-edited (project-owned,
    # placeholder-bearing). Warn — don't mutate CLAUDE.md — so a new always-core rule never silently
    # fails to load (the #194 class). The stub is reconciled by setup.sh --update-hooks / propagate.sh.
    missing = [n for n in created if n not in _imported_rule_names(project_dir)]
    if missing:
        print("[rules] new rule file(s) not @imported by CLAUDE.md: %s — won't load until the "
              "'## Conventions (always-core)' stub lists them. Run setup.sh --update-hooks "
              "(or propagate.sh)." % ", ".join(missing))


def main():
    # Read stdin ONCE (it's single-use) before delegating to _sync_heal, then ALWAYS warn on an
    # unresolved @import regardless of the sync/heal early-return paths.
    if _read_source() != "startup":
        return
    if is_child_session():
        return
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    if plugin_root:
        try:
            _sync_heal(plugin_root, project_dir)
        except Exception as e:  # fail-open, but leave a stderr breadcrumb (never stdout — that feeds context)
            print("[rules] _sync_heal error (fail-open): %s" % e, file=sys.stderr)
    try:
        _warn_unresolved_imports(project_dir)
    except Exception as e:
        print("[rules] _warn_unresolved_imports error (fail-open): %s" % e, file=sys.stderr)


if __name__ == "__main__":
    main()

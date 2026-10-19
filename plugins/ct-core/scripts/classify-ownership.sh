#!/usr/bin/env bash
# classify-ownership.sh — single source of truth for "which repo owns this asset".
# Mirrors propagate.sh:250-252 (cmp-vs-template-counterpart). Prints exactly one bucket.
#
# SCOPE: classifies paths WITHIN THIS SCRIPT'S OWN REPO ONLY. ROOT is pinned to the script's
# checkout, and the UPSTREAM/REPO-LOCAL cmp compares that repo's copy against that repo's
# rules/ — so run it from the repo whose paths you're classifying (the /improve miner runs in the
# template repo). It does NOT compare a sibling/managed repo's file against the template source; a
# cross-repo "is this bespoke vs the template" verdict is a separate capability (deferred; see #511
# S4). Passing a path from another repo yields a bucket computed against THIS repo, not that one.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"   # this repo's root (see SCOPE note above)
p="${1:?usage: classify-ownership.sh <path>}"

# 1) SHARED-GLOBAL: anything under the user's ~/.claude tree
case "$p" in
  "$HOME/.claude/"*|~/.claude/*) echo "SHARED-GLOBAL"; exit 0;;
esac

# 2) hard never-touched project files (setup.sh:484) → REPO-LOCAL
base_rel="${p#./}"
case "$base_rel" in
  lessons.md|CLAUDE.md|project-context.md|README.md|.claude/agents/*|docs/lessons.md)
    echo "REPO-LOCAL"; exit 0;;
esac

# 3) template counterpart under managed .claude/{rules} → cmp decides
#    (agents are plugin-shipped, no copy — excluded)
case "$base_rel" in
  .claude/rules/*.md|rules/*.md)
    b="$(basename "$base_rel")"
    tmpl="$ROOT/rules/$b"
    abs="$ROOT/$base_rel"
    if [[ -f "$tmpl" ]]; then
      if [[ -f "$abs" ]] && cmp -s "$abs" "$tmpl"; then echo "UPSTREAM"; else
        # counterpart exists but differs → committed-bespoke, preserved locally
        [[ -f "$abs" ]] && { echo "REPO-LOCAL"; exit 0; }
        echo "UPSTREAM"
      fi
      exit 0
    fi
    # no template counterpart → additive local
    echo "REPO-LOCAL"; exit 0;;
esac

# 4) plugin-native shipped assets (docs/skills/commands/agents) → UPSTREAM
case "$base_rel" in
  plugins/*|skills/*|commands/*|docs/workflow/*) echo "UPSTREAM"; exit 0;;
esac

# 5) unclassifiable → needs a human call
echo "ASK"

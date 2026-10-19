#!/usr/bin/env bash
# churn.sh — rank files by git-log touch-count (change frequency) so a refactor aims at the hot
# spots. Pairs with the refactor-plan skill's Step 0. Dependency-free: git + coreutils only.
#
#   churn.sh [N] [since] [path]
#     N      max rows       (default 20)
#     since  git --since    (default '90.days.ago')
#     path   pathspec        (default '.')
#
#   ./bin/churn.sh                 # top 20 hottest files, last 90 days
#   ./bin/churn.sh 10 '1.year.ago' src/   # top 10 in src/ over the last year
#
# ponytail: churn ALONE (touch-count) — no complexity/LOC blend; that needs a per-language analyzer
# and is YAGNI here. `--name-only` also counts deleted/renamed paths — acceptable noise for a
# "where's the heat" heuristic. Paths with spaces would break the "<count> <path>" parse; repo
# paths have none, so no NUL-delimited rewrite.
set -euo pipefail

N="${1:-20}"
SINCE="${2:-90.days.ago}"
CHURN_PATH="${3:-.}"

#   The tail is `awk NR<=n`, NOT `head -n "$N"`: `head` closes the pipe after N lines, and on a
#   large repo (sort -rn output > the pipe buffer) that SIGPIPEs `sort`, which under `pipefail`
#   surfaces as exit 141 despite correct output. `awk` reads to EOF, so the exit stays 0.
#   Blank lines are dropped with `awk NF`, NOT `grep -v '^$'`: grep exits 1 when it matches nothing
#   (an empty window — no commits for the path/since), which under `set -e -o pipefail` would kill
#   the script with exit 1, breaking the "empty window -> empty output, exit 0" contract. awk exits 0.
git log --since="$SINCE" --format='' --name-only -- "$CHURN_PATH" \
  | awk 'NF' \
  | sort \
  | uniq -c \
  | sort -rn \
  | awk -v n="$N" 'NR<=n'

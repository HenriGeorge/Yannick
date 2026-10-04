#!/usr/bin/env bash
# list-skills.sh — enumerate available skills for /skill-reinvent's no-arg menu.
#
# Lists project `.claude/skills/*/SKILL.md` and user `~/.claude/skills/*/SKILL.md`, source-labelled.
# Dependency-free (find + basename only, mirrors bin/stamp-docs.sh's style); tolerant of either
# directory being absent (prints nothing for that source, never errors). Excludes any path with a
# `plugins` segment (find is unbounded-depth, mirroring skill-audit's scripts/audit.py, which uses
# Path.rglob) — a plugin's bundled skill is overwritten on update; never review or list it here.
#
# Usage: list-skills.sh [--root=DIR]   (default: enumerate BOTH ./.claude/skills and ~/.claude/skills)
set -euo pipefail

ROOT_OVERRIDE=""
for arg in "$@"; do
  case "$arg" in
    --root=*) ROOT_OVERRIDE="${arg#--root=}" ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  esac
done

is_plugin_path() {  # $1=path -> 0 if it has a `plugins` path segment
  case "/$1/" in
    */plugins/*) return 0 ;;
    *) return 1 ;;
  esac
}

list_dir() {  # $1=dir $2=label
  local dir="$1" label="$2"
  [ -d "$dir" ] || return 0
  find "$dir" -name 'SKILL.md' -type f 2>/dev/null | sort | while IFS= read -r f; do
    is_plugin_path "$f" && continue
    name="$(basename "$(dirname "$f")")"
    printf '%-30s %-8s %s\n' "$name" "$label" "$f"
  done
}

if [ -n "$ROOT_OVERRIDE" ]; then
  list_dir "$ROOT_OVERRIDE" "custom"
else
  list_dir "./.claude/skills" "project"
  list_dir "${HOME}/.claude/skills" "user"
fi

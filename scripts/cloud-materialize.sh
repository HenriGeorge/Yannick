#!/usr/bin/env bash
# Cloud-only SessionStart materialize: copies plugin tooling + rules/*.md into .claude/ so a cloud
# session (which sees only the repo git tree, no installed plugins) gets the same tooling a local
# plugin-marketplace session loads. Idempotent, fail-open per step — never hard-fails the session.
# Never touches .claude/settings.json.
#
# skills/agents/commands come from ALL plugins (third-party tooling must load in cloud too). HOOKS
# come ONLY from the first-party hook plugins (ct-hooks-*): only their scripts are wired
# by the committed .claude/settings.json hooks block, and copying every plugin's hooks/ would merge
# unrelated third-party manifests (each ships its own hooks/hooks.json) into .claude/hooks/ by
# basename — pointless (nothing reads them in cloud) and collision-prone.
set -u

[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

root="${CLAUDE_PROJECT_DIR:-$PWD}"

copy_step() {
  label="$1"; shift
  if ! "$@"; then
    echo "cloud-materialize: $label failed (continuing)"
  fi
}

# shellcheck disable=SC2329  # invoked indirectly via copy_step's "$@"
copy_glob_dirs() {
  # $1=glob-suffix under plugins/*/, $2=dest dir name under .claude/
  suffix="$1"; dest="$2"
  for src in "$root"/plugins/*/"$suffix"; do
    [ -d "$src" ] || continue
    mkdir -p "$root/.claude/$dest" || return 1
    cp -R "$src"/. "$root/.claude/$dest/" || return 1
  done
}

copy_step "skills" copy_glob_dirs skills skills
copy_step "agents" copy_glob_dirs agents agents
copy_step "commands" copy_glob_dirs commands commands

# shellcheck disable=SC2329  # invoked indirectly via copy_step's "$@"
copy_hooks() {
  # First-party hook plugins only (see header). Copy the whole hooks/ tree so _lib/ and sibling
  # modules the wired scripts import land alongside them.
  for src in "$root"/plugins/ct-hooks-*/hooks; do
    [ -d "$src" ] || continue
    mkdir -p "$root/.claude/hooks" || return 1
    cp -R "$src"/. "$root/.claude/hooks/" || return 1
  done
}
copy_step "hooks" copy_hooks

# shellcheck disable=SC2329  # invoked indirectly via copy_step's "$@"
copy_rules() {
  [ -d "$root/rules" ] || return 0
  # In the source repo .claude/rules is a symlink → ../rules, already exposing the rules in cloud via
  # the git tree; copying rules/*.md onto themselves through the symlink just errors noisily. Skip it.
  # A fleet repo has no such symlink, so the copy materializes the rules there.
  [ -L "$root/.claude/rules" ] && return 0
  mkdir -p "$root/.claude/rules" || return 1
  for f in "$root"/rules/*.md; do
    [ -e "$f" ] || continue
    cp "$f" "$root/.claude/rules/" || return 1
  done
}
copy_step "rules" copy_rules

exit 0

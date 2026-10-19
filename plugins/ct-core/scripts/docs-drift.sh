#!/usr/bin/env bash
# docs-drift.sh — verify the narrative docs against the live codebase and report drift.
#
# Re-runnable "keep-docs-current" loop: each run re-checks the CURRENT checkout, so run it
# after a `git pull`/rebase to verify against the latest code. Three deterministic detectors
# (fast, no model) plus an optional local-ollama "detect + draft" pass on the flagged set.
#
#   Deterministic (always):
#     (1)  STALE-REF        a doc cites `bin/<x>` that no longer exists (advisory)
#     (1b) REMOVED-HOOK REF a doc cites a `<name>_gate`/`_nudge` backed by no hook/test — HARD FAIL
#                           (exit 3), so the next hook removal cannot leave the docs behind (#1393)
#     (2)  UNDOCUMENTED     a code surface (hook / bin script / command) named in NO narrative doc = "new"
#     (3)  STAMP-STALE      reuse `bin/stamp-docs.sh --check-fresh` (doc edited without restamping)
#   Exit: 0 normally, 2 on a usage/bad-ref error, 3 when a removed-hook ref (1b) is found. Classes
#   (1)/(2)/(3) are advisory and never change the exit code.
#   Ollama (opt-in, --draft): for each flagged doc, feed the doc + the relevant code to an ollama
#     model (default glm-5.2:cloud — PAID remote) and write a corrected passage to .docs-drift/ for
#     a human to approve. NEVER commits. Set DOCS_DRIFT_MODEL=qwen3:30b for a local free lane.
#
# Deps: git, grep, bash. Ollama only for --draft (degrades gracefully if absent).
# Usage: bin/docs-drift.sh [--since <ref>] [--draft] [--model <name>] [--json] [--root <dir>]
#   --since <ref>  diff-scope: report ONLY drift introduced since <ref> (docs changed + surfaces
#                  added vs <ref>...HEAD). This is how /pr-open fires it — merge-base as <ref> — so a
#                  PR warns on its OWN new drift, never the pre-existing backlog.
# No `set -e`: linear report generator over greps that legitimately exit non-zero (no-match) and
# reads ending without a trailing newline. No `set -u`: the surface arrays (hooks/bin/commands) are
# legitimately empty in a minimal repo, and empty-array expansion trips -u under bash 3.2. pipefail
# stays to catch real failures in the collection pipelines.
set -o pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
# Default = glm-5.2:cloud (Ollama Cloud, PAID + remote — drafts leave the machine). Override with a
# local free lane for private/offline drafting: DOCS_DRIFT_MODEL=qwen3:30b
MODEL="${DOCS_DRIFT_MODEL:-glm-5.2:cloud}"
DRAFT=0
JSON=0
SINCE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --draft)  DRAFT=1 ;;
    --model)  MODEL="$2"; shift ;;
    --json)   JSON=1 ;;
    --root)   ROOT="$2"; shift ;;
    --since)  SINCE="$2"; shift ;;   # diff-scope: only drift in files changed since <ref>
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done
cd "$ROOT" || exit 1

# bash 3.2 (macOS default) has no `mapfile` — portable array fill:
fill() { local __n="$1"; shift; eval "$__n=()"; local __l; while IFS= read -r __l; do eval "$__n+=(\"\$__l\")"; done; }

# --- COLLECT: LIVING narrative docs only ---
# We check docs that describe how the system works NOW. Point-in-time records — lessons logs,
# decision/ADR records, and dated plans/specs — legitimately cite tools later removed or renamed;
# "correcting" them would rewrite history, so they are excluded from drift checking.
fill DOCS < <(
  { git ls-files '*.md' 2>/dev/null || find . -name '*.md' -not -path './.git/*'; } \
  | grep -E '(^|/)(docs/|\.claude/rules/|README\.md|plugins/[^/]+/docs/)' \
  | grep -vE '(^|/)(archive/|node_modules/|\.claude/worktrees/)' \
  | grep -vE '(^|/)(lessons\.md|lessons-archive\.md|decisions/|superpowers/(plans|specs)/)' \
  | sed 's#^\./##' \
  | sort -u
)

# --- COLLECT: code surfaces (the things docs describe) ---
fill HOOKS < <(for f in plugins/ct-hooks-py/hooks/*.py; do [ -e "$f" ] && basename "$f" .py; done | sort -u)
fill BINS  < <(find bin -maxdepth 1 -type f 2>/dev/null | sort -u)
fill CMDS  < <(for f in plugins/*/commands/*.md; do [ -e "$f" ] && basename "$f" .md; done | sort -u)
# Every hook name, captured BEFORE --since narrows HOOKS to the added ones: a doc citing an existing
# hook (e.g. `_telemetry_gate`) is valid whether or not that hook changed in this diff.
valid_hooks=" ${HOOKS[*]} "

# --- DIFF-SCOPE (--since): restrict to drift THIS change introduced (Q4a) ---
# Docs → only those changed since <ref>. Surfaces → only those ADDED since <ref> (a pre-existing
# surface that was always undocumented is backlog, not new drift). Needs git; no-op without --since.
if [ -n "$SINCE" ]; then
  # A bad ref makes both git diffs exit 128 silently → empty CHANGED → "0 drift everywhere",
  # indistinguishable from a genuinely clean diff. Fail loud instead (silent-failure-hunter).
  git rev-parse --verify -q "$SINCE^{commit}" >/dev/null 2>&1 || {
    echo "docs-drift: bad --since ref: $SINCE" >&2; exit 2; }
  CHANGED="$(git diff --name-only "$SINCE"...HEAD 2>/dev/null; git diff --name-only "$SINCE" 2>/dev/null)"
  ADDED="$(git diff --name-only --diff-filter=A "$SINCE"...HEAD 2>/dev/null)"
  # here-strings, NOT `printf | grep -q`: under pipefail, grep -q closes the pipe on match and
  # SIGPIPEs the producer → pipeline reports non-zero even on a hit → a changed doc dropped from the
  # scan (false-negative on a >64KB diff). Same trap doc_has avoids. (code-reviewer)
  in_set() { grep -qxF "$1" <<<"$2"; }
  fill DOCS  < <(for d in ${DOCS[@]+"${DOCS[@]}"};  do in_set "$d" "$CHANGED" && echo "$d"; done)
  fill HOOKS < <(for h in ${HOOKS[@]+"${HOOKS[@]}"}; do in_set "plugins/ct-hooks-py/hooks/$h.py" "$ADDED" && echo "$h"; done)
  fill BINS  < <(for b in ${BINS[@]+"${BINS[@]}"};  do in_set "$b" "$ADDED" && echo "$b"; done)
  fill CMDS  < <(for c in ${CMDS[@]+"${CMDS[@]}"};  do grep -qE "(^|/)commands/$c\.md$" <<<"$ADDED" && echo "$c"; done)
fi

# /dev/null sentinel guarantees ≥1 file arg so cat/grep never fall back to reading stdin (would hang
# when --since filters DOCS to empty).
DOC_BLOB="$(cat "${DOCS[@]}" /dev/null 2>/dev/null || true)"

stale_ref=()      # "doc:line: `ref` — no such <kind>" (bin path; advisory)
stale_hook_ref=() # "doc:line: `name_gate` — no matching hook" (removed hook; HARD FAIL, exit 3)
undocumented=()   # "<kind> <name> — cited in no doc"
flagged_docs=()   # docs to hand to ollama

# --- (1) STALE-REF: bin/<x> paths cited that don't exist ---
while IFS= read -r hit; do
  [ -z "$hit" ] && continue
  f="${hit%%:*}"; rest="${hit#*:}"; ln="${rest%%:*}"
  ref="$(printf '%s' "$rest" | grep -oE 'bin/[A-Za-z0-9._-]+' | head -1)"
  [ -z "$ref" ] && continue
  # skip system/venv paths caught by the bare `bin/` match (/bin/bash, source bin/activate, ...)
  case "$ref" in bin/bash|bin/sh|bin/env|bin/activate|bin/python*|bin/pip*|bin/git|bin/gh) continue ;; esac
  if [ ! -e "$ref" ]; then
    stale_ref+=("$f:$ln: \`$ref\` — no such file")
    flagged_docs+=("$f")
  fi
done < <(grep -arEno 'bin/[A-Za-z0-9._-]+' "${DOCS[@]}" /dev/null 2>/dev/null || true)

# --- (1b) REMOVED-HOOK REF: `<name>_gate`/`_nudge` cited but backed by no hook OR test — HARD FAIL (exit 3) ---
# Only _gate/_nudge (precise hook-name suffixes); `_hook` is too prose-prone ("session hook").
# Valid when the token is a substring of a real hook name, OR hooks/<name>.py exists,
# OR tests/<name>.sh exists (test files are legitimately named e.g. test_pr_gate).
# Extract the MAXIMAL identifier (trailing word-chars included), then keep only tokens that END in
# exactly _gate/_nudge — else `_gate` greedily truncates longer names (test_build_loop_gate*s*,
# test_session_start_gate*0*, test_gate*_executor*) into phantom stale-refs.
# This gate is load-bearing (drives exit 3), so capture the scan grep's rc and surface a real error
# (rc>1) instead of letting `|| true` mask it into silently-empty results — a dropped gate with no
# trace. Mirrors the STAMP-STALE detector's hardening below. rc=1 (no match) is the normal clean case.
hook_scan="$(grep -arEno '[a-z][a-z0-9_]*_(gate|nudge)[a-z0-9_]*' "${DOCS[@]}" /dev/null 2>/dev/null)"; hook_scan_rc=$?
[ "$hook_scan_rc" -gt 1 ] && echo "docs-drift: removed-hook-ref scan grep failed (rc=$hook_scan_rc) — the exit-3 gate may be incomplete" >&2
while IFS= read -r hit; do
  [ -z "$hit" ] && continue
  f="${hit%%:*}"; rest="${hit#*:}"; ln="${rest%%:*}"
  ref="$(printf '%s' "$rest" | grep -oE '[a-z][a-z0-9_]*_(gate|nudge)[a-z0-9_]*' | head -1)"
  [ -z "$ref" ] && continue
  case "$ref" in *_gate|*_nudge) : ;; *) continue ;; esac  # exact suffix only — not _gates/_gate0/_gate_executor
  case "$valid_hooks" in *"$ref"*) continue ;; esac       # substring of a real hook — fine
  [ -e "plugins/ct-hooks-py/hooks/$ref.py" ] && continue
  [ -e "tests/$ref.sh" ] && continue
  [ -e "tests/test_$ref.sh" ] && continue   # a post_nudges MODULE (no own hook file) proven by tests/test_<name>.sh
  stale_hook_ref+=("$f:$ln: \`$ref\` — no matching hook or tests/*.sh")
  flagged_docs+=("$f")
done <<< "$hook_scan"

# --- (2) UNDOCUMENTED: code surface whose name appears in no narrative doc ---
# Pure-bash substring test — NOT `grep -q` in a pipe: grep -q exits on first match, and with
# `pipefail` the SIGPIPE'd producer makes the pipeline report failure even on a hit (false "undocumented").
doc_has() { case "$DOC_BLOB" in *"$1"*) return 0 ;; *) return 1 ;; esac; }
for h in "${HOOKS[@]}"; do [ -z "$h" ] && continue; doc_has "$h" || undocumented+=("hook $h"); done
for b in "${BINS[@]}";  do [ -z "$b" ] && continue; doc_has "$(basename "$b")" || undocumented+=("bin $b"); done
for c in "${CMDS[@]}";  do [ -z "$c" ] && continue; doc_has "$c" || undocumented+=("command /$c"); done

# --- (3) STAMP-STALE: reuse the existing freshness gate ---
# Separate the checker's exit from the grep so a crash can't masquerade as "no stale docs"
# (silent-failure-hunter): capture output, then grep it; emit a breadcrumb if the checker errored.
stamp_stale=""
if [ -x bin/stamp-docs.sh ]; then
  stamp_out="$(bin/stamp-docs.sh --check-fresh 2>&1)"; stamp_rc=$?
  # --check-fresh exits 1 when it FINDS stale docs (rc 1 + output) — that's success, not a crash.
  if [ "$stamp_rc" -gt 1 ]; then
    echo "docs-drift: stamp-docs.sh --check-fresh failed (rc=$stamp_rc) — stamp-staleness check skipped" >&2
  else
    stamp_stale="$(printf '%s\n' "$stamp_out" | grep -iE 'stale|older|future' || true)"
    # rc=1 with no stale/future line = the checker aborted, not "nothing stale" — never "(none)".
    if [ "$stamp_rc" -eq 1 ] && [ -z "$stamp_stale" ]; then
      stamp_stale="check NOT run cleanly: $stamp_out"
      echo "docs-drift: stamp-docs.sh --check-fresh $stamp_stale" >&2
    fi
  fi
fi

# --- dedup flagged docs ---
fill flagged_docs < <(printf '%s\n' "${flagged_docs[@]}" | sort -u | grep -v '^$' || true)

# --- REPORT ---
emit_text() {
  echo "== docs-drift report =="
  echo "docs scanned: ${#DOCS[@]} | hooks: ${#HOOKS[@]} | bin: ${#BINS[@]} | commands: ${#CMDS[@]}"
  echo
  echo "(1) STALE-REF (doc cites code that no longer exists): ${#stale_ref[@]}"
  [ ${#stale_ref[@]} -gt 0 ] && printf '   %s\n' "${stale_ref[@]}"
  echo
  echo "(1b) REMOVED-HOOK REF (doc cites a _gate/_nudge hook that no longer exists — FAILS, exit 3): ${#stale_hook_ref[@]}"
  [ ${#stale_hook_ref[@]} -gt 0 ] && printf '   %s\n' "${stale_hook_ref[@]}"
  echo
  echo "(2) UNDOCUMENTED (code surface in no narrative doc — candidate 'new'): ${#undocumented[@]}"
  [ ${#undocumented[@]} -gt 0 ] && printf '   %s\n' "${undocumented[@]}"
  echo
  echo "(3) STAMP-STALE (edited without restamping, via stamp-docs.sh --check-fresh):"
  if [ -n "$stamp_stale" ]; then printf '   %s\n' "$stamp_stale"; else echo "   (none)"; fi
}

if [ "$JSON" -eq 1 ]; then
  j() { printf '%s\n' "$@" | grep -v '^$' | sed 's/"/\\"/g;s/.*/"&"/' | paste -sd, -; }
  printf '{"stale_ref":[%s],"stale_hook_ref":[%s],"undocumented":[%s],"flagged_docs":[%s]}\n' \
    "$(j "${stale_ref[@]}")" "$(j "${stale_hook_ref[@]}")" "$(j "${undocumented[@]}")" "$(j "${flagged_docs[@]}")"
else
  emit_text
fi

# --- EXIT CODE: a removed-hook ref is a HARD failure (exit 3) so the next hook removal cannot
# leave the docs behind; bin-path / stamp / undocumented stay advisory (exit 0). #1393 ---
FAIL_RC=0
[ ${#stale_hook_ref[@]} -gt 0 ] && FAIL_RC=3

# --- OLLAMA detect + draft (opt-in) ---
if [ "$DRAFT" -eq 1 ]; then
  if ! command -v ollama >/dev/null 2>&1; then
    echo; echo "--draft: ollama not on PATH — skipping draft pass (deterministic report stands)." >&2
    exit "$FAIL_RC"
  fi
  mkdir -p .docs-drift
  echo; echo "== ollama detect+draft ($MODEL) → .docs-drift/ =="
  for f in "${flagged_docs[@]}"; do
    [ -z "$f" ] && continue
    out=".docs-drift/$(printf '%s' "$f" | tr '/' '_').draft.md"
    refs="$(grep -oE 'bin/[A-Za-z0-9._-]+|[a-z][a-z0-9_]*(_gate|_nudge|_hook)' "$f" 2>/dev/null | sort -u)"
    code=""
    for r in $refs; do
      p=""; [ -e "$r" ] && p="$r"; [ -e "plugins/ct-hooks-py/hooks/$r.py" ] && p="plugins/ct-hooks-py/hooks/$r.py"
      [ -n "$p" ] && code="$code
### $p
$(head -80 "$p" 2>/dev/null)"
    done
    prompt="You verify documentation against code. Below is a doc file and the code it references.
List each specific claim in the doc that no longer matches the code (stale), and each code behavior
the doc fails to mention (missing). Then output a corrected version of ONLY the affected passages.
Be precise; if the doc is actually accurate, say 'NO DRIFT'. Do not invent behavior not in the code.

===== DOC: $f =====
$(cat "$f")

===== REFERENCED CODE =====
$code"
    echo "  drafting $f → $out"
    # ollama streams a live-redraw display even when piped; strip ANSI escapes + CR so the draft is clean markdown.
    if ! printf '%s' "$prompt" | ollama run "$MODEL" 2>/dev/null \
         | perl -pe 's/\x1b\[[0-9;]*[A-Za-z]//g; s/\r//g' > "$out"; then
      echo "  (model call failed for $f)" >&2
    fi
  done
  echo "Drafts written to .docs-drift/ — review, then apply by hand. Nothing committed."
fi

exit "$FAIL_RC"

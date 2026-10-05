#!/usr/bin/env bash
# stamp-docs.sh — enforce/backfill the `Last updated: YYYY-MM-DD HH:MM` doc-timestamp convention
# (issue #97; time-of-day #146-T1, rules/doc-conventions.md). Dependency-free: bash + coreutils +
# git only.
#
# Usage:
#   stamp-docs.sh [--check|--check-time|--check-fresh|--upgrade] [paths...]
#   stamp-docs.sh --touch FILE...
#
#   --check      Report every *.md doc missing a `Last updated:` stamp (LENIENT — presence-only, a
#                date-only stamp still counts as stamped); exit 1 if any are missing, 0 otherwise.
#                Writes nothing — use it as a CI/pre-commit gate that stays compatible with
#                downstream scaffolds that may not have re-stamped with time-of-day yet.
#   --check-time STRICT opt-in: report every *.md doc whose stamp lacks the `HH:MM` payload —
#                missing entirely, OR present but date-only; exit 1 if any. Writes nothing.
#   --check-fresh STALENESS opt-in (issue #449): report every *.md doc whose date+time stamp is
#                OLDER than the file's last CONTENT commit — i.e. the doc was edited without
#                refreshing its stamp. Commits that changed ONLY the `Last updated:` line are
#                skipped, so a stamp-only re-commit never marks a doc "stale vs itself". Date-only
#                stamps are out of scope here (use --check-time); untracked docs are skipped. Exit 1
#                if any stale. ALSO flags a FUTURE stamp — later than now + 5 min (#930: agents
#                hand-typing a plausible time instead of running `date`) — UNTRACKED docs included, since
#                that needs no history; date-only stamps are still skipped. Writes
#                nothing. Template-repo opt-in — NOT wired into scaffold CI, which legitimately
#                carries backfilled/propagated stamps newer than content.
#   --touch FILE...  Rewrite each given doc's EXISTING stamp to now (`date '+%Y-%m-%d %H:%M'`),
#                preserving its style (bare, blockquote, emphasis, bold-list). Use this instead of
#                hand-typing a time. A file with no stamp is an error (exit 1, left unchanged);
#                no FILE at all is an error (exit 2) — it never defaults to every doc.
#   --upgrade    Rewrite a DATE-ONLY `Last updated: YYYY-MM-DD` stamp to `YYYY-MM-DD HH:MM` IN
#                PLACE, preserving the bare/blockquote style. The bold-list ADR form
#                (`- **Last updated:** YYYY-MM-DD`) is intentionally left alone — hand-update those.
#                Idempotent: a stamp that already carries a time is untouched.
#   (default)    Backfill: insert a `Last updated: <date+time>` line into each doc that lacks a
#                stamp at all, placed right after the file's first `# heading` (or at the top if
#                there is none). Never touches a doc that already has ANY stamp (presence-only
#                idempotency — no churn; use --upgrade to add time to an existing date-only stamp).
#
#   paths...  Files and/or directories to scan. A directory is walked recursively for *.md.
#             With no paths, defaults to `docs` and `rules` under the current directory.
#
# The stamped date+time is the file's LAST COMMIT datetime
# (`git log -1 --date=format:'%Y-%m-%d %H:%M' --format=%cd -- <file>`, 24h, no seconds/timezone —
# commit-local time), so a backfill reflects real history rather than "today". Untracked files (no
# commit yet) fall back to the filesystem mtime. Already-stamped docs are left untouched by the
# default write pass (idempotent).
set -euo pipefail

# Recognizes every stamp style: bare (`Last updated: ...`), blockquote (`> Last updated: ...`), the
# bold-list ADR form (`- **Last updated:** ...`, #146-T1), and markdown-emphasis-wrapped forms
# (`_Last updated: ..._`, `*...*`, `__...__`, #124). The leading-prefix group allows an optional
# blockquote `>` and/or list marker `-`, then any run of emphasis chars `_`/`*` (single or paired)
# before the literal `Last updated:` phrase — so an italicized/bolded hand-written stamp is NOT
# false-flagged as missing and never gets a SECOND (canonical) stamp on backfill (#124 edge case 2).
# It still requires the literal `Last updated:` phrase, so a non-stamp line can't match by accident.
STAMP_RE='^[[:space:]]*(>[[:space:]]*)?(-[[:space:]]*)?[_*]*[[:space:]]*[Ll]ast [Uu]pdated:'
# A stamp line that ALREADY carries the HH:MM payload, in any of the three styles above.
STAMP_TIME_RE='[Ll]ast [Uu]pdated:[[:space:]]*\**[[:space:]]*[0-9]{4}-[0-9]{2}-[0-9]{2}[[:space:]]+[0-9]{2}:[0-9]{2}'
# A DATE-ONLY bare/blockquote stamp (no time yet) — deliberately excludes the bold-list form (that
# form never starts with `>` or nothing; it starts with `- **`, which this pattern does not match).
STAMP_DATEONLY_BQ_RE='^[[:space:]]*>?[[:space:]]*[Ll]ast [Uu]pdated:[[:space:]]*[0-9]{4}-[0-9]{2}-[0-9]{2}[[:space:]]*$'

usage() { sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; }

check_only=0
check_time_only=0
check_fresh_only=0
upgrade_only=0
touch_only=0
paths=()
for arg in "$@"; do
  case "$arg" in
    --check) check_only=1 ;;
    --check-time) check_time_only=1 ;;
    --check-fresh) check_fresh_only=1 ;;
    --upgrade) upgrade_only=1 ;;
    --touch) touch_only=1 ;;
    -h|--help) usage; exit 0 ;;
    --) ;;
    -*) printf 'stamp-docs.sh: unknown option: %s\n' "$arg" >&2; exit 2 ;;
    *) paths+=("$arg") ;;
  esac
done

# --touch: explicit files only — rewrite the first stamp's date[+time] value to now, keeping every
# character around it (prefix `>`/`- **`/`_`, suffix `_`/`**`). Runs before the docs/rules default
# so a bare `--touch` can never restamp the whole tree.
if [ "$touch_only" -eq 1 ]; then
  [ "${#paths[@]}" -gt 0 ] || { printf 'stamp-docs.sh: --touch needs at least one FILE\n' >&2; exit 2; }
  now="$(date '+%Y-%m-%d %H:%M')"
  rc=0
  for f in "${paths[@]}"; do
    ln="$( { grep -anE "$STAMP_RE" "$f" 2>/dev/null || true; } | head -1 | cut -d: -f1)"
    if [ ! -f "$f" ] || [ -z "$ln" ]; then
      printf 'stamp-docs.sh: --touch: %s has no "Last updated:" stamp (not a file, or unstamped) — add one first\n' "$f" >&2
      rc=1; continue
    fi
    tmp="$(mktemp "${TMPDIR:-/tmp}/stamp-touch.XXXXXX")"
    sed -E "${ln}s/([Ll]ast [Uu]pdated:[^0-9]*)[0-9]{4}-[0-9]{2}-[0-9]{2}([[:space:]]+[0-9]{2}:[0-9]{2})?/\\1${now}/" "$f" > "$tmp"
    if ! sed -n "${ln}p" "$tmp" | grep -qF "$now"; then
      rm -f "$tmp"
      printf 'stamp-docs.sh: --touch: %s:%s stamp carries no YYYY-MM-DD value to rewrite\n' "$f" "$ln" >&2
      rc=1; continue
    fi
    cat "$tmp" > "$f"; rm -f "$tmp"   # cat-over keeps the doc's own file mode (mktemp is 0600)
    printf 'touched %s -> %s\n' "$f" "$now"
  done
  exit "$rc"
fi

[ "${#paths[@]}" -eq 0 ] && paths=(docs rules)

# --- collect target *.md files (files as-is; directories walked recursively) --------------------
docs=()
for p in "${paths[@]}"; do
  if [ -f "$p" ]; then
    case "$p" in *.md) docs+=("$p") ;; esac
  elif [ -d "$p" ]; then
    while IFS= read -r f; do docs+=("$f"); done < <(find "$p" -type f -name '*.md' | sort)
  fi
done

has_stamp() { grep -qE "$STAMP_RE" "$1"; }
has_time_stamp() { grep -qE "$STAMP_TIME_RE" "$1"; }

# Last-commit DATE+TIME for a tracked file (`YYYY-MM-DD HH:MM`, 24h, commit-local time, no
# seconds/TZ); empty if untracked / not a repo.
git_date() { git log -1 --date=format:'%Y-%m-%d %H:%M' --format=%cd -- "$1" 2>/dev/null || true; }

# The `YYYY-MM-DD HH:MM` datetime carried by a doc's FIRST time-bearing stamp, in any style; empty
# if the doc has no stamp or only a date-only one (freshness needs a time to compare).
stamp_datetime() {
  # -a: a doc with a stray NUL byte is "binary" to grep, whose -o then prints nothing; under
  # pipefail + set -e that silently aborted the whole --check-fresh run with rc=1 (#930).
  grep -aoE "$STAMP_TIME_RE" "$1" 2>/dev/null | head -1 \
    | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}[[:space:]]+[0-9]{2}:[0-9]{2}' | head -1 \
    | awk '{$1=$1; print}' \
    || true   # SIGPIPE from `head -1` under pipefail must not abort the caller; empty = skip
  # (awk collapses any multi-space date/time gap to a single space, no trailing)
}

# Datetime (`YYYY-MM-DD HH:MM`) of the last commit that changed CONTENT of a file — i.e. skipping
# commits whose patch for the file touched ONLY the `Last updated:` stamp line. Walk the file's
# commits newest-first; for each, strip the diff's +/- markers and check whether any changed line is
# NOT a stamp line — the first such commit is the last content commit. If every commit is stamp-only
# (shouldn't happen — the creation commit adds body), fall back to the plain last-commit date.
# ponytail: O(commits x git-show) per file — fine for an opt-in advisory gate at repo scale.
last_content_commit_date() {
  local f="$1" h
  while IFS= read -r h; do
    # Emit only HUNK +/- content (marker stripped) and test whether any line is NOT a stamp. The
    # awk keys off the first `@@` so the diff's file headers (`diff --git`, `index`, `--- a/f`,
    # `+++ b/f`) — all of which precede any hunk — are dropped structurally, not by a fragile
    # `^---` grep that also eats a REMOVED content line reading `---`/`-- flag` (shown in the diff
    # as `----`/`--- flag`) and would misclassify a delete-only commit as stamp-only (#453 review).
    # -c color.ui=false: color.ui=always (global) colorizes `git show` even to a pipe, breaking the
    # awk +/- hunk scan below. Force it off.
    if git -c color.ui=false show --format= "$h" -- "$f" 2>/dev/null \
         | awk '/^@@/ { inhunk=1; next } inhunk && /^[+-]/ { sub(/^./, ""); print }' \
         | grep -qvE "$STAMP_RE"; then
      git log -1 --date=format:'%Y-%m-%d %H:%M' --format=%cd "$h" 2>/dev/null
      return 0
    fi
  done < <(git log --format=%H -- "$f" 2>/dev/null)
  git_date "$f"
}

# Filesystem mtime as `YYYY-MM-DD HH:MM` — GNU (`-d @`) and BSD/macOS (`-r`) date both handled.
mtime_date() {
  local f="$1" epoch
  # GNU form FIRST. `-f` is "format" to BSD stat but `--file-system` to GNU stat, so on Linux
  # `stat -f %m` SUCCEEDS with filesystem info instead of failing — the BSD-first order only
  # recovered here by luck (the subsequent `date -r` chokes on that text and falls through). The
  # same inversion was a hard failure in propagate.sh's _backup_epoch, so don't leave it latent.
  # BSD stat rejects `-c` outright, which makes the fallback a real one in both directions.
  epoch="$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null)"
  case "$epoch" in ''|*[!0-9]*) epoch="" ;; esac
  if [ -n "$epoch" ]; then
    date -d "@$epoch" +'%F %H:%M' 2>/dev/null && return   # GNU
    date -r "$epoch"  +'%F %H:%M' 2>/dev/null && return   # BSD/macOS
  fi
  # Both stat forms failed (TOCTOU: file vanished between `find` and `stat`, or a platform with
  # neither `-c %Y` nor `-f %m`). Emit a breadcrumb so the caller's freshness stamp is observably
  # fabricated, not silently lied about. Return 0 (not non-zero): a stamp failure must not abort
  # the doc walk under `set -e` — a wrong stamp is better than no stamp run at all.
  printf 'stamp-docs.sh: could not stat %s, using current time as mtime\n' "$f" >&2
  date +'%F %H:%M'  # last-ditch: now
}

doc_date() {
  local f="$1" d
  d="$(git_date "$f")"
  [ -n "$d" ] || d="$(mtime_date "$f")"
  printf '%s' "$d"
}

# Insert `Last updated: <date>` after the first real markdown heading, keeping a blank line so it
# reads as its own block. W3 fix: a leading `---`…`---` YAML front-matter fence is skipped first —
# a `#` line INSIDE front-matter is a YAML comment, not a heading, and the stamp must never land in
# it. If there's no heading, the stamp goes right after the front-matter fence, else at the top.
insert_stamp() {
  local f="$1" date="$2" tmp
  tmp="$(mktemp "${TMPDIR:-/tmp}/stamp.XXXXXX")"
  # Primary pass: skip front-matter, then insert after the first `#`..`######` heading.
  awk -v stamp="Last updated: $date" '
    BEGIN { infm = 0; fmdone = 0; ins = 0 }
    NR == 1 && $0 == "---" { infm = 1; print; next }
    infm == 1 && fmdone == 0 { print; if ($0 == "---") { fmdone = 1 } ; next }
    ins == 0 && /^#+[[:space:]]/ { print; print ""; print stamp; ins = 1; next }
    { print }
  ' "$f" > "$tmp"
  # Fallback: no markdown heading found — insert after the front-matter fence, else prepend.
  if ! grep -qF "Last updated: $date" "$tmp"; then
    awk -v stamp="Last updated: $date" '
      BEGIN { infm = 0; fmdone = 0; ins = 0 }
      NR == 1 && $0 == "---" { infm = 1; print; next }
      infm == 1 && fmdone == 0 {
        print
        if ($0 == "---") { fmdone = 1; print ""; print stamp; ins = 1 }
        next
      }
      ins == 0 { print stamp; print ""; ins = 1; print; next }
      { print }
    ' "$f" > "$tmp"
  fi
  mv "$tmp" "$f"
}

# Rewrite a DATE-ONLY bare/blockquote stamp to date+time IN PLACE, preserving the line's PREFIX
# (leading whitespace, an optional `>` prefix) but REPLACING the entire date value with the fresh
# `doc_date` — date AND time sourced from the SAME commit. Never append a new time to the OLD date
# already on the line: if that date has drifted from the file's actual last-commit date (the doc
# was re-committed since the stamp was last touched), appending would weld together a date and a
# time from two different commits — a "2020-01-01 10:30" stamp that never actually occurred
# (adversarial re-review CRITICAL). The bold-list ADR form never matches STAMP_DATEONLY_BQ_RE (it
# starts with `- **`, not `>`/nothing), so it's untouched by construction — no separate exclusion
# logic needed. Returns 0 if a line was upgraded, 1 if nothing matched (already has a time, or has
# no stamp at all — both are "no-op", not errors).
upgrade_doc() {
  local f="$1" ln full tmp
  # -a: on a NUL-containing doc, BSD grep prints "Binary file … matches" — a non-numeric "line".
  ln="$(grep -anE "$STAMP_DATEONLY_BQ_RE" "$f" | head -1 | cut -d: -f1)"
  [ -n "$ln" ] || return 1
  full="$(doc_date "$f")"     # "YYYY-MM-DD HH:MM" -- date+time from the SAME commit
  tmp="$(mktemp "${TMPDIR:-/tmp}/stamp-upg.XXXXXX")"
  awk -v n="$ln" -v full="$full" '
    NR == n {
      idx = match($0, /[Ll]ast [Uu]pdated:/)
      prefix = substr($0, 1, idx + RLENGTH - 1)
      print prefix " " full
      next
    }
    { print }
  ' "$f" > "$tmp"
  mv "$tmp" "$f"
  return 0
}

if [ "$check_time_only" -eq 1 ]; then
  missing_time=()
  # `${arr[@]+"${arr[@]}"}` — iterate safely when the array is EMPTY. Under `set -u` on bash 3.2
  # (macOS default), a bare `"${arr[@]}"` on an empty array is an "unbound variable" error, which
  # bites when a target set has no docs (or, for `missing` below, when every doc is already stamped
  # — the common fleet case a propagate re-stamp hits). The `+` form expands to nothing when unset.
  for f in ${docs[@]+"${docs[@]}"}; do
    has_time_stamp "$f" && continue
    missing_time+=("$f")
  done
  if [ "${#missing_time[@]}" -gt 0 ]; then
    printf 'Missing time-of-day ("HH:MM") in "Last updated:" stamp:\n' >&2
    for f in "${missing_time[@]}"; do printf '  %s\n' "$f"; done
    exit 1
  fi
  printf 'All %d docs carry a date+time "Last updated:" stamp.\n' "${#docs[@]}"
  exit 0
fi

if [ "$check_fresh_only" -eq 1 ]; then
  # Freshness is measured against commit history — no repo, nothing to measure. Fail LOUD rather
  # than silently skip every doc and print a false "all fresh" (silent-failure-hunter, #453).
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    printf 'stamp-docs.sh: --check-fresh needs a git repo (freshness is measured against commit history)\n' >&2
    exit 2
  fi
  stale=()
  future=()
  unverified=0
  # A stamp later than now + 5 min was hand-typed, not taken from `date` (#930). The tolerance
  # absorbs minor clock skew. GNU `-d` and BSD `-v` both handled.
  now="$(date '+%Y-%m-%d %H:%M')"
  limit="$(date -d '+5 min' '+%Y-%m-%d %H:%M' 2>/dev/null || date -v+5M '+%Y-%m-%d %H:%M' 2>/dev/null)" \
    || { echo 'stamp-docs.sh: cannot compute now+5min (date lacks -d/-v)' >&2; exit 2; }
  for f in ${docs[@]+"${docs[@]}"}; do
    has_time_stamp "$f" || continue          # only a date+time stamp is freshness-checkable
    s="$(stamp_datetime "$f")"; [ -n "$s" ] || continue
    # The future check needs no history, so it runs BEFORE the untracked skip: a brand-new
    # agent-written doc is exactly where a hand-typed time lands (#930).
    if [[ "$s" > "$limit" ]]; then
      future+=("$f (stamp $s is in the future; now $now)")
    fi
    # An UNTRACKED doc has no history to compare against — a legitimate skip for STALENESS only.
    git ls-files --error-unmatch "$f" >/dev/null 2>&1 || continue
    c="$(last_content_commit_date "$f")"
    # A tracked doc with an empty date means git itself failed (git_date's fallback also returned
    # nothing) — count it and warn, so a swallowed git error never masquerades as FRESH.
    # ponytail: this is the only git-error surface left for a tracked file; a per-command status
    # check would be more code for the same signal.
    if [ -z "$c" ]; then
      printf 'stamp-docs.sh: --check-fresh: git returned no commit date for %s — cannot verify freshness\n' "$f" >&2
      unverified=$((unverified + 1)); continue
    fi
    # Minute-granularity lexicographic compare — the fixed-width `YYYY-MM-DD HH:MM` form sorts
    # chronologically as a string; a same-minute stamp is FRESH (>= content commit), only strictly
    # older is stale.
    if [[ "$s" < "$c" ]]; then
      stale+=("$f (stamp $s < last content commit $c)")
    fi
  done
  if [ "${#stale[@]}" -gt 0 ]; then
    printf 'STALE "Last updated:" stamp (older than the file'"'"'s last content commit):\n' >&2
    for f in "${stale[@]}"; do printf '  %s\n' "$f"; done
  fi
  if [ "${#future[@]}" -gt 0 ]; then
    printf 'FUTURE "Last updated:" stamp (later than now + 5 min; hand-typed? use stamp-docs.sh --touch):\n' >&2
    for f in "${future[@]}"; do printf '  %s\n' "$f"; done
  fi
  if [ "${#stale[@]}" -gt 0 ] || [ "${#future[@]}" -gt 0 ]; then exit 1; fi
  if [ "$unverified" -gt 0 ]; then
    printf 'stamp-docs.sh: --check-fresh: %d doc(s) could not be verified (git error, see above) — NOT an all-clear.\n' "$unverified" >&2
    exit 1
  fi
  printf 'All %d docs carry a FRESH "Last updated:" stamp.\n' "${#docs[@]}"
  exit 0
fi

if [ "$upgrade_only" -eq 1 ]; then
  upgraded=0
  for f in ${docs[@]+"${docs[@]}"}; do
    if upgrade_doc "$f"; then
      printf 'upgraded %s\n' "$f"
      upgraded=$((upgraded + 1))
    fi
  done
  printf 'Upgraded: %d docs (date-only -> date+time), %d unchanged.\n' "$upgraded" "$(( ${#docs[@]} - upgraded ))"
  exit 0
fi

missing=()
for f in ${docs[@]+"${docs[@]}"}; do
  has_stamp "$f" && continue
  missing+=("$f")
done

if [ "$check_only" -eq 1 ]; then
  if [ "${#missing[@]}" -gt 0 ]; then
    printf 'Missing "Last updated:" stamp:\n' >&2
    for f in "${missing[@]}"; do printf '  %s\n' "$f"; done
    exit 1
  fi
  printf 'All %d docs carry a "Last updated:" stamp.\n' "${#docs[@]}"
  exit 0
fi

stamped=0
for f in ${missing[@]+"${missing[@]}"}; do
  insert_stamp "$f" "$(doc_date "$f")"
  printf 'stamped %s\n' "$f"
  stamped=$((stamped + 1))
done
printf 'Done: %d stamped, %d already had a stamp.\n' "$stamped" "$(( ${#docs[@]} - stamped ))"

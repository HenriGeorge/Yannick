#!/usr/bin/env bash
# Cloud environment bootstrap (claude.ai cloud sessions, run once per fresh environment) —
# installs dependencies, pre-pulls Supabase images + Playwright browsers (web profile only), and
# stamps the lockfile hash the cloud_session SessionStart hook compares against on every later
# session start to decide whether a re-sync is needed. That hook is .claude/hooks/cloud_session.*
# in a vendored repo (CLOUD_VENDOR=1), else the hooks plugin's hooks/cloud_session.*.
#
# Every step is independent and fail-open: a missing/broken tool prints
# "cloud-setup: <step> failed (continuing)" and the script still exits 0 — a broken cloud tool
# must never block the session from starting. See docs/CLOUD.md.
set -uo pipefail  # deliberately NOT -e: each step below handles its own failure

cd "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)" || exit 0

_conf_val() { # <key> <file> → value (inline `# comment` + quotes stripped), empty if key/file absent
  [ -f "$2" ] || return 0
  sed -n "s/^$1=//p" "$2" | head -1 | sed -e 's/[[:space:]]*#.*$//' -e 's/^"\(.*\)"$/\1/'
}

SETUP="$(_conf_val SETUP .claude/worktrees.conf)"
# STACK_PROFILE (current schema) with a fallback to PROFILE= (older repos predate STACK_PROFILE).
PROFILE="$(_conf_val STACK_PROFILE .claude/worktrees.conf)"
[ -n "$PROFILE" ] || PROFILE="$(_conf_val PROFILE .claude/worktrees.conf)"

_cs_install_ok=1  # a failed install must not be stamped as synced (cloud_session would trust it)
case "$SETUP" in
  npm)         npm ci || { _cs_install_ok=0; echo "cloud-setup: npm ci failed (continuing)"; } ;;
  py-editable) uv sync || { _cs_install_ok=0; echo "cloud-setup: uv sync failed (continuing)"; } ;;
esac

if [ "$PROFILE" = "web" ]; then
  # Cloud images ship no supabase CLI. npm's `supabase` package fetches + checksum-verifies the
  # release binary; it refuses `-g`, so install into a prefix and link it onto PATH.
  if ! command -v supabase >/dev/null 2>&1 && ! command -v npm >/dev/null 2>&1; then
    echo "cloud-setup: supabase CLI not installed: npm not found on PATH ($PATH)"
  elif ! command -v supabase >/dev/null 2>&1; then
    _cs_cli="$HOME/.cache/cloud-setup/supabase-cli"
    _cs_bindir="${CLOUD_SETUP_BIN_DIR:-}"
    if [ -z "$_cs_bindir" ]; then
      if [ -w /usr/local/bin ]; then _cs_bindir=/usr/local/bin; else _cs_bindir="$HOME/.local/bin"; fi
    fi
    if _cs_log="$(npm install --no-save --no-audit --no-fund --prefix "$_cs_cli" supabase@^2 2>&1)" \
       && mkdir -p "$_cs_bindir" && ln -sf "$_cs_cli/node_modules/.bin/supabase" "$_cs_bindir/supabase"; then
      echo "cloud-setup: installed supabase CLI -> $_cs_bindir/supabase"
      PATH="$_cs_bindir:$PATH"
    else
      echo "cloud-setup: supabase CLI install failed (continuing): $(printf '%s\n' "$_cs_log" | grep -v 'complete log of this run' | tail -1)"
    fi
  fi
  if command -v supabase >/dev/null 2>&1; then
    _cs_services="$(supabase services 2>/dev/null)"
    if [ $? -ne 0 ]; then
      echo "cloud-setup: supabase services failed (continuing)"
    elif command -v docker >/dev/null 2>&1; then
      # Pre-pull every non-disabled image in the background so none of this blocks session start.
      for _cs_img in $(printf '%s\n' "$_cs_services" | awk '!/disabled/ {print $1}'); do
        [ -n "$_cs_img" ] && docker pull "$_cs_img" >/dev/null 2>&1 &
      done
      wait
    fi
  else
    echo "cloud-setup: supabase CLI not found (continuing)"
  fi
  # --with-deps apt-installs system libs and needs root; in a non-root cloud container that step
  # fails and takes the whole command with it. Fall back to the browser-binary-only install (libs
  # are often already present in the image) before giving up. Fail-open either way.
  npx --yes playwright install --with-deps chromium >/dev/null 2>&1 \
    || npx --yes playwright install chromium >/dev/null 2>&1 \
    || echo "cloud-setup: playwright install failed (continuing)"
fi

# --- Generic dev-dep + re-vendor steps (profile-independent, opt-in via worktrees.conf) -----------
CLOUD_APT_PACKAGES="$(_conf_val CLOUD_APT_PACKAGES .claude/worktrees.conf)"
CLOUD_INSTALL_UV="$(_conf_val CLOUD_INSTALL_UV .claude/worktrees.conf)"
CLOUD_REVENDOR="$(_conf_val CLOUD_REVENDOR .claude/worktrees.conf)"

if [ -n "$CLOUD_APT_PACKAGES" ]; then
  if command -v apt-get >/dev/null 2>&1; then
    # shellcheck disable=SC2086  # intentional word-split: space-separated package list
    apt-get install -y $CLOUD_APT_PACKAGES >/dev/null 2>&1 \
      || echo "cloud-setup: apt-get install ($CLOUD_APT_PACKAGES) failed (continuing)"
  else
    echo "cloud-setup: CLOUD_APT_PACKAGES set but apt-get not on PATH (continuing)"
  fi
fi

if [ "$CLOUD_INSTALL_UV" = 1 ] && ! command -v uv >/dev/null 2>&1; then
  # The `curl … | sh` success branch is load-bearing on `set -o pipefail` (top of file): a curl
  # failure writes nothing, sh exits 0, and without pipefail the pipeline would report false success.
  if curl -LsSf https://astral.sh/uv/install.sh 2>/dev/null | sh >/dev/null 2>&1; then
    PATH="$HOME/.local/bin:$PATH"   # uv installs to ~/.local/bin — put it on PATH for the rest of Setup
    echo "cloud-setup: installed uv -> $HOME/.local/bin/uv"
  else
    echo "cloud-setup: uv install failed (continuing)"
  fi
fi

if [ "$CLOUD_REVENDOR" = 1 ]; then
  if [ -x bin/vendor-tooling.sh ]; then
    bash bin/vendor-tooling.sh . >/dev/null 2>&1 \
      || echo "cloud-setup: re-vendor (bin/vendor-tooling.sh .) failed (continuing)"
  else
    # configured-but-prerequisite-missing: breadcrumb it (re-vendor is load-bearing — without it a
    # fresh cloud clone has no hooks/gates/skills), never a silent no-op
    echo "cloud-setup: CLOUD_REVENDOR=1 but bin/vendor-tooling.sh missing or not executable (continuing)"
  fi
fi

# Stamp the lockfile hash cloud_session.{py,cjs} compares against: sha256 of the present
# lockfiles' bytes concatenated IN THIS ORDER (package-lock.json then uv.lock; an absent one is
# skipped; no stamp at all when neither is present — nothing for cloud_session to re-sync against).
{
  _cs_locks=""
  [ -f package-lock.json ] && _cs_locks="$_cs_locks package-lock.json"
  [ -f uv.lock ] && _cs_locks="$_cs_locks uv.lock"
  if [ -n "$_cs_locks" ] && [ "$_cs_install_ok" = 0 ]; then
    echo "cloud-setup: stamp skipped — dependency install failed; re-run scripts/cloud-setup.sh"
  elif [ -n "$_cs_locks" ]; then
    mkdir -p .claude/state
    # shellcheck disable=SC2086  # intentional word-split: an ordered list of present lockfile paths
    if command -v sha256sum >/dev/null 2>&1; then
      cat $_cs_locks | sha256sum | cut -d' ' -f1 > .claude/state/cloud-setup.stamp
    else
      cat $_cs_locks | shasum -a 256 | cut -d' ' -f1 > .claude/state/cloud-setup.stamp
    fi
  fi
} || echo "cloud-setup: stamp failed (continuing)"

exit 0

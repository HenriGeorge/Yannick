# Cloud environment — Jeanre

> Last updated: 2026-10-04 18:21

This project runs in claude.ai cloud sessions via the `cloud_session` SessionStart hook
(`plugins/claude-template-hooks-{py,node}/hooks/cloud_session.*`) — a no-op on your laptop
(it only acts when `CLAUDE_CODE_REMOTE=true`). On a cloud session start it makes sure docker is
up, re-syncs dependencies when the lockfile changed, starts Supabase (web profile only), writes
`.env.local` / `.env.test` from the cloud environment's `# cloud: env` keys in `.env.example`,
seeds, and reports any missing cloud env var as a drift note.

## Environment scope

- **Name:** `Jeanre-dev` (the `CLOUD_ENV_NAME` key in `.claude/worktrees.conf`)
- **Scope:** Personal (single-repo) — one claude.ai cloud environment per repo, never shared
  across the fleet.
- **Stack profile:** cli
- **Seed method:** none

## First-time setup

`scripts/cloud-setup.sh` installs dependencies (`npm ci` / `uv sync`), installs the Supabase CLI
when the image has none and pre-pulls Supabase images and Playwright browsers (web profile only),
and stamps the lockfile hash the `cloud_session` hook
compares against on every later session start to decide whether a re-sync is needed. Every step
is fail-open — a missing/broken tool is noted, never a hard failure.

## Optional dev-dep + re-vendor steps

Three generic, profile-independent steps run when their `.claude/worktrees.conf` key is set — all
default **unset** (zero behaviour change for existing repos):

- `CLOUD_APT_PACKAGES="pkg …"` — `apt-get install -y` the space-separated OS packages (when `apt-get`
  is present).
- `CLOUD_INSTALL_UV=1` — install `uv` via the astral.sh installer when `uv` is absent.
- `CLOUD_REVENDOR=1` — regenerate the untracked vendored `.claude/` tree from in-repo `plugins/` via
  `bin/vendor-tooling.sh .` (for a repo that vendors its tooling with `ref: local`).

Each is fail-open and logs `cloud-setup: … (continuing)` on failure. See `docs/CLOUD.md` for
Jeanre's specific values.

## Env vars

`.env.example` explains the three `# cloud: env` / `# cloud: credential <host>` / `# cloud: skip`
markers the `cloud_session` hook reads — see that file. Copy the cloud environment's variables with
claude-template's `bin/cloud-env-block <repo>` (names only on screen, values to the clipboard).

claude.ai drops `ANTHROPIC_API_KEY` from a cloud session's environment (it is reserved for Claude
Code's own sign-in), so store it as `CLOUD_ANTHROPIC_API_KEY`; the hook writes it into `.env.local`
under the real name. `cloud-env-block` does this rename for you.

## Opting in to vendored tooling

Copying the plugin content into this repo's own committed `.claude/` tree (so a cloud session
with no marketplace access still gets the hooks/skills/agents) is a separate, explicit opt-in:
set `CLOUD_VENDOR=1` in `.claude/worktrees.conf` and re-run `setup.sh --update` — see
`bin/vendor-tooling.sh`. Flipping it back to `0` removes the vendored copy on the next `--update`.

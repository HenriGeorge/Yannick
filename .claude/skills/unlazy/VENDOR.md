# Vendored: unlazy

Last updated: 2026-09-11 11:15

- **Upstream:** https://github.com/Leonxlnx/unlazy
- **Package:** `unlazy-skill` v2.1.0
- **License:** MIT (see `LICENSE`, kept verbatim)
- **Vendored:** 2026-09-11
- **Snapshot, not a live dependency** — NOT auto-synced.

## Local adaptations (only these)
- `SKILL.md` description: `Codex` → `the agent` (harness-neutral; the description gates auto-fire).
- `<skill-dir>` script paths: unchanged. The SKILL.md calls scripts as `node <skill-dir>/scripts/...`, where `<skill-dir>` is an agent-resolved placeholder (the invoking agent substitutes the skill's real location) — not a hardcoded relative path, so it does not dangle across the plugin-cache boundary. No `${CLAUDE_PROJECT_DIR}/.claude` repoint needed.

## Omitted from upstream (not vendored)
`agents/openai.yaml` (Codex agent def), `package.json`, `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `.github/`, `research/`, and unlazy's own `tests/` — runtime skill payload only.

## Re-vendor procedure
Re-copy `SKILL.md scripts/ references/ templates/ LICENSE SECURITY.md` from a new upstream commit, re-apply the two adaptations above, bump this file's version+date, run `bash tests/test_vendor_unlazy.sh`.

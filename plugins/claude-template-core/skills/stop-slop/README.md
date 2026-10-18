# stop-slop

Last updated: 2026-10-03 21:00

## Provenance

- **Upstream:** https://github.com/hardikpandya/stop-slop
- **Pinned commit:** [`8da1f03`](https://github.com/hardikpandya/stop-slop/commit/8da1f030185bdfe8471220585162991eaeb970e9)
- **License:** MIT (see `LICENSE`, kept verbatim)
- **Vendored:** 2026-10-03
- **Snapshot, not a live dependency** — NOT auto-synced.

Vendored verbatim: `SKILL.md`, `references/phrases.md`, `references/structures.md`,
`references/examples.md`, `LICENSE`. Not vendored: upstream's own `README.md` and `CHANGELOG.md`
(this file replaces the former; the latter isn't needed for the skill to function).

## Local adaptation (the only edit)

`SKILL.md` frontmatter `description:` was rewritten to scope the trigger to **saved, human-facing
prose** (docs, READMEs, PR/issue descriptions, ADRs, specs) and explicitly exclude ordinary chat
replies — the `caveman` plugin deliberately uses terse chat fragments, and the two styles conflict
if both fire on the same chat turn. The skill body (rules, phrase/structure lists, examples) is
unchanged from upstream.

## Refreshing

1. Re-clone upstream at a new commit: `git clone --depth 1 https://github.com/hardikpandya/stop-slop <tmp>`.
2. Re-run the security read: read every file for prompt-injection or tool-use instructions
   (commands to run, URLs to fetch, data to exfiltrate, instructions to ignore other instructions)
   before copying anything.
3. Diff the new `SKILL.md` / `references/*.md` / `LICENSE` against this directory's copies.
4. Copy over the vendored files, re-apply the description adaptation above, bump the commit sha and
   date in this file.
5. Run `bash tests/test_plugin_skills_roster.sh` and `bash tests/test_readme_skill_count.sh`.

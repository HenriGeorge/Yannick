---
description: Publish THIS project's committed Mermaid diagrams as a browsable page (git-collected, kept fresh — run again to update, it reports what changed).
---
Publish a browsable view of **this repository's own committed Mermaid diagrams**.

**Framing (say this to the user if relevant):** this is the generic **collector** — it gathers the diagrams
that already live in this project's `*.md` files. It does **not** invent diagrams, and it is **not** the
claude_template workflow poster. The in-repo Markdown stays the source of truth; this publishes a snapshot and
reports what changed via git.

Do this:

1. **Run the generator** with the Bash tool: `workflow-diagrams`
   (If "command not found": it's installed at `~/.local/bin/workflow-diagrams` — make sure `~/.local/bin` is on
   PATH. It never edits the repo — it writes a per-repo **cache** HTML, so `git status` stays clean.)
   It prints the diagram/file counts, a git **"changed since last run"** line, and a final `HTML: <absolute-path>` line.

2. **Publish that file** with the `Artifact` tool. The page is pre-designed by the generator, so publish it
   **directly** — do NOT author, re-style it, or run an artifact-design pass:
   - `file_path` = the `<absolute-path>` from the `HTML:` line
   - `title` = "<this repo's name> — Diagrams"
   - `favicon` = 🗺️
   - **Keep one canonical URL per repo:** first call `Artifact` with `action:"list"`, look for an existing
     artifact titled "<repo> — Diagrams", and if found pass its `url` to update it in place; otherwise publish
     fresh and report the new URL.

3. **Report** to the user: the artifact URL, the diagram + file counts, and the git **"changed since last run"**
   summary (only diagrams whose source `.md` changed will differ in the page).

Notes:
- **Scope (default):** collects THIS project's OWN diagrams — it excludes the generic template/process
  docs (`.claude/rules/*`, `docs/workflow/WORKFLOW.md`/`DESIGN-WORKFLOW`/`VERIFY-WORKFLOW`/`CC-WORKTREES`/`OVERVIEW`/
  `crew-workflow-guardrails`/`DIAGRAMS`/`GETTING-STARTED`/`FIGMA-*`, `crew-archive/*`, `README.md`,
  `AGENTS.md`). Pass **`--all`** to include them (e.g. on claude_template itself, where those docs ARE the
  subject). The run prints how many files it excluded.
- The heading kicker always carries a `YYYY-MM-DD HH:MM UTC` **timestamp**.
- A **command panel** (click-to-copy · hover-to-explain) is shown by **default** — pass `--no-toolkit` to
  hide it. It's **project-aware**: each repo shows ITS OWN commands, read from the stamped
  `docs/workflow/WORKFLOW.md` (`RUN_CMD`/`TEST_CMD`) with a node `package.json` fallback, plus generic
  git-sync / `cc-worktrees` / `/workflow-diagrams` lines. On **claude_template itself** it shows the rich
  template toolkit (clone → running); a repo with no resolvable commands gets the generic lines only.
- Broken diagrams are flagged honestly: any block Mermaid can't render shows a `⚠ syntax error in <file>`
  box (with the source) instead of a silent blank.
- It's deterministic — the same repo state produces the same page. Re-running after a docs change updates only
  the diagrams whose source `.md` changed (shown in the "changed since" line).
- On a squash/rebase where the previous point isn't an ancestor, it safely does a full refresh and says so.

---
description: Update progress.md and docs, then commit and push
---

# /write — Session Documentation & Commit

Automate end-of-session documentation and git commit. Follow these steps exactly:

## Step 1: Understand What Changed

Run `git diff HEAD` and `git status` to understand all staged and unstaged changes since the last commit. Also check `git log -1` to see the last commit message for context.

## Step 2: Append to progress.md

Find `progress.md` in the project root. Append a new section at the bottom with today's date (format: `## YYYY-MM-DD — Short Title`) summarizing:
- What was built or fixed (grouped by feature if multiple)
- Which files changed and why (table format preferred)
- Any architectural decisions made
- A verification line describing how to test it

Use the same style and formatting as existing entries in that file. Do NOT rewrite existing entries.

## Step 3: Update CLAUDE.md

Find `CLAUDE.md` in the project root. In the **Current State** table, update rows for anything that changed status (e.g., `❌ not done` → `✅ done`). Add new rows for new features/modules. Update line counts if components changed significantly. Do NOT reformat or restructure other sections.

## Step 4: Update MEMORY.md (if applicable)

Check the auto-memory file at the path shown in the system context. If this session introduced stable new patterns, architectural decisions, or key file locations that should persist across sessions, update or add entries. Skip this step if nothing noteworthy was discovered.

## Step 5: Git Commit & Push

1. Stage the files you modified in steps 2–4 plus any other changed source files (do NOT stage `.env`, secrets, or `tsconfig.tsbuildinfo`)
2. Write a commit message following the project's style (check recent `git log` entries). Use `feat:`, `fix:`, `docs:` etc. prefixes. Include `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>` at the end.
3. Commit and push to the current branch.

Report what was committed when done.

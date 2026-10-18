---
name: remember
description: 'Transform lessons learned into organized, persistent memory entries. Categorizes by domain and writes to the memory system.'
---

# Remember — Lesson Capture

Transform a lesson learned into a persistent, domain-organized memory entry.

## When to Use

After discovering something non-obvious about:
- Code behavior that surprised you
- A bug pattern that recurs
- A convention that isn't documented
- A tool/library quirk
- A user preference

## Process

1. **Extract the lesson** — what was learned?
2. **Categorize** — which domain?
   - `user` — about the user's role/preferences
   - `feedback` — how the user wants you to work
   - `project` — about ongoing work/goals
   - `reference` — where to find information
3. **Write the memory** — with frontmatter:
   ```markdown
   ---
   name: descriptive-slug
   description: one-line description for relevance matching
   type: feedback|user|project|reference
   ---

   The lesson content.

   **Why:** [context that makes this actionable]
   **How to apply:** [when this should influence behavior]
   ```
4. **Update MEMORY.md index** — add one-line pointer

## Rules
- Don't save what can be derived from code or git history
- Don't save ephemeral task details
- Do save surprising behaviors, user preferences, and non-obvious constraints
- Keep entries focused — one lesson per file
- Update existing memories rather than creating duplicates

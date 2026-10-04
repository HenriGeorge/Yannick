---
name: what-context-needed
description: 'Before answering a question, list the files needed for an accurate answer. Use when unsure what context to provide.'
---

# What Context Do You Need?

Before answering my question, tell me what files you need to see.

## My Question

{{question}}

## Instructions

1. Based on the question, list the files you would need to examine
2. Explain why each file is relevant
3. Note any files you've already seen in this conversation
4. Identify what you're uncertain about

## Output Format

```markdown
## Files I Need

### Must See (required for accurate answer)
- `path/to/file` — [why needed]

### Should See (helpful for complete answer)
- `path/to/file` — [why helpful]

### Already Have
- `path/to/file` — [from earlier in conversation]

### Uncertainties
- [What I'm not sure about without seeing the code]
```

After I provide these files, I'll ask my question again.

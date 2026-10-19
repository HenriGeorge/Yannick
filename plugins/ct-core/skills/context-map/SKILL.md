---
name: context-map
description: 'Map all relevant files before making changes — identifies dependencies, callers, tests, and related code.'
---

# Context Map

Before making changes, map all relevant files to understand the full impact.

## Process

1. **Start from the target** — the file(s) you plan to modify
2. **Find imports** — what does this file import?
3. **Find callers** — what imports this file? (grep for the module/function name)
4. **Find tests** — what tests cover this code?
5. **Find config** — any configuration that references this?
6. **Find docs** — any documentation that describes this?

## Output

```markdown
## Context Map: [target]

### Target Files
- `path/to/file.py` — [what it does]

### Dependencies (imports)
- `path/to/dep.py` — [what it provides]

### Callers (imported by)
- `path/to/caller.py:42` — [how it uses target]

### Tests
- `tests/test_file.py` — [what it tests]

### Configuration
- `config.py` / `.env` — [relevant settings]

### Documentation
- `docs/file.md` — [relevant docs]

### Change Impact
- Modifying [target] will require updating [N] callers
- Tests to run: [list]
- Docs to update: [list]
```

## Rules
- Use `grep -rn` to find ALL usages, not just obvious ones
- Check both Python (`from X import Y`) and TypeScript (`import { Y } from 'X'`)
- Include indirect dependencies (A imports B which imports target)

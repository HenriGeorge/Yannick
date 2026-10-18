---
name: ruff-fix
description: 'Run ruff check iteratively until all fixable issues are resolved. Handles unfixable issues with manual fixes.'
---

# Ruff Recursive Fix

Run ruff check and iteratively fix all issues until clean.

## Process

```bash
# Step 1: Auto-fix what ruff can handle
ruff check --fix .

# Step 2: Check what remains
ruff check .

# Step 3: If issues remain, fix manually then repeat
# Common manual fixes:
# - F401: Remove unused import
# - E501: Break long line
# - UP006/UP007: Dict→dict, Optional→X|None (Python 3.12)
# - I001: Sort imports

# Step 4: Format
ruff format .

# Step 5: Final check
ruff check . && echo "Clean!"
```

## Rules
- Run on specific files/dirs when possible (not entire repo)
- Don't auto-fix files you haven't read — understand the change
- Some rules are intentionally disabled in pyproject.toml — respect those
- After fixing, run affected tests to verify no breakage

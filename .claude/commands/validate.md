---
description: Run full validation suite — tests, linter, and any project-specific checks
argument-hint: [path or scope] (blank = full suite)
---

# Validate

**Scope**: $ARGUMENTS

---

## Phase 1: DETERMINE SCOPE

| Input | Action |
|-------|--------|
| (blank) | Full suite: all tests + linter |
| `tests/unit` | Only unit tests |
| `quick` | Linter only (fastest check) |
| path | Tests matching that path + lint on that path |

---

## Phase 2: DETECT PROJECT STACK

Check for the project's test runner and linter:
- `pyproject.toml` → `uv run pytest` + `uv run ruff check`
- `package.json` → `npm test` / `npx vitest` + `npx eslint`
- `Cargo.toml` → `cargo test` + `cargo clippy`
- `go.mod` → `go test ./...` + `golangci-lint run`

---

## Phase 3: RUN TESTS

Run the appropriate test command with fail-fast (`-x` or equivalent). Capture exit code and output.

---

## Phase 4: RUN LINTER

Run the appropriate linter. Capture any violations.

---

## Phase 5: PROJECT-SPECIFIC CHECKS

If CLAUDE.md or project config mentions additional checks (doc sync, type checking, etc.), run those too.

---

## Phase 6: REPORT

```markdown
## Validation Results

| Check | Status | Details |
|-------|--------|---------|
| Tests | {pass/fail} | {N passed}, {N failed}, {N skipped} |
| Linter | {pass/fail} | {N violations or clean} |
| Extra checks | {pass/fail} | {summary} |

### Failures
{details of any failures with file:line references}

### Suggested Fixes
{actionable next steps for each failure}
```

If everything passes, just say: **All green.**

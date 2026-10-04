---
name: refactor-plan
description: 'Plan multi-file refactors with sequencing, rollback strategy, and verification steps. Advisory only — does not modify code.'
---

# Refactor Plan

Plan a multi-file refactor with sequencing, dependency ordering, and rollback strategy.

## Process

### 0. Aim at the hot files
Before scoping, rank files by change frequency so the refactor targets the genuinely hot spots,
not whatever's top of mind:
```bash
claude-template churn              # top 20 most-churned files, last 90 days
claude-template churn 10 '1.year.ago' src/   # narrow by count / window / path
```
High churn + high complexity = the strongest refactor candidates. Low-churn code, however ugly, is
rarely worth the risk.

### 1. Scope Analysis
- What is being refactored and why?
- What files are affected? (grep for all usages)
- What are the dependencies between changes?
- What tests cover this code?

### 2. Change Graph
Build a dependency graph of changes:
```
A (rename interface) → B (update implementations) → C (update callers) → D (update tests)
```

### 3. Sequencing
Order changes so the codebase is valid after each step:
1. Add new (don't remove old yet)
2. Migrate callers to new
3. Verify no remaining usages of old
4. Remove old
5. Run tests

### 4. Rollback Strategy
For each step, define how to undo it:
- Git revert? Manual undo? Feature flag?

### 5. Verification
After each step:
- Run `ruff check` (Python) or `npx eslint` (TypeScript)
- Run affected tests
- Grep for remaining usages of old patterns

## Output

```markdown
# Refactor Plan: [description]

## Why
[Motivation — not just "cleanup" but the specific pain point]

## Affected Files
- `path/to/file.py` — [what changes]

## Steps (in order)
1. [Step] — verify: [how to check]
2. [Step] — verify: [how to check]

## Rollback
- After step N: `git revert HEAD~N..HEAD`

## Risks
- [What could go wrong]
```

## Rules
- For >20 files: recommend writing a Python/sed script instead of manual edits
- Always grep for ALL usages before planning removal
- Never combine refactor with feature changes

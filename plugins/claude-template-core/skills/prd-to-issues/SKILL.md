---
name: prd-to-issues
description: "Convert a PRD (Product Requirements Document) into actionable GitHub issues. Reads a PRD file or description, breaks it into well-scoped issues with labels, milestones, acceptance criteria, and dependency ordering. Use when: (1) user says 'convert PRD to issues', 'create issues from PRD', 'break this PRD into tasks', (2) user has a PRD file and wants GitHub issues created, (3) user wants to plan implementation from a spec or requirements doc."
---

# PRD to Issues

Convert a Product Requirements Document into well-scoped, dependency-ordered GitHub issues.

## Workflow

### 1. Ingest the PRD

Read the PRD from whichever source the user provides (file path, URL, pasted text, or GitHub issue/PR).

Extract:
- Features/capabilities described
- User stories or use cases
- Technical requirements and constraints
- Non-functional requirements (performance, security, accessibility)
- Dependencies between features
- Priority signals (must-have, nice-to-have, future)

### 2. Break Into Issues

Decompose into issues following these rules:

**Sizing:** Each issue completable in 1-3 days by one developer. If larger, split it.

**Independence:** Each issue deployable independently where possible.

**Structure per issue:**
```markdown
Title: [type]: [concise description]

## Context
Why this issue exists — link back to the PRD section.

## Acceptance Criteria
- [ ] Specific, testable criterion 1
- [ ] Specific, testable criterion 2
- [ ] Specific, testable criterion 3

## Technical Notes
Implementation hints, relevant files, or constraints (only if non-obvious).

## Dependencies
- Blocks: #N (if applicable)
- Blocked by: #N (if applicable)
```

**Labels:** `feature`, `enhancement`, `bug`, `chore`, `docs`, `testing`, `infrastructure`, `security`, `performance`

**Priority:** `priority:critical`, `priority:high`, `priority:medium`, `priority:low`

### 3. Order by Dependencies

Build a dependency graph and present in implementation order:

```
Phase 1 (no dependencies):  #1, #2, #3
Phase 2 (depends on P1):    #4, #5
Phase 3 (depends on P2):    #6
```

Identify which issues can be worked in parallel within each phase.

### 4. Present for Review

Show:
1. Summary table: title, labels, priority, phase, size (S/M/L)
2. Dependency graph (text-based)
3. Full issue bodies

Ask: **"Create these on GitHub? Any to modify, split, merge, or remove?"**

### 5. Create on GitHub

Once approved, use `gh issue create` for each:
- Create in dependency order (so `#N` references resolve)
- Apply labels and milestone
- Add dependency references in the body

Output a summary table with issue numbers and URLs.

## Guidelines

- Prefer more smaller issues over fewer large ones
- Every issue must have testable acceptance criteria
- Group related issues with a shared label or milestone
- Flag vague features with `needs-clarification` label
- Include a `docs` issue for any user-facing feature needing documentation
- Include a `testing` issue for complex flows needing integration/E2E coverage

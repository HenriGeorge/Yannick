---
name: security-review
description: 'AI-powered codebase security scanner — traces data flows, catches vulnerabilities, produces actionable report with severity ratings.'
---

# Security Review

Comprehensive security scan of the codebase. Traces data flows from input to output, catches vulnerabilities.

## Scan Areas

### Input Validation
- All user inputs validated (Pydantic models, query params)
- File upload size/type restrictions
- Path traversal prevention in file operations
- SQL injection via raw queries (use parameterized)

### Authentication & Authorization
- Auth required on all non-public endpoints
- Role-based access control enforced
- Session/token management secure
- API key handling (not in frontend, not logged)

### Data Exposure
- No secrets in code or config files committed to git
- Sensitive data not in error messages or logs
- PII handling compliant with data retention policy
- CORS configured correctly (not wildcard in production)

### Dependencies
- Known vulnerabilities in dependencies (`pip audit`, `npm audit`)
- Pinned versions for reproducibility
- No unnecessary dependencies

### Infrastructure
- HTTPS enforced
- Security headers set (CSP, HSTS, X-Frame-Options)
- Rate limiting on auth and GPU endpoints
- Request size limits

## Output Format

```markdown
# Security Review: [scope]

## Critical (must fix before deploy)
- [finding with evidence and fix]

## High (fix soon)
- [finding]

## Medium (fix in next sprint)
- [finding]

## Informational
- [observation]
```

## Rules
- Never guess at security — verify with actual code
- Include file:line references for every finding
- Suggest specific fixes, not vague recommendations
- Check OWASP Top 10 systematically

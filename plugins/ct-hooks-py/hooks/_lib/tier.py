"""The PR-tier path predicates — ONE python copy, read by pr_gate (merge-time tier-0 re-check) and
by guards/session_prime (#1427, the docs-only exemption). Copied byte-for-byte from bin/pr-tier
(#926); tests/test_pr_tier.sh PT-DRIFT pins the bash and python literals equal. Keep to portable ERE
syntax. Case-INSENSITIVE: macOS checkouts are case-insensitive, so `.Claude/x.md` loads exactly like
`.claude/x.md`."""
import re

TIER0_DOC_RE = re.compile(r"\.md$", re.IGNORECASE)
TIER0_DENY_RE = re.compile(r"(^|/)(rules|commands|agents|skills|hooks|\.claude|\.github)/|(^|/)(CLAUDE|CLAUDE\.local|project-context|SKILL)\.md$|(^|/)GATES[^/]*\.md$|\.template\.md$|(^|/)docs/lessons[^/]*\.md$|(^|/)plugins/[^/]+/docs/", re.IGNORECASE)
# #1073: prompt-prose predicate. A .md under a plugin's prompt-code dirs (commands/agents/rules) or
# top-level rules/ — prose with no testable behavior, so the no-testable-behavior test-quality waiver
# is valid when every changed path is prose.
PROMPT_PROSE_RE = re.compile(r"(^|/)plugins/[^/]+/(commands|agents|rules)/.*\.md$|(^|/)rules/.*\.md$", re.IGNORECASE)

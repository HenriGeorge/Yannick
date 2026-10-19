// Pure: map a guard's refusal/error text to a known reason_class, or null.
// Anchors are the stablest substrings of each guard's message (plugins/ct-hooks-py/hooks/guards/*.py
// and the harness worktree-isolation refusal). A reworded message that no longer matches fails safe
// to null (caller leaves the result untouched) — never a wrong classification.

export type ReasonClass = 'worktree-path' | 'stale-base' | 'test-lock' | 'prime-gate'

// Checked in order; the first match wins (deterministic on a multi-anchor message).
const CHECKS: ReadonlyArray<readonly [ReasonClass, RegExp]> = [
  ['stale-base', /GATE-0 stale-base/],
  ['test-lock', /bare test-runner invocation|test-lock: lock held/],
  ['prime-gate', /isolate \+ prime|session_prime_gate|always start in a worktree, primed/],
  ['worktree-path', /worktree-isolated|stays inside the worktree|target its own worktree/],
]

export function matchReason(text: string): ReasonClass | null {
  if (!text || !text.trim()) return null
  for (const [reason, re] of CHECKS) {
    if (re.test(text)) return reason
  }
  return null
}

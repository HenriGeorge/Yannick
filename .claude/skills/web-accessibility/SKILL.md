---
name: web-accessibility
description: Use when WRITING or modifying web-profile UI — a page, form, component, or any rendered surface — so the accessibility baseline holds from the first line (semantic HTML, keyboard navigation, contrast floors), and when verifying with a11y tooling at GATE-2. Triggers - building web UI, accessibility baseline, keyboard-accessible, contrast, semantic HTML. NOT a broad UI-guidelines AUDIT of existing code (that is web-design-guidelines). Web profile ONLY — service/API, CLI, data projects skip.
---

# Accessibility baseline (R7) — WEB-PROFILE SCOPED

> Origin: rules/web-accessibility.md — moved by rules-triage Phase B / plugin phase 2.

**Scope note:** this applies to the **web** stack profile only (see `workflow.md`'s profile
table). Service/API, CLI/library, and data projects have no UI surface for it to apply to — skip
this checklist entirely for those profiles, the same way `design-workflow.md`'s Web-UI
art-direction section is gated.

A baseline accessibility bar for any UI work — not exhaustive WCAG conformance (that's a dedicated
audit, `web-design-guidelines`/`ui-aliveness-audit`), but the floor every shipped surface should
clear by default, checked at BUILD time rather than discovered later in a dedicated a11y pass.

## Semantic HTML

- Use the element whose semantics match the content: `<button>` for something clickable that
  performs an action, `<a href>` for navigation, `<nav>`/`<main>`/`<header>`/`<footer>` for page
  landmarks, `<h1>`–`<h6>` in a real (non-skipping) hierarchy, `<label>` tied to its form control
  (via `for`/`id` or wrapping).
- Don't reach for a bare `<div onClick>` when a `<button>` does the same job — the native element
  gives you keyboard focus, `Enter`/`Space` activation, and screen-reader role for free; a `div`
  gives you none of that unless you hand-roll all three.
- Images that convey information get a real `alt` describing that information; purely decorative
  images get `alt=""` (not a missing attribute, an explicitly empty one) so screen readers skip
  them cleanly.

## Keyboard navigation

- Every interactive element must be reachable and operable via keyboard alone — `Tab` to focus,
  `Enter`/`Space` to activate, `Escape` to dismiss a modal/menu. If you built a custom interactive
  component (not a native `<button>`/`<a>`/`<input>`), it needs `tabindex`, the right ARIA role,
  and hand-wired key handlers to match — that's real work, not a checkbox; verify it by actually
  tabbing through the surface, not just reading the JSX.
- Focus order should follow visual/reading order — a `tabindex` that jumps around confuses more
  than it helps. Prefer relying on natural DOM order over manual `tabindex` values wherever
  possible.
- A visible focus indicator must remain visible — don't blanket-strip `outline: none` without
  supplying an equivalent focus style; a sighted keyboard user needs to see where focus is exactly
  as much as a mouse user needs to see a hover state.

## Contrast

- Body text and meaningful UI text needs at least a 4.5:1 contrast ratio against its background
  (WCAG AA); large text (≥18pt, or ≥14pt bold) needs at least 3:1. Check actual rendered colors,
  not just the design token names — a token can drift from its documented value.
- Don't convey information (an error state, a required field, a status) through color alone — pair
  it with an icon, text label, or pattern so it still reads for color-blind users and in a
  low-contrast viewing environment.

## Verifying this skill's checklist

This is a judgment call at BUILD time (see `hooks/README.md`'s enforcement-vs-instruction
boundary — none of this is deterministically hook-checkable), but it IS verifiable at VERIFY time:
`chrome-devtools-mcp`'s `a11y-debugging` skill and Chrome DevTools' own accessibility panel both
audit semantic structure, contrast, and focus order against a live render. Run that check as part
of GATE-2's EXERCISE step for any web-profile UI change, the same way a screenshot proves the
visual render — don't treat "looks right" as proof it's operable.

## See also

`design-workflow.md` (the Web-UI GATE-1 profile this checklist complements — approve the RENDERED
design, then this governs how it's actually built) · `chrome-devtools-mcp:a11y-debugging`
(the live-audit tool for VERIFY) · `ui-aliveness-audit` (micro-feedback/loading-states audit, a
sibling concern, not a substitute for this checklist).

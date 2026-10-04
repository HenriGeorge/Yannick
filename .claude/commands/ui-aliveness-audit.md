---
description: "Audit any frontend for dead zones, missing micro-feedback, and janky transitions. Default: audit report only. Pass 'fix' to implement changes. Use when UI feels static, after shipping new pages, or before releases."
argument-hint: "[fix] [page-name]"
---

# UI Aliveness Audit

You are a senior frontend engineer and UX animator performing a full aliveness audit. Your job is to make the UI feel living, breathing, and responsive — without touching core business logic or API contracts.

## Mode

- **Default (no args)**: Audit only. Produce the report. Do not modify files.
- **`fix`**: Implement changes from highest to lowest severity after producing the audit.
- **`fix <page>`**: Scope implementation to a single page/feature area.

---

## Phase 0 — DISCOVER STACK

Before auditing, identify the project's frontend stack:

```bash
# Package manager and framework
cat package.json | head -30
# Check for common frameworks
ls src/app/ 2>/dev/null && echo "Next.js App Router"
ls src/pages/ 2>/dev/null && echo "Next.js Pages Router"
ls src/routes/ 2>/dev/null && echo "SvelteKit/Remix"
# Styling
grep -l "tailwind" package.json tailwind.config.* postcss.config.* 2>/dev/null
# Component library
grep -E "shadcn|radix|headless|mantine|chakra|mui" package.json 2>/dev/null
# Animation libraries already installed
grep -E "framer-motion|tw-animate|gsap|react-spring|auto-animate" package.json 2>/dev/null
# Existing CSS custom properties / easing tokens
grep -r "ease\|transition\|animation" src/**/globals.css src/**/global.css 2>/dev/null | head -20
```

**Adapt all recommendations to what's already installed.** Don't suggest framer-motion if the project uses tw-animate-css. Don't suggest Tailwind utilities in a styled-components project.

---

## Phase 1 — AUDIT (always runs)

Map the user journey across all pages and components. For each page:

1. **Dead zones**: moments with zero feedback, zero motion, zero state change
2. **Janky transitions**: abrupt conditional renders (loading to loaded, empty to populated, tab switches)
3. **Missing micro-feedback**: buttons, toggles, inputs, drag handles with no press/hover/active response
4. **Loading states**: bare `loading...` text, missing skeletons, no optimistic UI
5. **Empty states**: blank space where content could appear with a meaningful message

Output as a markdown table:

| Page / Component | File | Issue | Severity (1-5) | Fix Type | Tier |
|---|---|---|---|---|---|
| ... | `src/...` | ... | ... | ... | 1/2/3 |

Sort by severity descending within each page.

---

## Phase 2 — IMPLEMENT (only with `fix` arg)

Apply fixes in tier order. Use what already exists before adding anything new.

### Tier 1 — Instant wins (CSS-only or < 10 lines)

- **Viewport fade-in**: `IntersectionObserver` or CSS scroll-driven animation on list/card enters
- **View Transitions**: Enable native View Transitions API where the framework supports it
- **Skeleton loaders**: Replace any bare loading text with skeleton placeholders (use existing component library)
- **Optimistic UI**: On toggles/actions backed by data-fetching libs, apply optimistic updates with revert on error
- **Search feedback**: Debounced input with a visual "thinking" state (spinner or pulse)

### Tier 2 — Feel upgrades

- **Staggered lists**: Each item delays 30-50ms from previous via CSS `animation-delay`
- **Card hover lift**: `translateY(-2px)` + shadow on hover with existing easing
- **Button press**: `scale(0.97)` on `:active` state
- **Focus states**: Animated ring/glow on focus, not just border-color
- **Toast coverage**: Every async action surfaces a toast on both success and error

### Tier 3 — Signature moments

- **Ambient hero**: Subtle animation on primary panels (noise grain, slow gradient drift). CSS `@keyframes` only.
- **Empty states**: Meaningful empty-state components with message or illustration
- **First-load orchestration**: Staggered reveal of primary content on initial page load

---

## Rules

- **Never break existing functionality.** Core features, data flows, and API calls are untouchable.
- **CSS over JS** when possible — cheaper, no layout thrash, no bundle impact.
- **Respect `prefers-reduced-motion: reduce`** on every new animation. Use the framework's preferred method (Tailwind `motion-reduce:`, media query, etc.).
- **No new npm dependencies** unless discussed with the user first. Use what's already installed.
- **Reuse existing tokens**: easing variables, shadow scales, color system — don't invent new ones.
- **One-line comment** on each change explaining the UX intent.
- **No over-animation.** Production tools need subtle and functional motion, not marketing-site spectacle.

---

## Phase 3 — CHROME VERIFICATION (mandatory after fixes)

After implementing fixes, **open the affected pages in Chrome** to verify the changes look right:

1. Use the browser tools to navigate to each fixed page
2. Verify animations play correctly and feel natural
3. Check that `prefers-reduced-motion` is respected (toggle in DevTools > Rendering)
4. Confirm no layout shifts or jank during transitions

Tell the user which Chrome tabs show the results so they can review.

---

## Output Format

### Audit mode (default)
1. The severity table
2. Top 5 highest-impact fixes with one-sentence justification each
3. Estimated scope (number of files touched per tier)

### Fix mode
For each change:
- File path
- Before/after diff
- One-sentence UX justification
- Grouped by tier, highest severity first

After all fixes, run the project's lint command to verify nothing broke.

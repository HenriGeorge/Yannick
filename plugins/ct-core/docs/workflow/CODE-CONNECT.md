# Code Connect

Last updated: 2026-10-19 02:50

How to wire Figma **Code Connect**: it maps a repo React component to a Figma component so Dev
Mode / the Figma MCP emit the real `<Component/>` (with mapped props) instead of guessing. Full
paid-plan / CLI caveats: `figma-ui` skill, SKILL.md:62-67.

## When it applies

Publish/Dev-Mode-view/MCP-read need an Org/Enterprise plan + Dev or Full seat (`parse`/`dry` work
offline for free) — adopt as a scoped per-project exception, recorded in your ADR. Map components
both sides have, or create the Figma side first; start with one high-traffic component (a Button).

## Tooling

- `bin/code-connect.sh` — wrapper over `figma connect`: `parse` / `dry` / `publish [--file F]` /
  `create <node-url>` / `repoint <file> <url>`; loads `FIGMA_ACCESS_TOKEN` from gitignored
  `.env.local`; 429 exp-backoff on publish (`CODE_CONNECT_DELAYS="0 30 90 210"`, else exit 75).
- `figma.config.json` → `codeConnect`: `parser: react`, `include: ["components/**/*.figma.tsx"]`,
  `@/*` path alias. Widen `include` as your tree grows.

## Steps

1. Clear the owner blockers: Org/Enterprise plan + Dev/Full seat; a PAT (`Code Connect → Write` +
   `File content → Read`) in `.env.local` as `FIGMA_ACCESS_TOKEN=figd_…`.
2. `bin/code-connect.sh dry` — validate the shape offline (no token/plan needed).
3. `bin/code-connect.sh create "<figma-node-url>"`, then edit the generated `*.figma.tsx`: bind
   Figma props → React props (`figma.string`/`boolean`/`enum`/`children`).
4. `bin/code-connect.sh parse` to validate, then `bin/code-connect.sh publish`. Use `repoint
   <file> <new-node-url>` to swap a mapping's Figma URL in place.

## Prop-mapping cheat sheet

```ts
import figma from '@figma/code-connect'
import { Button } from './Button'
figma.connect(Button, 'https://www.figma.com/design/<KEY>?node-id=<ID>', {
  props: {
    disabled: figma.boolean('Disabled'),
    variant: figma.enum('Type', { Primary: 'primary', Secondary: 'secondary' }),
    label: figma.string('Label'),
  },
  example: ({ disabled, variant, label }) => (
    <Button variant={variant} disabled={disabled}>{label}</Button>
  ),
})
```

## Gotchas

- `create` needs a token (fetches node metadata); `parse`/`dry` do not. Publishing on a non-Org
  plan or a View seat fails server-side — the owner blockers are hard requirements.
- Keep the PAT out of git (`.env.local` / env var); never commit it. Rate-limited (429) publishes
  retry with backoff, then exit 75 — run again later.
- `repoint` only replaces a single-quoted `figma.com/design/...` URL — double-quoted won't match.

## See also

`FIGMA-UI.md` (the Figma-MCP mechanics this complements) · the `figma-ui` skill (per-change checklist).

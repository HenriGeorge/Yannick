# Code Connect runbook

Last updated: 2026-10-11 19:46

How to wire Figma **Code Connect** for a web project. Code Connect maps a repo React component to a
Figma component so Dev Mode / the Figma MCP emit the real `<Component/>` (with mapped props) instead
of guessing. The `figma-ui` skill calls this "the highest-value lever to try first" — this is the
tool behind that claim.

> ⚠ **Paid, by conscious exception.** Code Connect is Org/Enterprise-plan + Full/Dev-seat only
> (publish, Dev-Mode view, and MCP read are all server-side gated). This collides with the usual
> no-paid-SaaS default — adopt it only as a **scoped, per-project exception** (record it in your
> project's own ADR; the template does not pre-decide it for you). Local `parse` / `dry-run` work
> offline for free; only `publish`/view/MCP-read need the paid plan.

## Tooling (scaffolded by setup.sh for the web profile)
- `bin/code-connect.sh` — the wrapper (loads `FIGMA_ACCESS_TOKEN` from gitignored `.env.local`
  without leaking it, runs `figma connect parse|dry|publish|create|repoint`, 429 exp-backoff on
  publish). Retry delays tune via `CODE_CONNECT_DELAYS="0 30 90 210"`.
- `figma.config.json` → `codeConnect` with `parser: react`, an `include` glob
  (`components/**/*.figma.tsx`), and the `@/*` path alias. Widen `include` as your tree grows.
- Install the CLI in the project: `npm i -D @figma/code-connect` (provides `node_modules/.bin/figma`;
  the binary subcommand is **`figma connect`**). ⚠ Always drive mappings through the **project-local**
  install (`bin/code-connect.sh` → `node_modules/.bin/figma`), never a global `npm i -g @figma/code-connect`:
  the global can be a **MAJOR version ahead** of the project pin, with different parser / `figma.config.json`
  behavior (a consumer repo on 2026-10-11 hit a local v1.x vs global v2.x split). A green global
  `figma --version` is NOT evidence the project tooling works — check `package.json` for the pin.
- Template files (`.figma.ts`, the v2 format) are the default in recent releases; the React
  `.figma.tsx` parser is being deprecated — prefer template files for new mappings, or `migrate`.

## The two owner actions (hard blockers for publish)
1. **Upgrade** Figma to Organization/Enterprise and assign yourself a **Dev or Full seat**.
2. **Create a Personal Access Token** at figma.com → Settings → Security → Personal access tokens,
   with scopes **Code Connect → Write** and **File content → Read**. Put it in gitignored
   `.env.local` as `FIGMA_ACCESS_TOKEN=figd_…` (the wrapper reads it from there).

## Which components to map
Code Connect needs both sides to correspond: a repo React component and a Figma component. Either map
your existing components to Figma components that already exist, or first **create** the Figma
components (via the official Figma MCP or by hand), then map your `components/*` to them. Start with
one high-traffic component (a Button) to validate the loop before mapping the whole library.

## Steps (once the blockers are cleared)
```bash
bin/code-connect.sh dry                               # validate the shape offline (no token/plan)
bin/code-connect.sh create "https://www.figma.com/design/<FILE_KEY>/<name>?node-id=<NODE_ID>"
# edit the generated file: bind Figma props → React props (figma.string/boolean/enum/children)
bin/code-connect.sh parse                             # validate the mapping
bin/code-connect.sh publish                           # real upload (needs token + paid org + Dev seat)
bin/code-connect.sh repoint <file> <new-node-url>     # swap a mapping's Figma URL in place
```

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
- `create` needs a token (it fetches node metadata); `parse` and `dry` (publish --dry-run) do not.
- Publishing on a non-Org plan or a View seat fails **server-side** — the two owner actions above are
  hard requirements, not optional.
- Keep the PAT out of git (`.env.local` / env var). Never commit it.
- Rate-limited (429) publishes retry with backoff, then exit 75 — run again later.

## See also
`FIGMA-UI.md` (the Figma-MCP mechanics this complements) · the `figma-ui` skill (per-change checklist).

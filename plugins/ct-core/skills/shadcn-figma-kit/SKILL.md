---
name: shadcn-figma-kit
description: Use when building UI with the sitsiilia shadcn/ui Figma kit — matching its component props (which deliberately differ from stock shadcn), its Figma links, or a dialog/form/chat layout from that kit. NOT for stock shadcn/ui.
---

# shadcn Figma Kit (sitsiilia)

The [sitsiilia shadcn/ui Figma kit](https://www.figma.com/community/file/1342715840824755935) ships
components whose props and classes **deliberately differ from stock shadcn/ui**. Emit code that
matches the KIT, not upstream. Every claim below is verified against the kit's own component source
(vendored, SHA-pinned, under `web-scaffold/shadcn-registry/r/`); when in doubt, read that source.

## Differs from stock shadcn

| Area | Stock shadcn | This kit |
|---|---|---|
| **Button height** | `default` = `h-9` | `default` = **`h-8`** (one step smaller) |
| **Button sizes** | `sm` `default` `lg` + `icon` | `xs` `sm` `default` `lg` — **no `size="icon"`** |
| **Icon button** | `<Button size="icon">` | a **separate `IconButton`** component |
| **Button radius** | uniform | `xs`/`sm` → `rounded-sm`, `default`/`lg` → `rounded-lg` |
| **Pill button** | — | add `className="rounded-full"` |
| **Focus ring** | `ring-2 ring-ring` | **`border-ring` + `ring-ring-subtle` + `ring-[3px]`** (a 3px subtle ring + 1px coloured border, never plain `ring`) |
| **Destructive** | one solid token | three tokens: `destructive` (solid), `text-destructive`, `destructive-subtle` (the subtle badge/alert fill) |
| **Badge** | `default`/`secondary`/`destructive`/`outline` | adds **`ghost`**; destructive is subtle (`bg-destructive-subtle text-text-destructive`), not a solid red chip |
| **Switch** | one size | adds `size` = **`default`** (`h-[18px]`) \| **`small`** (`h-3.5`) |
| **Tabs** | horizontal pills | adds `variant="line"` (underline rail) + an `orientation="vertical"` |
| **Charts** | theme chart tokens | `chart-1..5` alias the **Radix `blue` scale, steps 8→12** (sequential, not categorical) |
| **Kit-exclusive** | — | `Attachment`, `Bubble`, `Marker`, `Message`, `MessageScroller`, `Questionnaire` have **no stock-shadcn equivalent** (chat / AI-UI additions) |

## Conventions

- **Compose, don't configure.** Build layouts from the kit's parts (`CardHeader`, `DialogFooter`, …),
  not one mega-component with flags.
- **Logical props for RTL.** The kit uses `-ms-*`/`-me-*` (not `-ml-*`/`-mr-*`) so layouts mirror in RTL.
- **Icon placement via `data-icon`.** Mark an icon `data-icon="inline-start"` or `data-icon="inline-end"`
  so the component spaces it correctly — don't hand-tune margins.
- **Tokens, never hex.** Use the semantic tokens (`bg-destructive-subtle`, `var(--chart-1)`), never raw colours.
- **Disabled = `opacity-50`** on every interactive component — **except `Input`**, which dims its fill to
  `bg-input/50` instead.

## Worked example — a primary button with a leading icon

```tsx
import { Button } from "@/components/ui/button"
import { Plus } from "lucide-react"

// default size = h-8 rounded-lg (NOT stock's h-9); icon marked for spacing
<Button size="default">
  <Plus data-icon="inline-start" />
  Add item
</Button>

// a pill: add rounded-full. An icon-only action: the separate IconButton, never size="icon".
<Button className="rounded-full">Follow</Button>
```

Figma source: <https://www.figma.com/community/file/1342715840824755935>

---

Cheat-sheet derived from the **shadcn/ui Figma Kit by [@sitsiilia](https://github.com/Sitsiilia/shadcn-figma-skill)** (MIT).
Full component source is vendored SHA-pinned under `web-scaffold/shadcn-registry/` — read it when a claim here is ambiguous.

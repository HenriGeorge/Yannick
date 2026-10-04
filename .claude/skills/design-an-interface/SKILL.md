---
name: design-an-interface
description: "Design software interfaces using 'Design It Twice' from A Philosophy of Software Design. Spawn parallel agents to generate 3+ radically different designs, then compare on simplicity, depth, generality, and misuse resistance. Use when: (1) designing a new module, class, or API surface, (2) user says 'design an interface', 'design it twice', or 'compare API designs', (3) refactoring a module's public API, (4) deciding between interface approaches. Purely interface shape — no implementation."
---

# Design an Interface

Based on "Design It Twice" from *A Philosophy of Software Design*: your first idea is unlikely to be the best. Generate multiple radically different designs, then compare.

## Workflow

### 1. Gather Requirements

Before designing, understand:

- What problem does this module solve?
- Who are the callers? (other modules, external users, tests)
- What are the key operations?
- Any constraints? (performance, compatibility, existing patterns)
- What should be hidden inside vs exposed?

Ask: **"What does this module need to do? Who will use it?"**

When any of these are ambiguous, use the **AskUserQuestion** tool to resolve them — ask the key
ambiguities **one at a time** (callers first, then constraints, then hide-vs-expose), not a wall of
questions. Do not start generating designs on guessed requirements.

If the user provides a module description or code, read the relevant files to understand the current interface and its callers before proceeding.

### 2. Generate Designs (Parallel Sub-Agents)

Spawn 3+ sub-agents simultaneously using the Agent tool. Each must produce a **radically different** approach.

Assign a different design constraint to each agent:

| Agent | Constraint |
|-------|-----------|
| 1 | Minimize method count — aim for 1-3 methods max |
| 2 | Maximize flexibility — support many use cases |
| 3 | Optimize for the most common case |
| 4+ | Take inspiration from a specific paradigm/library (optional) |

Each agent prompt must include:

```
Design an interface for: [module description]
Requirements: [gathered requirements]
Constraint: [this agent's specific constraint]

Produce:
1. Interface signature (types, methods, params) — use the project's language
2. Usage example showing how a caller actually uses it
3. What this design hides internally
4. Trade-offs: what does this design make easy? What does it make hard?
```

Use `subagent_type: "general-purpose"`. Agents must research the codebase (read files, grep for callers) before designing.

### 2.5. Render Chrome Mockups (Mandatory for UI/UX interfaces)

**If the interface has a visual component** (UI components, page layouts, API responses rendered in a frontend, CLI output formats), each design MUST be rendered as a live Chrome mockup so the user can see the result, not just read about it.

For each design:

1. Create a minimal HTML file that demonstrates the interface visually
   - Use inline CSS (Tailwind CDN or plain CSS) — no build step
   - Include realistic placeholder data, not lorem ipsum
   - Show the primary interaction (click, hover, input) if applicable
   - File location: `/tmp/design-{A|B|C|...}.html`

2. Open it in Chrome using the browser tools:
   ```
   mcp__claude-in-chrome__tabs_create_mcp → navigate to file:///tmp/design-A.html
   ```

3. **Do NOT take screenshots** unless the user explicitly asks. The user will view the tab directly in Chrome.

4. Tell the user which Chrome tab has which design so they can compare side-by-side.

**For non-visual interfaces** (pure API shape, module boundaries, data structures): skip this step. A code signature + usage example is sufficient.

**Why this is mandatory**: Text descriptions of UX are unreliable — "a collapsible sidebar with grouped items" means different things to different people. A live mockup in Chrome eliminates ambiguity and makes comparison instant. (Validated in SplitWave lesson #59: visual comparison caught design insights that text specs missed.)

### 3. Present Designs

Show each design sequentially so the user can absorb each before comparison:

**Design A: [Name] — [Constraint]**
- Interface signature
- Usage example
- What it hides
- Trade-offs

**Design B: [Name] — [Constraint]**
- ...

**Design C: [Name] — [Constraint]**
- ...

### 4. Compare Designs

After presenting all designs, compare on these criteria from *A Philosophy of Software Design*:

- **Interface simplicity** — fewer methods, simpler params = easier to learn and use correctly
- **General-purpose vs specialized** — flexibility vs focus; beware over-generalization
- **Implementation efficiency** — does the interface shape allow efficient internals? Or force awkward implementation?
- **Depth** — small interface hiding significant complexity = deep module (good); large interface with thin implementation = shallow module (avoid)
- **Ease of correct use vs ease of misuse** — can callers get it wrong?

Discuss trade-offs in prose, not tables. Highlight where designs diverge most.

### 5. Synthesize

Often the best design combines insights from multiple options. Ask:

- "Which design best fits your primary use case?"
- "Any elements from other designs worth incorporating?"

Then produce a final synthesized interface if the user wants one.

### 6. Follow-Up: Aliveness Check

After the user picks a design direction, suggest:

> "Want me to run `/ui-aliveness-audit` on the implemented version to catch dead zones, missing micro-feedback, and janky transitions?"

This pairs design-time decisions (interface shape) with implementation-time polish (motion, feedback, loading states). The two skills cover different phases of the same UX quality spectrum.

## Anti-Patterns

- Do not let agents produce similar designs — enforce radical difference via distinct constraints
- Do not skip comparison — the value is in contrast
- Do not implement — this is purely about interface shape
- Do not evaluate based on implementation effort — evaluate on caller experience
- Do not present a table comparison — use prose to explain why trade-offs matter

## Verification (pass/fail)

End with an explicit verdict, not an implicit "done":

- **PASS** — ≥3 radically different designs were generated, compared on the five criteria, and the user
  has picked (or synthesized) a direction that satisfies the gathered requirements.
- **FAIL** — designs converged (not radically different), a requirement is still unresolved, or no
  direction was chosen. State which and loop back to the relevant step.

## Gotchas

- **Agents converge without distinct constraints.** If two sub-agents share a constraint they produce
  near-duplicate designs and the comparison is worthless — enforce a *distinct* constraint per agent.
- **Requirements guessed instead of asked** produce plausible-but-wrong designs that the user rejects
  late. Resolve ambiguity with AskUserQuestion (one at a time) *before* spawning agents.

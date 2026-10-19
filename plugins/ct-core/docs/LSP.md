# Native LSP — language-server symbol navigation (on by default)

Last updated: 2026-10-05 13:55

Claude Code has a **native** Language Server Protocol (LSP) integration — no third-party MCP wrapper.
When you wire in a language server, Claude gets a built-in **LSP tool** with 9 symbol-level operations
it can invoke directly, **plus** automatic diagnostics after every edit. This is real, language-aware
code intelligence: "who calls this?", "go to the definition", "find every reference", answered from
the compiler's own index instead of from text search.

Native LSP is **ON by default** in every scaffold where a language server is detected from the repo's
own files — you don't add the config, `setup.sh` does. Detection at scaffold time:

- `tsconfig.json` **or** `package.json` present → `typescript-lsp`
- `pyproject.toml` / `setup.py` / `setup.cfg` / any top-level `*.py` → `pyright-lsp`
- both signals → **both** (mixed repo)
- neither → **no LSP**, grep-only (a `cli`/`data`/Go/Rust repo is unchanged)

The detected servers **auto-install via `npm`** on a fresh scaffold (`npm i -g typescript
typescript-language-server`; `npm i -g pyright` — never `pip`, which PEP 668 breaks). This is
**fail-soft**: if `npm` is missing or the install fails, `setup.sh` warns and continues — the
`enabledPlugins` config is still written and the repo degrades to grep, it never aborts. On
`--update`/`propagate` the config is refreshed, but no global install runs (the session-start
binary warning was removed in the 2026-10-14 hook diet — a missing server degrades silently to grep). **Opt out entirely with `LSP_ENABLE=0`** (removes the entries).

> **Why default-on is safe.** An enabled LSP plugin whose server binary is missing is a documented
> **graceful silent no-op** in Claude Code: the session runs normally with no hang and no error storm —
> the plugin simply has nothing to talk to and Claude falls back to grep. The only place the absence is
> visible is `claude --debug` / the `/plugin` **Errors** tab — check there when symbol navigation
> seems absent. This graceful runtime degradation is why LSP-default is unlike the reverted RTK-default — LSP adds
> symbol tools and rewrites nothing, applies only where a server is detected, and fails to grep instead
> of to wrong output. See [`RTK.md`](RTK.md).

## What native LSP gives the agent

The LSP tool exposes **9 operations** that map directly to LSP commands (verified against
[code.claude.com/docs](https://code.claude.com/docs/en/plugins-reference) and the community
`claude-code-lsps` marketplaces):

| Operation | What Claude can ask |
|---|---|
| `goToDefinition` | jump to where a symbol is defined |
| `goToImplementation` | find the concrete implementation(s) of an interface/abstract |
| `findReferences` | **every** caller/use of a symbol (no comment/string false positives) |
| `workspaceSymbol` | search symbols across the whole repo by name |
| `documentSymbol` | list all symbols in a file (outline) |
| `hover` | type + doc of the symbol at a position |
| `prepareCallHierarchy` / `incomingCalls` / `outgoingCalls` | who-calls-what call graph |

On top of that, **automatic diagnostics**: after Claude edits a file the language server reports type
errors / unused imports / syntax errors immediately, without running a compiler or linter.

> This is why native LSP is a genuine replacement for a third-party symbol-search MCP: `findReferences`
> + `workspaceSymbol` + `goToDefinition` are exactly the cross-repo-navigation primitives that text
> search fumbles on a large codebase — and here they're built in, not a wrapper.

## WHEN it's active (and how to turn it OFF)

Native LSP is **active by default** in any scaffold where the detection above found a server —
TypeScript, Python, or both — so you get find-references at scale, rename/change-impact, type
navigation, and edit-time diagnostics without a manual step. A repo where **no** server is detected
(Go/Rust/`cli`/`data`) stays on Claude's built-in agentic search, unchanged. **Turn it off** for a
repo that would otherwise get a server with `LSP_ENABLE=0` (removes the `enabledPlugins` entries on
`--update`) — reach for that only if the startup-index cost genuinely outweighs the symbol-nav value
on your repo; the fail-soft default means an unavailable server already costs you nothing.

## HOW it's wired (and how to enable it manually)

Native LSP is a **plugin component**, not a `settings.json` key (there is no top-level `lspServers`
in the settings schema — it's declared inside a plugin's `plugin.json` or a `.lsp.json` file the
plugin ships). So you enable it by turning **a language-server plugin** on. Two committed, cloud-reaching
paths:

### A. Recommended — install an OFFICIAL language-server plugin (one-click, no third-party trust)
Anthropic's own `claude-plugins-official` marketplace (registered automatically on first interactive
launch) now ships pre-built LSP plugins, so **this no longer requires trusting a community
marketplace**. Available as of 2026-08-14: `typescript-lsp`, `pyright-lsp`, `rust-analyzer-lsp`,
`gopls-lsp`, `clangd-lsp`, `jdtls-lsp`, `csharp-lsp`, `kotlin-lsp`, `swift-lsp`, `php-lsp`,
`ruby-lsp`, `lua-lsp`, `liquid-lsp`, `platform-lsp-integrate`.

```
/plugin install pyright-lsp@claude-plugins-official
/plugin install typescript-lsp@claude-plugins-official
```

Committed equivalent, in the shared version-controlled `.claude/settings.json` so it reaches
teammates and cloud sandboxes:
```json
{
  "enabledPlugins": {
    "pyright-lsp@claude-plugins-official": true,
    "typescript-lsp@claude-plugins-official": true
  }
}
```

> **⚠ `setup.sh --update` reconciles these entries — a manual key for an UNDETECTED language is
> dropped.** On `--update` (and `propagate.sh --apply`) the helper `_lsp_merge_entries` rewrites the
> LSP config from what `_detect_lsp_servers` finds in the repo: it strips **every**
> `*-lsp@claude-plugins-official` key, then re-adds only the auto-detected ones (non-LSP
> `enabledPlugins` keys are preserved untouched). This is deliberate — it's what makes re-detection
> and `LSP_ENABLE=0` opt-out idempotent. **Consequence:** an LSP plugin you enable *by hand* for a
> language the detector doesn't recognize from repo files is **silently removed on the next
> `--update`**. To make a manual entry survive, add its detection trigger to `_detect_lsp_servers`
> in `setup.sh` (so it's auto-detected), or re-add the entry after each update.

> **The upstream guidance is now "official first."** [Create plugins → Add LSP servers](https://code.claude.com/docs/en/plugins#add-lsp-servers-to-your-plugin)
> says to install the pre-built plugins for common languages and to hand-roll a `.lsp.json` **only**
> for a language they don't cover. For this template that exception is **bash** — there is no
> official bash LSP plugin, so `bash-language-server` would go the path-B route below.

**Fallback — community marketplaces.** Still valid for languages the official set misses:
[`boostvolt/claude-code-lsps`](https://github.com/boostvolt/claude-code-lsps),
[`Piebald-AI/claude-code-lsps`](https://github.com/Piebald-AI/claude-code-lsps) — e.g.
`/plugin marketplace add boostvolt/claude-code-lsps` then `/plugin install vtsls@claude-code-lsps`.
Weigh the third-party-config trust decision in GOTCHAS below; the official plugins avoid it.

### B. Self-hosted — commit your own tiny LSP config (no third-party marketplace)
The per-server schema is a map of `<language> → { command, args, extensionToLanguage }` (plus optional
`transport`/`env`/`initializationOptions`/`settings`/`maxRestarts`). Ship it as a `.lsp.json` in a small
in-repo plugin (or inline under an `lspServers` key in that plugin's `plugin.json`). The **verified**
snippets for the two languages the note targets:

```json
// typescript-language-server (or vtsls) — .ts/.tsx/.js/.jsx/.mjs/.cjs
{
  "typescript": {
    "command": "typescript-language-server",
    "args": ["--stdio"],
    "extensionToLanguage": {
      ".ts": "typescript", ".tsx": "typescriptreact",
      ".js": "javascript", ".jsx": "javascriptreact",
      ".mjs": "javascript", ".cjs": "javascript"
    }
  }
}
```
```json
// pyright — .py/.pyi
{
  "python": {
    "command": "pyright-langserver",
    "args": ["--stdio"],
    "extensionToLanguage": { ".py": "python", ".pyi": "python" }
  }
}
```

### Per-machine prerequisite — install the language servers yourself
Unlike an all-in-one MCP, native LSP does **not** auto-provision the servers; the `command` above must
be on `PATH` on every machine (and in the cloud sandbox image):
```bash
npm install -g typescript typescript-language-server   # TypeScript/JavaScript (or: @vtsls/language-server)
npm install -g pyright                                 # Python (provides pyright-langserver)
# Python alt: uv tool install basedpyright   (basedpyright-langserver, stricter type checking)
```

## THE NUDGE (load-bearing — don't skip this)

**Wiring the server is not enough.** Left to its defaults Claude keeps reaching for `grep`/`rg` and the
LSP tool sits unused — the value evaporates. When you enable LSP in a large repo, add a pointer to that
repo's `CLAUDE.md` so the model actually prefers the symbol operations:

```md
## Code navigation
This is a large repo with native LSP enabled. Prefer the LSP tool — `goToDefinition`,
`findReferences`, `workspaceSymbol`, `hover` — over `grep`/`rg` for cross-repo navigation,
find-references, and rename-impact. Fall back to text search only for non-symbol matches
(comments, config, docs).
```
Treat this instruction as part of enabling LSP, not an optional extra.

## GOTCHAS

- **You install the servers (they aren't bundled).** The `command` must resolve on every machine AND in
  the cloud sandbox — if the sandbox image lacks `typescript-language-server`/`pyright`, the LSP tool
  silently has nothing to talk to. Bake the install into the sandbox/CI image.
- **Monorepo / tsconfig roots.** The server indexes from the workspace root; in a monorepo point it at
  the right sub-root (`workspaceFolder`) or `tsconfig.json`/package, or references come back thin.
- **First-index latency.** The initial index of a big repo takes seconds to a minute+ (language- and
  size-dependent). Measure it on your real repo before committing the team — a slow cold index on every
  fresh sandbox can outweigh the query savings.
- **Diagnostics fire automatically.** After each edit the server posts errors/warnings into the session;
  useful, but it's always-on context cost — another reason this is large-repo-only.
- **Third-party plugin trust (path A fallback only).** A *community* LSP marketplace plugin is
  third-party config you're enabling; it wires standard language servers to the **native** LSP tool
  (not an MCP wrapper), but it's still an explicit opt-in trust decision. The **official**
  `*-lsp@claude-plugins-official` plugins carry no such decision — prefer them; path B avoids it too.
- **Confirming a server actually started.** A language server that fails to launch shows up in the
  `/plugin` **Errors** tab (e.g. `Executable not found in $PATH` when the binary isn't installed). A
  plugin whose config is *invalid* is skipped silently instead — run `claude --debug` to see why.

## See also

- [`RTK.md`](RTK.md) — the **on-by-default** sibling extra; native LSP diverges from it
  deliberately (default-on, fail-soft, detected-only — see "Why default-on is safe" above).
- [Plugins reference](https://code.claude.com/docs/en/plugins-reference) — the `lspServers` component and
  the LSP tool.
- [`boostvolt/claude-code-lsps`](https://github.com/boostvolt/claude-code-lsps) /
  [`Piebald-AI/claude-code-lsps`](https://github.com/Piebald-AI/claude-code-lsps) — ready per-language
  LSP plugins and their `.lsp.json` sources.

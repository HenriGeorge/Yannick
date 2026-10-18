# Enforcement — the workflow gates that are hard-coded, not just rule-mandated

Last updated: 2026-10-18 15:24

The canonical Design→Code→Prove workflow (`docs/workflow/WORKFLOW.md`, `rules/workflow.md` Adherence) is
rule-mandated end to end, but only PART of it is machine-enforced — a hook can't detect "did you
run skill X", only whether the **durable artifact** X produces exists, or whether a **tool-event**
appears in the session transcript. Enforcement is therefore tiered: **BLOCK** where a clean
artifact exists and false positives are rare, **WARN** (a non-blocking notice) where the trigger is
fuzzy even though the underlying discipline still matters. Every BLOCK gate carries a
`WORKFLOW:no-*` bypass token for the genuinely-trivial case; WARN gates either carry one too or are
advisory-only (no bypass needed — they never block).

> [`../FIELD-GUIDE.md`](../FIELD-GUIDE.md)'s "The gate lane" section maps this to the two proof
> modes — command-verified gates (code) + rendered-pixel approval (design) — so a reader lands here
> with the "how we decide done" framing, not just the roster.

## The gate roster

> **PreToolUse process boundary (hook consolidation PR 6).** The `Hook` column below still names each
> gate by its identity, but the 9 PreToolUse hooks — `pre_tool_use` plus `session_prime_gate` /
> `grill_gate` / `stale_base_guard` / `tdd_gate` / `nocommit_guard` / `test_lock_enforce` /
> `plan_interview_gate` / `parallel_gate` — now run as **`guards/<name>` modules of one `pre_tool`
> process** per call (PreToolUse is 2 wired entries: `pre_tool`, `pr_gate`). Each
> gate's BLOCK condition and `WORKFLOW:no-*` bypass are unchanged; full-mode `pre_tool` joins every
> matching gate's DENY into one. Each retired gate's checks run inside `pre_tool`; the
> `pre_tool --only <name>` seam is kept for the test harness, but the standalone forwarder files were
> deleted in PR C's post-propagate cleanup (`pre_tool_use.py` is kept as the stack-probe sentinel).
> See `docs/workflow/HOOKS.md` for the per-group detail.

| Step hard-coded | Hook | Event | Tier | Fires on | Bypass |
|---|---|---|---|---|---|
| **grill-me** (design+plan pressure-test) | `grill_gate` | PreToolUse (`git commit`) | **BLOCK** | committing a spec/plan (`docs/superpowers/{specs,plans}/**`) or ADR (`docs/decisions/**`) with no non-empty `## Grill findings` section. On a sync merge (MERGE_HEAD present), a spec that arrives unchanged from the other parent is skipped; one the author edited during the merge is still checked (#996). A FINAL spec also needs a `## Interview` with >=4 recorded Q&A, counted as `- **Q…` bullets or `1. **Q…` numbered items (#909) | `WORKFLOW:no-grill` |
| **plan-time interview** (GATE-1 plan interview, deliverable H — keeps the human at design time while BUILD is autonomous) | `plan_interview_gate` | PreToolUse (`git commit`) | **BLOCK** | committing a plan (`docs/superpowers/plans/**`, excluding `TEMPLATE*`) with no non-empty `## Questions resolved` section — the durable record of the `writing-plans` AskUserQuestion interview (≥3 prompts + the human's answers). Gating on a doc SECTION (not a transcript scan) is transcript-independent: AskUserQuestion is main-session-only, so a delegated builder can't call it, but the section proves the interview happened regardless of which session wrote the plan. Distinct from `grill_gate`'s `## Grill findings` (specs/plans/ADRs) — this gate is plans-only | `WORKFLOW:no-interview` |
| **brainstorming + writing-plans** (design-before-code, GATE 1) | `pr_gate` (create check) | PreToolUse (`gh pr create`) | **BLOCK** | a `feat/*` branch that hasn't ADDED a `docs/superpowers/specs/**` or `docs/superpowers/plans/**` file of its own since it diverged from trunk (a branch-scoped merge-base diff — a spec/plan already merged to trunk by an earlier PR does NOT satisfy a later, unrelated branch) | `WORKFLOW:no-design` |
| **/merge-prs** (P7 merge safety) | `pr_gate` (merge check) | PreToolUse (`gh pr merge`) | **BLOCK** | CI not all green, or the PR isn't cleanly mergeable against its base. When CI is REQUIRED (#942 — env `REQUIRE_CI`, else a `REQUIRE_CI=` line in `.claude/worktrees.conf`, else a `.github/workflows/test.yml` present), an EMPTY rollup also blocks CLOSED: a check named `tests` must report `SUCCESS` for the head, so a missing / `SKIPPED` / `NEUTRAL` check (Actions disabled, YAML error, path filter) no longer merges as green | `WORKFLOW:force-merge` |
| **head-commit race closed** (#956 — a push between the review check and the merge must not silently land an unreviewed head) | `pr_gate` (match-head check) | PreToolUse (`gh pr merge`) | **BLOCK** | the merge command is missing `--match-head-commit <headRefOid>`, or its sha doesn't equal the PR's CURRENT `headRefOid` — the block names the exact flag+sha to add. `/merge-prs`'s documented merge step always re-reads `headRefOid` and pastes it in literally (`/pr-open` has no merge step — it only reviews), so GitHub itself then refuses the merge if the head moved between this check and the real merge call | `WORKFLOW:force-merge` (same escape valve as CI/mergeable) |
| **rolling-quality-pipeline dispatched** (auto-review-on-pr Layer 2 create nudge) | `pr_gate` (create nudge) | PreToolUse (`gh pr create`) | **WARN** (nudge) | every successful (non-blocked) `gh pr create` — "run `/pr-open` — the only way to dispatch the review panel (docs-impact included at tier ≥ 1)" | — (non-blocking, no bypass) |
| **code review happened + is current** (auto-review-on-pr Layer 2 merge gate) | `pr_gate` (review check) | PreToolUse (`gh pr merge`) | **BLOCK** | the PR's LATEST `<!-- code-review:VERDICT@<headRefOid> -->` comment marker (or a genuine human GitHub review, `state: APPROVED`, counted only on the current head) is missing, not `APPROVE`, or its `@sha` ≠ the PR's `headRefOid` (a bare marker with no sha, an abbreviated sha, or a review of an older commit all block) — "latest" by timestamp across both sources, so a newer `:BLOCKERS` overrides an older `:APPROVE` and vice versa; an unrecognized/malformed verdict token is treated as non-APPROVE (fail-safe). Proves a review marker/approval IS PRESENT and head-bound; a human review counts only on the current head — not that it's thorough or author-independent (the PR author can self-post `:APPROVE`) | `WORKFLOW:no-review` (independent of `WORKFLOW:force-merge` — a merge failing BOTH CI/mergeable AND review needs BOTH tokens) |
| **security review happened + is current** (Deliverable K — the one review a self-driving run cannot skip) | `pr_gate` (security check) | PreToolUse (`gh pr merge`) | **BLOCK** *(fail-CLOSED)* | the PR's LATEST `<!-- security-review:VERDICT@sha -->` comment marker is missing, not `PASS` (or attended `WAIVED`), or its `@sha` ≠ the PR's `headRefOid` (a post-review push invalidates it) — "latest" by timestamp. UNLIKE the CI/mergeable/review axes (which fail OPEN), this fails CLOSED on a missing/invalid marker — but only once `gh pr view` itself succeeded; if `gh` is unreachable the WHOLE gate still fails open. Attended `WAIVED` (no `reason=`) needs a reason authored in the PR body (goodwill, not machine-checked; tightening tracked in #937). An auto `WAIVED@<sha> reason=docs-only` (posted by `/pr-open` on a tier-0 PR, #926) counts ONLY after the gate re-verifies from `gh pr view --json files,changedFiles` that the list is complete, has no rename/copy, and every path is docs-only markdown (the tier-0 predicate mirrored from `bin/pr-tier`) — otherwise it BLOCKs naming the first offending path; any other `reason=` value blocks as unrecognized. **DEFERRED**: for `autonomy: unattended` plans, `WAIVED`/`WORKFLOW:no-security` become non-waivable (lands with `plan_state.frontmatter`) | `WORKFLOW:no-security` (independent of `WORKFLOW:force-merge`/`no-review` — an axis-failing merge needs each axis's own token) |
| **test-quality review happened + is current** (Deliverable L — the plan-named acceptance tests are green now + ≥1 is mutation-proven able to fail) | `pr_gate` (test-quality check) | PreToolUse (`gh pr merge`) | **BLOCK** *(fail-CLOSED)* | the PR's LATEST `<!-- test-quality:VERDICT@sha -->` comment marker is missing, not `PASS` (or attended `WAIVED`), or its `@sha` ≠ the PR's `headRefOid` (a post-review push invalidates it) — "latest" by timestamp. A twin of the security axis, including the gate-verified `WAIVED reason=docs-only` tier-0 auto-waiver (#926): fails CLOSED on a missing/invalid marker, but only once `gh pr view` succeeded (if `gh` is unreachable the WHOLE gate fails open). Neither the code-review nor security marker satisfies it, and it does not satisfy them (distinct `test-quality:` prefix). This axis proves a PASS marker IS PRESENT and current-head; the marker is EARNED by a real run — `bin/test-quality-run <ledger>` executes the plan's committed CHECK/EXPECT gates through the vendored unlazy executor (`bin/gate/`) and emits `test-quality:PASS@head` ONLY on a genuine ALL-MET (a nonzero CHECK never passes on output-match), with `bin/mutation-check` as the negative control. Honest limit: the executor's `--approve` store is per-machine (dev + pre-merge, not a CI oracle) and is accident-defense, not a boundary against a determined agent — so the merge check still trusts the marker STRING; the marker is no longer paste-judged ONCE the producer is run — but wiring `/pr-open` to invoke `bin/test-quality-run` on a committed ledger end-to-end is the pending follow-up (#584); until it lands the marker in the documented flow is still `test-quality-reviewer`-authored | `WORKFLOW:no-test-quality` (independent of `WORKFLOW:force-merge`/`no-review`/`no-security` — each axis needs its own token) |
| **declare parallel batches** (`rules/agent-delegation.md` — collision-safe fan-out) | `parallel_gate` | PreToolUse (`git commit`) | **BLOCK** | committing a plan (`docs/superpowers/plans/**`, excluding `TEMPLATE*`) with ≥2 `### Task` blocks (ids numeric or letter-prefixed, e.g. `A1`) that either omits a `## Parallelization` callout OR declares a batch whose member tasks share a file path OR names a task id with no matching `### Task` block (ids normalized so `T1` == `1`; this check runs against every batch reference regardless of how many OTHER tasks parsed, so a single recognized task among ≥2 declared members still catches the unrecognized one — #668) (from `**Files:**` bullets — an explicit-verb bullet (`Create:`/`Modify:`/`Add:`/`Delete:`/`Edit:`/`Test:`) names any next token (extensionless OK), a bullet with any OTHER `Label:` prefix (single- or multi-word) or no prefix needs a path-like first token (backticked — spaces OK —, containing `/`/`.`, or a known extensionless build filename like `Makefile`/`Dockerfile` — #929), `:line-range` stripped; the Files block ends at the next heading AT THE SAME OR SHALLOWER DEPTH as the task's own (a deeper sub-heading inside a task does not end it — #929), a `**Label:**` marker EXCEPT `**Notes:**` (#929), or first `- [ ]` step-checkbox line, every other line — blank, `---`, interface decl (`- Produces:`/`- Consumes:`/`- Interfaces:`), prose — is skipped (not a close) so later real paths are never silently dropped; ``` / ~~~ fenced code is stripped once with CommonMark matching (same-char, length ≥ opener) and drives tasks + batches + the `## Parallelization` check alike so a fenced example neither counts nor hides the real section, while an unclosed fence at EOF BLOCKs rather than swallowing later tasks — #915). Single-task plans skip; a `## Parallelization` section with zero parseable tasks fails loud. Intra-plan only — cross-plan overlap is worktree+merge's job; the plan-mode path (`~/.claude/plans/*.md`, outside any project git repo) is NOT covered by this commit-time BLOCK — the `parallel_nudge` WARN that once covered it was removed in the hook diet (`agent-delegation.md`'s "a plan batch is concurrent by default" prose is the only remaining discipline there). Fail-open on git/parse error | `WORKFLOW:no-parallel` |
| **test-driven-development** (write the failing test first, issue #150) | `tdd_gate` | PreToolUse (`git commit`) | **BLOCK** (V1) | the staged set has ≥1 SOURCE-classified file change and 0 TEST-classified file changes (classification below). (The `.claude/vendor.lock` exemption was retired in #1296 — copy-delivery leaves nothing lock-tracked to exempt, so every staged path is classified) | `WORKFLOW:no-tdd` |
| **GATE-0 stale-base** (gives "rebase if behind" teeth — rules A4/A5) | `stale_base_guard` | PreToolUse (`git commit`) | **BLOCK** | HEAD is behind `origin/main` AND the staged files OVERLAP files that changed on `origin/main` since the merge-base (a real collision risk). Behind-but-disjoint → **WARN** (allow — no overlap to collide); not-behind / no `origin/main` → allow. A throttled `git fetch --quiet origin` (≤1/300s, gated on `FETCH_HEAD` mtime, fail-open) refreshes `origin/main` before the behind-check, so a long-lived session checks against the true remote tip, not a stale cached ref (#731). A `git commit -a`/`--all` also unions the unstaged-tracked names into the overlap check (#488 Gap B), and both twins tokenize a quoted `-C` path (#488 Gap A). Worktree-anchored via `git -C <path>` so a cross-worktree commit evaluates its OWN target repo, not `cwd` (#470). A `git merge origin/main` sync is exempt: when `MERGE_HEAD` exists AND is `origin/main` or contains it, the behind-check is skipped (that merge IS the sync-forward, #959) — a sync merge no longer needs `WORKFLOW:no-rebase-check`; a plain commit while behind, or a merge of another branch, still BLOCKs. **The `WORKFLOW:no-rebase-check` bypass is merge-only (#959 follow-up): honoured ONLY while a merge is in progress (`MERGE_HEAD` present), IGNORED on a normal commit** — the DENY reason gives the sanctioned path (`git stash push -u -m <tag>` → `git merge origin/main` → `git stash apply <sha>` → commit), and a refused-bypass attempt is recorded in the denial telemetry. Fail-open on any git error | `WORKFLOW:no-rebase-check` (merge commits only) |
| **isolate-then-prime first action** (GATE-0 teeth for rules A5 — `autonomy.md` — machine-enforced) | `session_prime_gate` | PreToolUse (`Edit`\|`Write`\|`NotebookEdit`\|`Bash` `git commit`/`push`/`gh pr create`\|`merge`) | **BLOCK** | in a **managed** repo (`.claude/worktrees.conf` or `project-context.md` present), a first *mutation* (`Edit`/`Write`/`NotebookEdit`, or a `git commit`/`git push`/`gh pr create`/`gh pr merge`) attempted either (1) on the shared PRIMARY checkout — not a `.claude/worktrees/` linked worktree (reuses `_is_primary_checkout`), or (2) before the session is primed for ITS OWN session id — the marker is **session-bound** (hooks-plugin 0.6.224): `.claude/state/primed` must contain the hook input's `session_id` (an empty or stale marker, from a different session, is denied; a child session inherits any non-empty marker; no `session_id` in the input falls back to presence-only + a breadcrumb). Read-only tools and ungated Bash never trip it; writes under `.claude/state/` are exempt so priming can't self-block; non-managed repos are never gated; an `Edit`/`Write`/`NotebookEdit` target that resolves OUTSIDE the repo's working tree, or inside it but CONFIRMED `git check-ignore`'d (e.g. `CLAUDE.local.md` — a check-ignore error, not a clean exit 0/1, fails CLOSED to the normal isolation/primed path), is exempt too (#995 — a worktree can't isolate either case). `PRIME_GATE=0` (env) disables it; the old `.claude/state/prime-bypass` touch-file bypass is dropped (forgeable). Fail-open on any error. SessionStart is inject-only (can't block), so this PreToolUse gate is what enforces the isolate+prime instruction — and it also removes a stale marker on startup (coordinator only) | `WORKFLOW:no-worktree` (skip isolation check) · `WORKFLOW:no-prime` (skip primed check) — both inline on the Bash command; or `PRIME_GATE=0` |
| **no leftover artifacts in history** (merge markers / NOCOMMIT sentinels / `.DS_Store`) | `nocommit_guard` | PreToolUse (`git commit`) | **BLOCK** | the staged diff ADDS a merge-conflict marker (`<<<<<<<`/`>>>>>>>`, never bare `=======`), a `NOCOMMIT`/`DO NOT COMMIT` sentinel (case-insensitive), or a `.DS_Store` (`--diff-filter=AM`). Added-lines-only, so a pre-existing marker on a context line never blocks. The sentinel doesn't match when preceded by `no-`, so the `WORKFLOW:no-nocommit` bypass token itself is never flagged (#1015). Extra patterns OPT-IN via `NOCOMMIT_PATTERNS` (env / `.claude/worktrees.conf`); a bad opt-in regex is skipped, never wedging commits. `git -C <path>`-safe. No `--amend`/merge exemption | `WORKFLOW:no-nocommit` |
| **model allow-list** (H11 Agent/Task model-guard, #178 → inverted #918) | `pre_tool_use` | PreToolUse (`Agent`/`Task` tool dispatch) | **BLOCK** | a subagent dispatch whose `model:` param is anything OTHER than an exact pinned ID (shape `claude-<family>-<version>…`) — an allow-list, so a NEW floating alias is denied by default: the bare aliases (`sonnet`/`opus`/`haiku`/`fable`) AND `opusplan`, `default`, `[1m]`-suffixed variants all float to the newest generation and are blocked; an omitted param or an exact pinned ID passes — omit `model:` so the agent def's pinned ID wins; choose the model by choosing the agent | — (architectural rule, no bypass) |
| **destructive-op guard** (H7 — the one where a miss is irrecoverable) | `pre_tool_use` | PreToolUse (`Bash\|PowerShell`) | **BLOCK** | force-push / `reset --hard` on `main`/`master`, `rm -rf` on sensitive paths (PR 8 #908: the Windows sensitive targets `C:/`, `C:/Windows`, `C:/Users` and `$env:USERPROFILE`/`$env:HOME` also apply to Bash `rm -rf`), a PowerShell `Remove-Item -Recurse` (and its aliases `del` / `erase` / `rd` / `rmdir` / `ri`, judged as `rm -f`, so `-Recurse` alone counts) on a sensitive path or a linked worktree, and the working-tree destroyers `git clean -f[d]` · `branch -D` · `checkout .` · `restore .`. Any git **global option** between `git` and the subcommand is skipped structurally — `-C`/`-c`/`--git-dir`/`--no-pager`/`--paginate`/`-P`/… — matched by SHAPE, not by name (#123 + #230; the original name-whitelist let `git --no-pager clean -fd` through UNBLOCKED). For those working-tree destroyers (`clean`/`branch`/`checkout`/`restore`) ONLY, a quoted/escaped subcommand, flag or pathspec (`git "clean" -fd`, `git \clean -fd`, `git checkout "."`) is caught too (#240, via a quote/backslash strip) — the force-push / `reset --hard` / `rm -rf` arms are NOT quote-hardened. **Also blocks the concurrent-worktree data-loss vector (#483):** a FORCED `git worktree remove -f <path>` or an `rm -rf <path>` whose target realpath is a linked worktree root that is NOT the caller's own (predicate is realpath-membership in `git worktree list`, not liveness/mtime) — fail-open when the target can't be resolved to a known worktree. See Known limitations for what it still can't see | `CT_ALLOW_DANGER=1` (segment-scoped; for PowerShell only via the process env, since a `$env:CT_ALLOW_DANGER=1` written inside the command does not count — fails closed, Q2) |
| **shared-checkout guard** (R8 — don't mutate a shared primary checkout) | `pre_tool_use` | PreToolUse (`Bash`) | **BLOCK** | a mutating git op on the shared PRIMARY checkout (`git-dir == git-common-dir`) when ≥1 other live session shares it AND it is not clean on `origin/main`; verb matched in command position so `git worktree add`/`git remote add` are not self-blocked (grill Q1). A solo session, a linked worktree, a clean-on-`origin/main` quick op, and a read-only subcommand all pass | `CT_ALLOW_SHARED=1` (process or segment-scoped) · `CT_GIT_TIMEOUT=<seconds>` (SCG git-liveness-check timeout, default 3s — raise it so a slow git shell doesn't false-fire the fail-open, #487) |
| **worktree-prune reminder** (H-prune, #483) | `pre_tool_use` | PreToolUse (`Bash`) | **WARN** (inject-only, never blocks) | any `git worktree prune` — it only clears metadata for worktrees whose dir is already gone, but a blind prune during concurrent-agent work can race a live sibling; nudge, don't stop | — (non-blocking, no bypass) |
| **plugin-cache edit guard** (don't edit a disposable plugin-cache copy) | `pre_tool_use` | PreToolUse (`Write`\|`Edit`\|`NotebookEdit`) | **BLOCK** | a Write/Edit/NotebookEdit whose resolved target is under `~/.claude/plugins/{cache,marketplaces}/**` — a machine-global copy regenerated by `claude plugin update`, where an edit never propagates to any repo and is silently dropped on the next version switch. Steers the edit to the source upstream (for claude-template, `plugins/<plugin>/<relpath>` in the claude_template checkout). Repo paths and the template repo's own `plugins/.../docs/` (not under the cache) pass untouched; NotebookEdit's `notebook_path` is matched as well as `file_path`. Claude-side only (a hook can't see a human's external-editor edit); matches the requested path, not realpath, so a repo-side dev-link stays editable. Fail-open on a bad path | `CT_ALLOW_PLUGIN_EDIT=1` (process-env) |
| **plugin-source edit guard** (keep a single source of truth for plugin-served tooling) | `vendor_owned` (a `pre_tool` guard) | PreToolUse (`Write`\|`Edit`\|`NotebookEdit` + `git commit`) | **BLOCK** (source repo only) | in the **source repo** (detected by `.claude-plugin/marketplace.json` at the root), a Write/Edit/NotebookEdit of — or a `git commit` staging — a `.claude/<kind>/<rest>` materialized copy whose `plugins/<plugin>/<kind>/<rest>` source exists REDIRECTS: the DENY names the real `plugins/` source to edit. Lock-free since #1296 (resolves ownership by walking `plugins/*/` on disk, no `vendor.lock`). A consumer/fleet repo (no marketplace.json) is never blocked — it receives `plugins/` by copy-delivery, not enforcement. Commit-side uses the shared `GIT_COMMIT_INVOCATION_RE` (so `git -C <path> commit` is caught, R8) + `_staged_names`. Fail-open when no `plugins/` dir resolves | `CT_ALLOW_TEMPLATE_EDIT=1` (process-env) |
| **conventional commits** (H2 commit-message grammar) | `pre_tool_use` | PreToolUse (`git commit`) | **BLOCK** | an inline message subject that doesn't match `type(scope)!: subject` (`feat\|fix\|docs\|style\|refactor\|perf\|test\|build\|ci\|chore\|revert`, lowercase per the spec). **Scope FROZEN (ADR 0015)** — it recognizes the COMMON spellings, not all of them: `-m x`, `-m=x`, `-m"x"` (attached), bundled shorts (`-am`/`-vam`), `--message`/`--message=`, and heredoc-in-command-substitution messages parsed from the heredoc's first content line (#190). **Every** `git commit` in a `;`/`&&` chain is checked, and within each one the subject is taken from the FIRST message-bearing flag, matching git's own rule (#230). Merge-commit default messages are exempt. **Read Known limitations before treating this as comprehensive** — a quoted token (`git "commit" -m …`) is not seen | — (no token; `-F`/`--file` is the de facto escape hatch, since a file-sourced message is out of scope) |
| **rules load check** (H12 — CLAUDE.md always-core rule imports) | `session_start` / `rules_refresh` | SessionStart | **WARN** (inject-only, never blocks) | a `@.claude/rules/*.md` import in `CLAUDE.md` that will not actually load — either **MISSING** (no such file) or **IGNORED** (present here but gitignored, so a fresh clone / CI checkout / cloud sandbox gets nothing — the #194/#198 class). `rules_refresh` (0.6.140) re-checks the MISSING case after its sync/heal on every `startup`, so a broken load surfaces even when heal is skipped (dirty tree / non-plugin import). Silent when every import resolves. Fails safe: if `git` is unavailable nothing is flagged as ignored (absence of evidence is never reported as a problem) | — (inject-only, nothing to bypass — it only reports whether a file the project itself asked for is loadable) |
| **always-core rules auto-refresh** (zero-copy rules sync; py in hooks-plugin 0.6.17, node twin in 0.6.19 #401) | `rules_refresh` | SessionStart (`source == "startup"`) | **REFRESH** (non-gating, never blocks) | on `startup`, byte-compares the repo's `.claude/rules/*.md` against the plugin's bundled `${CLAUDE_PLUGIN_ROOT}/rules/`; if any differ/are missing AND the git tree is clean, writes them and auto-commits `chore(rules): sync from plugin <ver>`. Dirty tree (any staged/unstaged TRACKED change) → warn + skip. When it *creates* a brand-new rule file the project's `CLAUDE.md` doesn't `@import`, it also warns (the refresh path never auto-edits `CLAUDE.md`) so a new always-core rule can't silently fail to load — reconcile the stub via `setup.sh --update-hooks` / `propagate.sh` (#399). **BOOTSTRAP (0.6.132, #857):** when `.claude/rules/` is *entirely missing* AND the repo's `CLAUDE.md` still cites `~/.claude/rules`, it self-heals — creates the dir, writes all bundled rules, appends the `## Conventions (always-core)` `@import` stub to `CLAUDE.md` (glob-derived, RTK-safe placement), and commits `chore(rules): bootstrap always-core rules from plugin <ver>`; a repo not citing `~/.claude/rules` is left untouched, and a gitignored `.claude/rules` warns + skips (the #194 trap). This auto-heals old-model repos left ruleless after the global-rules removal (#853). Plugin-only wiring in BOTH the py (`rules_refresh.py`) and node (`rules_refresh.cjs`) hooks plugins (NOT in `canonical-settings-hooks.json`). Fallback for the copy-model path: manual `propagate.sh` | — (non-gating; refresh, not block) |
| **concurrent-session check** (heartbeat lock; new in hooks-plugin 0.6.10) | `session_start` | SessionStart | **WARN** (inject-only, never blocks) | another **live** Claude session already holds a heartbeat lock for this repo (`~/.local/share/claude-template/sessions/<repo>/`, keyed by the session PID; `CT_SESSION_DIR` redirects it) — the shared-checkout collision the workflow's `/rc` concept was meant to catch (no `/rc` command exists; this is its deterministic replacement). Silent when no other live session holds a lock. Pruning is PID-liveness only, so a dead/crashed session's lock is removed on the next start; accepted limitation — PID reuse can keep a dead lock looking live (an advisory false-positive) | — (inject-only, nothing to bypass — advisory only) |
| **suite serialization** (run suites under the per-repo lock) | `test_lock_enforce` | PreToolUse (`Bash`) | **BLOCK** | a raw suite run (bare `pytest` / `npm test` / the project's `TEST_CMD` …) not wrapped in `bin/test-lock -- <cmd>` — the lock is keyed by git-common-dir and spans all worktrees; a contended run prints the holder and exits 75 | run via the wrapper — agents use `bin/test-lock --wait -- <cmd>` (FIFO queue, exit 75 only on `--timeout`), never an exit-75 retry loop |
| **worktree provisioning** (GATE-0 fetch · env carry-in · PORT · setup) | `worktree_create` | WorktreeCreate | **provision** (warn-and-continue, never blocks) | a native worktree being created (EnterWorktree / Agent `isolation: worktree`): branch add is `--no-track` so parallel creates don't race on `.git/config.lock` (#927), then `git fetch origin` + behind-warn, gitignored `.env*` carry-in, `SETUP` install, collision-free `PORT` → `.claude/worktree.env`. Provisioning warns-and-continues, but a *creation* failure (both the branch add and the detached fallback fail) exits **non-zero** with git's real error on stderr — never a silent exit-0 (#927) | — (non-gating) |
| **worktree teardown safety net** (backup before removal) | `worktree_remove` | WorktreeRemove | **backup + log** (non-gating) | a worktree being removed: backs up untracked/ignored files + an uncommitted-changes patch to `~/.local/share/claude-template/backups/` and frees the PORT | — (non-gating) |
| **teammate keep-working** (no idle teammate with owned tasks) | `teammate_idle` | TeammateIdle | **keep-working** (inject, never blocks) | an in-process Agent-tool teammate going idle while it still owns pending tasks — injects a continue nudge | — (non-gating) |

`stop_gate` (the Stop-event BLOCK that had folded `close_issue_gate`, `close_gate`, `docs_gate` and
`plan_gate` into modules over one transcript pass — the five rows this table once carried for
`/dev-reflect`, `/handoff`, verify-at-Stop, P6 DOCUMENT and the Plan Contract checkboxes, plus
CLOSE issue-filing) was removed in the hook diet. `Stop` now wires only `stop_record` (log/WARN —
not a gate). Those phases' discipline moved to `rules/*.md` prose; GATE-2's enforced teeth remain
in `pr_gate`'s review panel + merge axes above.

`tdd_gate`'s split responsibilities (what it does / doesn't verify, classification, the V1→V4
roadmap) and `pre_tool`'s per-guard parity/test wiring live in `HOOKS.md` — not restated here.

## How BLOCK vs WARN actually render

- **BLOCK** — the hook prints `{"decision": "block", "reason": "..."}` to stdout. PreToolUse hooks
  emit that legacy field (deprecated upstream) PLUS the current
  `hookSpecificOutput.permissionDecision: "deny"` form in the same JSON object, write the reason to
  stderr, and additionally `exit 2` — so the block survives a harness release that drops the legacy
  field. Stop hooks signal the block via the `decision` field alone (`exit 0` — Stop
  hooks block via the JSON field, not the exit code).
- **WARN** — the hook prints `{"systemMessage": "..."}` to stdout (no `decision` field) and always
  `exit 0`.
- **Fail-open, always.** Every gate: malformed stdin, a missing transcript, `git`/`gh` being
  offline or unauthenticated, or any unexpected exception → silent `exit 0`, never a block. A gate
  must never wedge a legitimate session over its own bug or a flaky external command.
- **`gh`/`git` detection is token-based, not a rigid regex/substring.** A global flag between the
  program and its subcommand (`gh --repo org/repo pr merge 123`, `gh -R org/repo pr create`, `git -C
  <path> commit`) is common — plausible in this repo's own multi-worktree workflow — and every
  detection point (`pr_gate`'s create/merge checks) tolerates
  intervening flag tokens (skipping known value-taking flags like `--repo`/`-R`/`-C`/`-c`) rather
  than requiring the literal words to sit adjacent (fix-round 1, CRITICAL). `pr_gate` further
  requires `gh` to be in **command position** — the program at the start of its shell segment,
  optionally behind a `VAR=val` assignment or an exec-wrapper (`sudo`/`env`/…) — so a `gh pr merge`
  that appears only as an ARGUMENT (`echo gh pr merge`, `grep 'gh pr merge'`, prose) no longer trips
  the gate (#447, command-vs-mention; a pure narrowing with no false-negative). A `gh pr merge` on a
  heredoc-BODY line is still gated — the accepted-false-positive class of the command-string blind
  spot; the workaround is `--body-file`, not weakening detection (see `hook-wiring/README.md`).

## Known limitations (documented, not fail-open — a genuine structural/detection gap)

These are NOT "can't tell, so allow" fail-opens — they're cases where the signal exists but the
hook's search space or classification can't see/bucket it. Written down here per fix-round 1 so the
gap is known rather than silently assumed away:

- **(Historical — the limitation this bullet described no longer applies.)** `close_gate` /
  `close_issue_gate` (the Stop-time single-transcript scope, and the `#36` compaction leg
  `precompact_evidence` once fixed for them) were removed in the hook diet (#1285) along with
  `stop_gate`; `precompact_evidence` was its only reader, so it was deleted too.
- **An empty `statusCheckRollup` is treated as CI-green ONLY when CI is NOT required** (`pr_gate`'s
  `_ci_ok`/`ciOk`). By default "no CI configured" and "checks not yet registered" (the seconds right
  after `gh pr create`/a push) produce the identical empty-array shape and the gate resolves the
  ambiguity toward ALLOW. **FIXED for CI repos (#942):** when the repo expects CI the gate instead
  requires a check **named `tests`** reporting `SUCCESS` for the head and fails CLOSED on an empty
  rollup or a missing/`SKIPPED`/`NEUTRAL` `tests` check — so a workflow that never triggered no
  longer merges as green. "Expects CI" is decided from the PR's **base branch**, not the PR's own
  worktree — `git show origin/<baseRefName>:.github/workflows/test.yml` (or `gh api
  repos/<R>/contents/…?ref=<base>` when `-R` is given) — so a PR that deletes/renames the workflow,
  a subdirectory cwd, or `-R other/repo` can no longer switch off its own requirement. An explicit
  `REQUIRE_CI` (env, else a `.claude/worktrees.conf` line) overrides both directions — `1`/`true`
  forces required, `0`/`false` opts out **with a visible systemMessage**, and an empty `REQUIRE_CI=`
  is treated as unset. The `tests` check is matched on name **and** the base workflow's `name:`
  (`workflowName`) so a stray job/app named `tests` from another workflow doesn't count. Base
  detection is **tri-state** (present / absent / **unknown**): a gh/git error, an unresolvable base
  ref, a timeout or a parse failure is *unknown* — never silently "no CI" — and fails **closed** on
  an empty rollup with a visible "could not determine" message (a non-empty green rollup only warns).
  **Remaining limit:** detection keys on a workflow file named `.github/workflows/test.yml` whose workflow `name:`
  owns the `tests` check; a PR that EDITS the workflow itself (or renames the file) still needs
  GitHub **branch protection** server-side — a client-side PreToolUse hook reads the base but cannot
  enforce required-check settings. The permissive read remains only for repos whose base has no CI.
  **Note (CI teardown 2026-10-05):** claude_template itself removed its own `.github/workflows/test.yml`,
  so this repo's base is CI-absent → the gate reads permissive here; the logic above still governs any
  scaffolded repo that keeps CI.
- **`_resolve_trunk`/`resolveTrunk` can still return `None` on a non-standard trunk with NO tracking
  signal at all.** Fix-round 2 (#142(b)) widened trunk resolution beyond `origin/HEAD` +
  `main`/`master` to also try the current branch's own upstream (`@{u}`) and
  `git config init.defaultBranch`. That covers a feature branch created with `--track` against a
  trunk like `develop`, or a repo where the default-branch config is set. A repo trunked on a
  non-standard name with NEITHER a tracked upstream NOR `init.defaultBranch` configured (e.g. a
  bare `git init` + manual branch rename, no tracking ever set) still resolves trunk to `None`, and
  `_has_spec_or_plan` fails OPEN on an unknown trunk — same permanent-no-op class as before, just a
  narrower trigger. Accepted residual: no further signal short of asking the operator.
- **The auto-review-on-pr merge gate (`pr_gate`'s review check) is Bash-only.** It fires on `gh pr
  merge` invoked as a shell command; a merge performed via the GitHub web UI or the "Merge" button
  in the GitHub app bypasses the hook entirely (true of every `pr_gate` check — no PreToolUse hook
  can intercept an action that never runs as a local tool call). A GitHub branch-protection rule
  requiring a passing status check would be the CI-side complement; out of scope for v1.
- **The review-gate marker is head-bound but still unauthenticated.** It proves a
  `<!-- code-review:APPROVE@<headRefOid> -->` comment (or an APPROVED GitHub review on the current
  head) IS PRESENT and covers the CURRENT head commit — a bare marker with no sha, an abbreviated
  sha, or a review of an older commit all block, and a post-review push invalidates the marker. It
  does NOT prove an independent party posted it (the PR author can self-post the marker; no
  author-binding in v1) — that remains accepted, documented scope, not a bug.
  `tests/test_pr_gate.sh` PG32 pins the head-binding explicitly (a marker on an older commit is
  BLOCKED, reason naming both shas and the commit distance) so it can't silently regress.

- **H2 (conventional commits) still matches a command STRING, not argv — false negatives remain in
  BOTH directions.** The three bypasses documented here previously — attached `-m"…"`/bundled `-am`,
  a `--file` appearing anywhere, and only the first commit of a chain being checked — are fixed and
  pinned (`H2.17`–`H2.19` in `tests/test_pretooluse_h1h2.sh`, differential-verified: all 32
  assertions fail against the pre-fix hooks).

  An earlier revision of this bullet claimed those were *the* false negatives and that only a false
  positive remained. **That was wrong**, and an adversarial grill of ADR 0015 measured it: a quoted
  token still hides a commit entirely — `git "commit" -m 'bad'` and `git commit "-m" 'bad'` are both
  **allowed**. This shared the root cause of the H7 quoted-invocation gap, but the two are now
  decoupled: #240 closed that gap for H7's destructive-op (via a quote/backslash strip LOCAL to that
  function), while H2's frozen scope (ADR 0015) was deliberately left untouched, so this H2 miss
  remains open. The `H2-LIMIT` rows pin only the over-block direction,
  because those were the comfortable ones to pin — which is lesson #206 recurring one layer up.

  The whole-command false POSITIVE that used to trip on *prose* is now CLOSED (#482): H2/H8 key on
  the BARE position of `git commit`/`git push` (a light quote/heredoc lexer, `_bare_shell_mask`), so a
  commit line merely *quoted* in another command's argument (`gh pr comment --body "…git commit…"`)
  or embedded in a heredoc body fed to a non-shell (`gh issue create -F - <<EOF … git commit … EOF`)
  is inert text, not a dispatch. `$( … )` / `` `…` `` command substitution stays in scope (its
  contents run), so `echo $(git commit …)` is still graded — and so is a substitution nested INSIDE
  double quotes (`x="$(git commit …)"`, `` "`git push`" ``), whose interior the shell also runs
  (#482 Gap 2: the lexer now grades a `$(`/backtick region BARE even under `"…"`, tracking context
  depth so a paren nested in a quote can't close it early). H8 additionally checks EVERY commit/push
  occurrence in a segment, not just the first — `&` is not a segment separator, so an inert-quoted
  push preceding a BARE one in the same segment (`echo "git push origin main" & git push origin
  main`) no longer masks the real dispatch (#482 Gap 1, mirroring H2's finditer structure). The
  deliberate cost: `bash -c "git commit …"` / `eval "…"`
  now go UNDETECTED — a quoted arg is treated as inert even though the shell would run it — which
  aligns H2/H8 with H1-LIMIT's long-documented `bash -c` non-detection (a guard is not a shell
  parser). This is a narrow, intentional false NEGATIVE for the wrapper-exec forms, the price of
  killing the far more common prose false-positive; genuine invocations (bare, `&&`/`;`-chained,
  `git -C <path> commit`) are still caught. The quoted-SUBCOMMAND miss above (`git "commit" -m …`) is
  a separate, still-open case (it never matched the detection regex to begin with).

  **H2's scope is now frozen, deliberately (#230 / ADR 0015, after six review rounds).** It grades the
  LITERAL argument text of the common spellings and stops there. A message the shell would build at
  runtime — a variable, a non-`cat` `$( )`, a backtick, an `eval`/`xargs` wrapper — is judged as
  that literal text, so it BLOCKS rather than slipping through. Safe direction, with one real
  consequence: building a message in a variable fails even when the runtime value is perfectly
  conventional. Pass a literal, or use `-F <file>`. Pinned as `H2-LIMIT` assertions in
  `tests/test_pretooluse_h1h2.sh`, the same "record the gap so it can't be mistaken for handled"
  discipline as `H7-LIMIT-230`.

  Why frozen rather than hardened further: six rounds found seven defects in seven different
  directions, and the last one was found by walking through a *whitelist* the round before had just
  extended. A regex cannot tokenize a shell, and H2 is a style gate on the agent's own commit
  messages — not a safety guard. `shlex` would fix the class outright, but only for the Python
  stack; the Node hook has no stdlib equivalent and the two are contractually required to return
  identical verdicts, so a hand-written JS tokenizer would trade a known regex gap for an unbounded
  parity risk. Further effort belongs on the guards where a miss is `rm -rf` or a leaked secret.

  Two narrower residuals remain accepted: a hypothetical `-format`-style flag would mis-read as
  `-m` + a value (git commit has no such flag; failure direction is a false positive), and
  `-c`/`-C <commit>` message-reuse is treated as "no inline message" and left alone.
- **H7 (destructive-op guard) skips git global options by SHAPE, but a separate-argument option
  still has to be NAMED (#230).** The prefix used to enumerate three options (`-C`, `-c`,
  `--git-dir`), which meant every other one smuggled a destroyer past the guard —
  `git --no-pager clean -fd` and `git --no-optional-locks branch -D x` were both **allowed**, a
  bypass open since #123 introduced the whitelist. It now matches the *shape* of an option, which
  closes that family — **the option family only**. An earlier revision said "for good"; an
  adversarial grill of ADR 0015 showed that overclaimed, because at the time the guard's remaining
  weakness was quoting, not options — that quoting gap is now itself closed by #240 (next bullet).

  What shape-matching cannot infer: whether an unknown option consumes the next token as its value.
  Nothing in the text of `--foo bar` says whether `bar` is that option's argument or the subcommand,
  so the separate-argument arm names git's real set (`--git-dir`, `--work-tree`, `--namespace`,
  `--exec-path`, `--super-prefix`, `--attr-source`, `--config-env`). A future git option taking a
  separate argument would reopen this one gap. Pinned as `H7-LIMIT-230`, which asserts BOTH halves
  of the boundary: the unknown separate-arg form slips, while the attached `--foo=bar` spelling of
  the *same* unknown option is caught.

- **✅ CLOSED (#240): the quoted/escaped-invocation class no longer defeats H7.**
  `_destructive_worktree_op` now STRIPS single-quote, double-quote and backslash (`['"\]`) from the
  segment before the destroyer regexes run, so a quoted or escaped SUBCOMMAND (`git "clean" -fd`,
  `git ""clean -fd`, `git \clean -fd`, intra-token `git cle"an" -fd`, `git "branch" -D x`,
  `git "restore" .`, `git "checkout" -- .`), and — because the flag and pathspec checks run on that
  same stripped segment — a quoted FLAG or PATHSPEC too (`git clean "-fd"`, `git checkout "."`,
  `git branch '-D' x`), is now caught on both stacks. This subsumes the former `H7-123-LIMIT`
  quoted-flag/pathspec limitation (whose pinned rows flipped allow→block). The strip is LOCAL to H7's
  destructive-op: H2's frozen scope (which shares `_GIT_GLOBAL_OPT`) is deliberately untouched, so a
  quoted `git "commit" …` is still invisible to H2 — see the H2 known-limitation above, which #240
  does **not** change. H7's guarantee now covers quoted and backslash-escaped invocations of the
  git working-tree destroyers, not only unquoted ones.

  Still true: H7 remains a raw-string heuristic, not a full shell tokenizer — the separate-argument
  option gap (`H7-LIMIT-230`, above) and the cwd-tracking + glob gap (`H7-LIMIT`, `cd / && rm -rf *`)
  are unchanged by #240.

## PR-gate merge axes (canonical)

This is the single canonical home for the `pr_gate` merge-check facts (`gh pr merge`). Every other
doc that touches this topic (`rules/workflow.md`, `rules/verify-workflow.md`,
`rules/agent-delegation.md`, `docs/MANUAL.md`) states a one-line summary and links
here — this section is the source of truth a drift test (`tests/test_pr_gate_docs_truth.sh`)
checks against `pr_gate.py` directly, so it must stay verbatim-accurate.

- **Marker form.** Every axis marker is an HTML comment:
  `<!-- <prefix>:<VERDICT>@<40-hex-headRefOid> -->` — a bare (non-comment) marker line, or one with
  no sha or an abbreviated sha, is rejected (the gate asks for the exact form to post).
- **Prefixes + accepted verdicts.**
  - `code-review` → needs `APPROVE` (a genuine human GitHub review, `state: APPROVED`, on the
    current head also satisfies it).
  - `security-review` / `test-quality` / `suite` → each needs `PASS` **or** `WAIVED`. A `WAIVED`
    with NO `reason=` is accepted as an attended human risk-acceptance (honored on goodwill, not
    machine-checked). When a `reason=` IS present it IS machine-validated: `reason=docs-only` (any
    axis) and test-quality's `reason=no-testable-behavior` are checked against the PR's actual
    changed files and will themselves BLOCK if the files don't match; any other `reason=` value
    blocks as unrecognized.
- **`suite` axis scope.** Evaluated only where CI is **not** required — where CI is required, the
  CI axis itself owns regression and `suite` stays inert.
- **Fail-open / fail-closed split.** The WHOLE gate fails **open** (nothing checked, but visibly —
  a stdout `systemMessage`) when `gh pr view` can't read the PR at all. Once the PR IS readable,
  the code-review, security and test-quality axes fail **closed** on a missing/invalid marker
  (code-review's only looseness is an alternate satisfaction path — a native GitHub APPROVED
  review at the current head also counts). Only the CI and mergeable checks fail open by absence;
  the head-match check fails **CLOSED** when `--match-head-commit` is missing or mismatched. CI,
  mergeable and head-match are all bypassable via `WORKFLOW:force-merge`.
- **Bypass tokens.** `WORKFLOW:force-merge` (CI/mergeable/head-match) · `WORKFLOW:no-review`
  (code-review — **not** `no-code-review`) · `WORKFLOW:no-security` · `WORKFLOW:no-test-quality` ·
  `WORKFLOW:no-suite` — each axis needs its own token; none substitutes for another.
- **Head binding.** `--match-head-commit <40-hex-headRefOid>` is required on the merge command
  itself, closing the review→merge race (a push between review and merge invalidates a marker from
  an older sha).
- **`grill_gate` is commit-time**, not part of `pr_gate`'s merge check — it blocks committing a
  spec/plan/ADR with an empty `## Grill findings` section; the plan-mode path (outside any project
  git repo) is NOT reachable by this commit-time block — the write-time `grill_nudge` WARN that once
  covered it was removed in the hook diet.

## Beyond the gates — on-demand adversarial verification (not a gate)

`/verify-adversarial` (the core plugin's `plugins/claude-template-core/commands/verify-adversarial.md`) is the
**advisory, on-demand complement** to the GATE-2 machinery above: it re-attacks a finished change
assuming its summary is wrong — scope check, cold suite re-run under `bin/test-lock`, false-test
sweep, mutation check with explicit-path restores (`git checkout -- <file>`, honoring H7), and a
checkbox audit — and emits a report-only verdict table (VERIFIED / UNPROVEN / BROKEN). It is a
command a human (or CLOSE checklist) invokes, not a hook: nothing blocks on it. An asyncRewake
Stop-hook wiring (auto-run after each source-changing turn) was designed and deliberately
deferred — the mutation step edits the working tree, which is unsafe concurrently with a live
session, and a headless per-turn run is standing billed spend; see the design spec
`docs/superpowers/specs/2026-08-14-verify-adversarial-design.md` and the follow-up issue.

## See also

`docs/workflow/WORKFLOW.md` (the 9-phase spine these gates enforce) · `rules/workflow.md` Adherence (the
seven commitments this roster machine-checks a subset of) · `hook-wiring/README.md` (the
enforcement-vs-instruction boundary these hooks live on one side of) · `tests/test_grill_gate.sh` /
`test_pr_gate.sh` (the behavior tests) ·
`tests/test_hook_wiring_merge.sh` (the wiring parity + `--init-missing` mechanism) ·
`skills/unlazy/` (the vendored completion-discipline skill whose `bin/gate/` executor earns the
test-quality `PASS@head` marker the test-quality axis above reads).

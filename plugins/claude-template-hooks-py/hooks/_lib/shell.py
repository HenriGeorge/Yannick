"""Shell-command parsing shared by the PreToolUse guards (hook consolidation PR 5): segment
split, leading-token strip, override scoping, the bare-shell mask, the #574 chained-ops note."""

import os
import re


# #980 fix round 1 — a lone `|` immediately after `>` is the shell's `>|` noclobber-override
# redirect token, not a pipe operator; splitting on it there severed `>|` from its device argument
# and let an H7 disk-device write past the guard. `(?<!>)\|` excludes exactly that one case.
SHELL_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||;|\n|(?<!>)\|")


# Leading tokens stripped (in a loop, so combos like "env FOO=bar npx ./node_modules/.bin/jest"
# resolve) before anchoring TEST_LOCK_RE — this is a nudge-grade guard, not a shell parser: it does
# NOT attempt to see through `bash -c '...'` or `$(subshell)` wrapping (accepted limitation, see
# tests/test_pretooluse_h1h2.sh "H1-LIMIT" cases).
LEADING_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*\s+")


LEADING_ENV_KEYWORD_RE = re.compile(r"^env\s+")


LEADING_NPX_RE = re.compile(r"^npx\s+")


LEADING_PATH_PREFIX_RE = re.compile(r"^(?:\./(?:[\w.-]+/)*|(?:[\w.-]+/)*node_modules/\.bin/)")


LEADING_STRIP_PATTERNS = (
    LEADING_ENV_ASSIGN_RE,
    LEADING_ENV_KEYWORD_RE,
    LEADING_NPX_RE,
    LEADING_PATH_PREFIX_RE,
)


def _strip_leading_tokens(segment: str) -> str:
    """Iteratively strips leading env-assignment / `env` / `npx` / path-prefix tokens so
    `env FOO=bar npx ./node_modules/.bin/jest` resolves down to `jest` before anchoring."""
    seg = segment
    changed = True
    while changed:
        changed = False
        for pattern in LEADING_STRIP_PATTERNS:
            new_seg = pattern.sub("", seg, count=1)
            if new_seg != seg:
                seg = new_seg
                changed = True
    return seg


def _segment_has_leading_override(segment: str, name: str) -> bool:
    """True if `name=1` is a genuine LEADING env-assignment token of THIS shell segment (not
    merely a substring mentioned elsewhere, e.g. inside a commit message or an echo — HIGH fix —
    and not leading a DIFFERENT segment of the same command — MED fix: under real shell semantics
    `VAR=1 true && git commit` only exports VAR to `true`, not to the following segment, so an
    override must be scoped to the exact segment doing the guarded work, never "any segment")."""
    seg = segment.strip()
    while True:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(\S*)\s*", seg)
        if not m:
            return False
        val = m.group(2)
        # nice-to-have: tolerate a quoted value (CT_ALLOW_SECRETS='1') — strip matching quotes.
        if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
            val = val[1:-1]
        if m.group(1) == name and val == "1":
            return True
        seg = seg[m.end():]


def _process_env_override(name: str) -> bool:
    """The hook process's own env (in case Claude Code invokes it as a child that inherits it) —
    this legitimately applies globally, unlike a command-embedded assignment."""
    return os.environ.get(name) == "1"


# #482 — a `git commit` textual match is only a REAL invocation when its `git` token sits in BARE
# shell context: NOT inside a single/double-quoted string and NOT inside a heredoc body. A commit
# command merely QUOTED in another command's argument (`gh pr comment --body "…git commit…"`) or
# embedded in a heredoc body fed to a non-shell (`gh issue create -F - <<EOF … git commit … EOF`)
# is inert data, not a dispatch. `$( … )` command substitution stays bare (its contents ARE run),
# so `echo $(git commit …)` is still caught; `bash -c "git commit …"` / `eval "…"` become
# undetected, matching H1's documented `bash -c` limitation (a guard is not a shell parser).
_HEREDOC_OPEN_RE = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")


def _strip_shell_quotes(segment: str) -> str:
    """Drop single-quote, double-quote and backslash so a QUOTED/ESCAPED invocation
    (`rm '-rf' /`, `git reset "--hard" origin/main`) can't slip past a raw-string matcher — the
    shell dispatches every one of these as the real command. #240 applied this LOCALLY to
    `_destructive_worktree_op`; #251 extends the same normalization to the sibling H7 destroyer arms
    (`_is_rm_rf`/`_rm_rf_sensitive_target`, `_reset_hard_remote_target`)."""
    return re.sub(r"['\"\\]", "", segment)


def _has_short_flag(segment: str, ch: str) -> bool:
    """True if a clustered short flag containing `ch` is present (e.g. `-f`, `-fd`, `-xf`)."""
    return bool(re.search(r"(?:^|\s)-[A-Za-z]*" + re.escape(ch) + r"[A-Za-z]*(?:\s|$)", segment))


def _bare_shell_mask(command: str) -> list:
    """Per-char booleans: True where `command[i]` is in BARE shell context — a position where the
    shell parses a command word: outside single/double quotes and heredoc bodies, but INCLUDING the
    interior of a command substitution `$( … )` / `` `…` `` EVEN when that substitution is itself
    inside double quotes, because the substitution's contents RUN (#482 Gap 2: `"$(git commit …)"`
    and `` "`git push`" `` execute — grading their interior as inert-quoted let a real commit/push
    escape). Best-effort lexer (a guard is not a shell parser): an unterminated quote / heredoc /
    substitution simply means the rest of the string is that string/body, so no real command follows.

    A stack of contexts drives the masking: 'single'/'double' (and a heredoc body) are STRING
    contexts → non-bare; 'bare'/'subst'/'btick' are COMMAND contexts → bare. A `$(` / backtick opens
    a command context on top of a string context and its matching `)` / backtick pops back — so the
    commit in `"$(git commit …)"` grades BARE while the surrounding string stays non-bare, and a
    paren nested inside a quote can't close the substitution early."""
    n = len(command)
    mask = [True] * n
    stack = ["bare"]   # top context; command modes → bare, string modes → non-bare
    active = None      # heredoc body being consumed: (delimiter, strip_leading_tabs)
    pending = []       # heredocs opened on the current line, activated at its newline
    i = 0
    while i < n:
        if active is not None:  # inside a heredoc body — mark whole line non-bare, line-oriented
            eol = command.find("\n", i)
            eol = n if eol == -1 else eol
            for k in range(i, min(eol + 1, n)):
                mask[k] = False
            line = command[i:eol]
            probe = line.lstrip("\t") if active[1] else line
            if probe.strip() == active[0]:
                active = None
            i = eol + 1
            if active is None and pending:
                active = pending.pop(0)
            continue
        c = command[i]
        top = stack[-1]
        if top == "single":
            mask[i] = False
            if c == "'":
                stack.pop()
            i += 1
            continue
        if top == "double":
            mask[i] = False
            if c == "\\" and i + 1 < n:
                mask[i + 1] = False
                i += 2
                continue
            if command[i:i + 2] == "$(":  # substitution RUNS even inside "…" → open a command context
                mask[i + 1] = False
                stack.append("subst")
                i += 2
                continue
            if c == "`":
                stack.append("btick")
                i += 1
                continue
            if c == '"':
                stack.pop()
            i += 1
            continue
        # command context ('bare' / 'subst' / 'btick') — mask stays True (bare)
        if c == "\\" and i + 1 < n:  # bare escape — the next char is literal, position still bare
            i += 2
            continue
        if c == "'":
            stack.append("single")
            mask[i] = False
            i += 1
            continue
        if c == '"':
            stack.append("double")
            mask[i] = False
            i += 1
            continue
        if command[i:i + 2] == "$(":
            stack.append("subst")
            i += 2
            continue
        if c == "`":
            stack.pop() if top == "btick" else stack.append("btick")
            i += 1
            continue
        if c == ")" and top == "subst":
            stack.pop()
            i += 1
            continue
        if command[i:i + 2] == "<<":
            m = _HEREDOC_OPEN_RE.match(command, i)
            if m:
                pending.append((m.group(3), m.group(1) == "-"))
                i = m.end()
                continue
        if c == "\n":
            if pending:
                active = pending.pop(0)
            i += 1
            continue
        i += 1
    return mask


def _segments_with_offsets(command: str):
    """(segment_text, absolute_start_offset) for each SHELL_SEGMENT_SPLIT_RE segment — same split
    the sibling guards use, but carrying each segment's offset in the ORIGINAL command so a match
    can be checked against `_bare_shell_mask` (#482)."""
    out = []
    last = 0
    for m in SHELL_SEGMENT_SPLIT_RE.finditer(command):
        out.append((command[last:m.start()], last))
        last = m.end()
    out.append((command[last:], last))
    return out


def _bare_segments(command: str, pattern=SHELL_SEGMENT_SPLIT_RE) -> list:
    """Split `command` the way `pattern`.split would, but ONLY at operators in BARE context (per
    `_bare_shell_mask`) — an operator inside a quote / heredoc body is not a real separator, so the
    fragments it would split are kept joined (#889). `pattern` defaults to the full-operator regex;
    the chained-ops warning passes `_CHAIN_SPLIT_RE` to keep its narrower set (no `|` / `\\n`), so a
    quoted `;` is not counted as a chained op."""
    mask = _bare_shell_mask(command)
    segments = []
    last = 0
    for m in pattern.finditer(command):
        if mask[m.start()]:            # operator is bare → a real separator
            segments.append(command[last:m.start()])
            last = m.end()
        # else: quoted/heredoc operator → not a separator; keep accumulating
    segments.append(command[last:])
    return segments


def _segment_has_bare_command(segment: str, seg_off: int, mask, words=("git", "rm")) -> bool:
    """True if one of `words` (a destructive op's BASE command — `git`/`rm`) appears as a token in
    BARE context, judged against the ORIGINAL command's `mask` at the token's ABSOLUTE offset (#889).
    A destructive op is only really dispatched when its base command is bare; when the only git/rm
    token sits inside a quote / heredoc body (`gh issue create --body "... git branch -D ..."`, or a
    `cat <<EOF` body) the op is inert TEXT, not a command. The danger + shared-checkout detectors
    quote-STRIP before matching (#240/#251), so a segment split alone is not enough — a fully-quoted
    op would still match the stripped substring. Gating on a bare base-command token keeps #240's
    `git "clean" -fd` (base `git` IS bare) detected while making a fully-quoted op inert. The mask is
    the original command's (never a recomputed segment mask, which loses heredoc-body context), so it
    stays correct even for a body segment split off at the bare heredoc-introducing newline (#482).

    KNOWN LIMITATION (#744/#899, nudge-grade): `_bare_shell_mask` treats `$(…)` / backtick interiors as
    bare (their contents run) but does NOT model a shell-EXECUTOR string argument — `sh -c "git reset
    --hard origin/main"`, `bash -c "rm -rf /"`, `eval "…"`, `echo "…" | sh`. There the destroyer's
    token grades non-bare and the segment is skipped, so the guard does NOT catch it. This is a
    deliberate, pre-existing limit (=#482), pinned by the H7-899-LIMIT test rows. So this gate makes a
    fully-quoted-INERT op inert while still catching a bare or #240/#251 quoted-flag dispatch — it does
    NOT claim to catch a destroyer re-dispatched through a shell executor."""
    for word in words:
        for m in re.finditer(r"\b" + re.escape(word) + r"\b", segment):
            if mask[seg_off + m.start()]:
                return True
    return False


# Independent shell operators — NOT a bare `|` (a pipeline runs every stage, nothing is discarded).
_CHAIN_SPLIT_RE = re.compile(r"&&|\|\||;")


def _chained_ops_warning(command: str) -> str:
    """If `command` chains other operations (via &&, ||, ;, or a heredoc), return a suffix warning
    they did NOT run when the command is denied. Text-only; never changes allow/deny decisions."""
    if not command:
        return ""
    # #889: a `;`/`&&`/`||`/`<<` inside a quote or heredoc BODY is inert text, not a real chain — count
    # only bare-context separators (and a bare `<<`), so `gh pr comment --body "a; b; c"` isn't warned.
    mask = _bare_shell_mask(command)
    segments = [s.strip() for s in _bare_segments(command, _CHAIN_SPLIT_RE)]
    segments = [s for s in segments if s]
    has_heredoc = any(command[i:i + 2] == "<<" and mask[i] for i in range(len(mask) - 1))
    if len(segments) < 2 and not has_heredoc:
        return ""
    others = len(segments) - 1 if len(segments) >= 2 else len(segments)
    leads = [seg.split()[0] for seg in segments if seg.split()]
    listed = ", ".join(f"`{v}`" for v in leads)
    return (
        f" NOTE: this command chains {others} other operation(s) "
        f"({listed}) that did NOT run — re-run them separately."
    )

# ---- PowerShell (hook consolidation PR 8, #908) -------------------------------------------------
# Claude Code's PowerShell tool sends the command in tool_input.command, like Bash. Rather than teach
# every guard a second shell, pre_tool / _lib.transcript translate it ONCE into the bash string with
# the same quoting, separators and command words, and the bash guards judge that. Best-effort, like
# _bare_shell_mask (a guard is not a shell parser): Invoke-Expression / cmd /c / Start-Process /
# pwsh -c are executor strings and stay undetected — the same limit as `bash -c` (#744/#899).
SHELL_TOOLS = ("Bash", "PowerShell")

_PS_RM = frozenset({"remove-item", "del", "erase", "rd", "rmdir", "ri"})  # `rm` is already rm
_PS_CMD_RE = re.compile(
    r"(?i)(^\s*|[;|&\n{(=]\s*)(?:&\s+)?"
    r"(remove-item|del|erase|rd|rmdir|ri|set-location|sl|chdir|push-location|pushd)(?=\s|$)")
_PS_CALL_RE = re.compile(r"(^|[;|\n{(]\s*)&\s+(?=\S)")
_PS_PATH_COLON_RE = re.compile(r"(?i)(\s-(?:path|literalpath|lp|pspath)):")


def ps_to_sh(cmd: str) -> str:
    """A PowerShell command as the equivalent BASH string (see the block comment above)."""
    sh = _ps_requote(cmd)
    sh = _PS_CMD_RE.sub(lambda m: m.group(1) + ("rm -f" if m.group(2).lower() in _PS_RM else "cd"), sh)
    sh = _PS_CALL_RE.sub(r"\1", sh)
    return _PS_PATH_COLON_RE.sub(r"\1 ", sh)


def _ps_requote(cmd: str) -> str:
    """PowerShell quoting → bash quoting, one char at a time. Backslash is a PowerShell PATH separator,
    never an escape → '/'. Backtick IS the escape. States: bare | sub ($( … ) inside a string — runs) |
    sq | dq | hsq | hdq (here-strings, closed only by '@ / "@ at the start of a line)."""
    out, stack, depth = [], ["bare"], []
    i, n = 0, len(cmd)
    while i < n:
        c, top, two = cmd[i], stack[-1], cmd[i:i + 2]
        if top in ("hsq", "hdq") and two == ("'@" if top == "hsq" else '"@') and (i == 0 or cmd[i - 1] == "\n"):
            out.append("'" if top == "hsq" else '"')
            stack.pop()
            i += 2
            continue
        if top in ("sq", "hsq"):
            if top == "sq" and two == "''":
                out.append("'\\''")
                i += 2
            elif top == "sq" and c == "'":
                out.append("'")
                stack.pop()
                i += 1
            else:
                out.append("'\\''" if c == "'" else "/" if c == "\\" else c)
                i += 1
            continue
        if top in ("dq", "hdq"):
            if c == "`" and i + 1 < n:
                nx = cmd[i + 1]
                out.append('\\"' if nx == '"' else "\\`" if nx == "`" else "/" if nx == "\\" else nx)
                i += 2
            elif top == "dq" and two == '""':
                out.append('\\"')
                i += 2
            elif top == "dq" and c == '"':
                out.append('"')
                stack.pop()
                i += 1
            elif two == "$(":
                out.append("$(")
                stack.append("sub")
                depth.append(0)
                i += 2
            else:
                out.append('\\"' if c == '"' else "/" if c == "\\" else c)
                i += 1
            continue
        # command context: bare or sub
        if c == "`" and i + 1 < n:
            if cmd[i + 1] == "\n" or cmd[i + 1:i + 3] == "\r\n":  # line continuation
                out.append(" ")
                i += 2 if cmd[i + 1] == "\n" else 3
            else:
                out.append("\\" + cmd[i + 1])
                i += 2
            continue
        if two in ("@'", '@"') and cmd[i + 2:i + 3] in ("\n", "\r"):
            out.append(two[1])
            stack.append("hsq" if two[1] == "'" else "hdq")
            i += 2
            continue
        if c in ("'", '"'):
            out.append(c)
            stack.append("sq" if c == "'" else "dq")
            i += 1
            continue
        if top == "sub" and c in "()":
            if c == ")" and depth[-1] == 0:
                stack.pop()
                depth.pop()
            else:
                depth[-1] += 1 if c == "(" else -1
        out.append("/" if c == "\\" else c)
        i += 1
    return "".join(out)

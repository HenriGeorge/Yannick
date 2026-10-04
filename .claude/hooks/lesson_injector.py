#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""UserPromptSubmit lesson-injector — surface the top-N relevant past lessons, re-firing on topic pivots.

UserPromptSubmit is a zero-authority seam: whatever we return as `additionalContext` is added to
the model's context, nothing more. We read `docs/lessons.md`, score each lesson block by keyword
overlap with the prompt, and inject the best N (default 3). The first prompt always injects; a later
prompt re-injects only when it's a TOPIC PIVOT (Jaccard overlap with everything injected so far
< 0.2), up to a per-session budget (default 3). A JSON state file (<session>.json =
{injected_count, last_tokens}) tracks this; a stale pre-B2 `.done` marker degrades to "already fired".

Emits nothing (silent exit 0) when: over budget, same-topic repeat, lessons.md is missing/empty, or
no lesson scores above zero (never inject noise). Fail-open on any error.

Config (env): LESSON_INJECT_TOP_N (default 3), LESSON_INJECT_BUDGET (default 3),
LESSONS_PATH (default <proj>/docs/lessons.md).

ponytail: scoring is naive set-overlap of >=4-char word tokens — good enough for a nudge; swap for
embeddings only if relevance measurably disappoints.
"""
import json
import os
import random
import re
import sys

# #554 — shared age-based state GC (sibling module in the same hooks dir). Guarded: a missing module
# degrades to no-GC, never a crash (fail-open).
try:
    from _state_prune import gc_every as _gc_every
    from _state_prune import prune_stale as _prune_stale
except Exception:  # noqa: BLE001 - GC is best-effort; never block hook load
    _prune_stale = None
    def _gc_every(_env, default=50):
        return default

DEFAULT_GC_EVERY = 50  # probabilistic 1/N sweep so the scandir isn't paid every prompt
WORD_RE = re.compile(r"[a-z0-9]{4,}")
# A lesson block starts at a `### ` heading and runs until the next `### `/`## `/`# ` heading.
HEADING_RE = re.compile(r"^#{1,3} ")
LESSON_START_RE = re.compile(r"^### ")
# `**Seen**: <N>x (last <YYYY-MM-DD>)` — count + optional last-seen date, both optional-tolerant.
SEEN_RE = re.compile(r"\*\*Seen\*\*:\s*(\d+)x(?:.*?\(last\s*(\d{4}-\d{2}-\d{2}))?", re.IGNORECASE | re.DOTALL)


def _tokens(text):
    return set(WORD_RE.findall(text.lower()))


def _seen(block):
    """(count, date) for the block's Seen line; (1, '') when absent — a pure ranking tiebreak."""
    m = SEEN_RE.search(block)
    if not m:
        return (1, "")
    return (int(m.group(1)), m.group(2) or "")


def _date_desc(d):
    """Sortable key so a MORE-RECENT date sorts FIRST (ascending); no-date sorts last."""
    if not d:
        return (0, 0, 0)
    return tuple(-int(x) for x in d.split("-"))


def _split_lessons(md):
    """-> list of (heading_line, full_block_text) for each `### ` block."""
    lines = md.splitlines()
    blocks = []
    cur = None
    for ln in lines:
        if LESSON_START_RE.match(ln):
            if cur is not None:
                blocks.append(cur)
            cur = [ln]
        elif cur is not None:
            if HEADING_RE.match(ln):  # a `## `/`# ` (or next `### `) closes the block
                blocks.append(cur)
                cur = None
                if LESSON_START_RE.match(ln):
                    cur = [ln]
            else:
                cur.append(ln)
    if cur is not None:
        blocks.append(cur)
    return [(b[0].strip(), "\n".join(b)) for b in blocks]


def _snippet(block_lines):
    """Heading + up to 2 non-blank body lines, for a compact injected entry."""
    lines = block_lines.split("\n")
    head = lines[0].strip()
    body = [ln.strip() for ln in lines[1:] if ln.strip()][:2]
    out = head
    if body:
        out += "\n  " + "\n  ".join(body)
    return out


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    try:
        if data.get("hook_event_name") not in (None, "", "UserPromptSubmit"):
            sys.exit(0)
        prompt = data.get("prompt", "")
        if not isinstance(prompt, str) or not prompt.strip():
            sys.exit(0)

        proj = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        # session_id reaches a filename — strip to a safe charset so a crafted id can't escape
        # state_dir (R6 validate-external-input; #519 review). Harness UUID in practice; defense-in-depth.
        session = re.sub(r"[^A-Za-z0-9_-]", "", str(data.get("session_id") or "nosession")) or "nosession"

        state_dir = os.path.join(proj, ".claude", "state", "lesson_injector")
        os.makedirs(state_dir, exist_ok=True)

        # GC stale per-session state files (#554) via the shared helper — both the JSON state and the
        # legacy `.done` markers. Probabilistic so the scandir isn't paid every prompt. The sweep runs
        # before this session's file is rewritten below, so the current file is kept unless this session
        # idled longer than the GC max-age (7d). STATE_GC_EVERY overrides the cadence (=1 forces a sweep,
        # used by tests). Fail-open.
        gc_every = _gc_every("STATE_GC_EVERY", DEFAULT_GC_EVERY)
        if _prune_stale and random.random() < 1.0 / gc_every:
            _prune_stale(state_dir, suffixes=(".json", ".done"))

        try:
            top_n = int(os.environ.get("LESSON_INJECT_TOP_N", "3"))
        except ValueError:
            top_n = 3
        if top_n < 1:
            sys.exit(0)

        p_tokens = _tokens(prompt)
        if not p_tokens:
            sys.exit(0)

        # Multi-prompt re-fire (B2): a JSON state file replaces the old `.done` once-per-session
        # marker. We re-inject on a later prompt only when it's a TOPIC PIVOT (Jaccard overlap with
        # everything injected so far < 0.2), up to a budget. p_tokens is computed above so the
        # fire/skip decision below can use it.
        try:
            budget = int(os.environ.get("LESSON_INJECT_BUDGET", "3"))
        except ValueError:
            budget = 3
        state_f = os.path.join(state_dir, session + ".json")
        st = {"injected_count": 0, "last_tokens": []}
        try:
            with open(state_f, encoding="utf-8") as fh:
                st = json.load(fh)
        except (OSError, ValueError):
            # A stale `.done` marker from an older (pre-B2) session degrades gracefully: treat as
            # already-injected so we don't re-fire the whole first-prompt payload on a resumed session.
            if os.path.exists(os.path.join(state_dir, session + ".done")):
                st = {"injected_count": 1, "last_tokens": []}
        # Valid-but-non-dict JSON (`[]`, `5`, `"x"`) parses without ValueError, then st.get(...) below
        # would raise → outer except → silently dead for the session. Reset to default on non-dict.
        if not isinstance(st, dict):
            st = {"injected_count": 0, "last_tokens": []}
        cnt = int(st.get("injected_count", 0))
        last = set(st.get("last_tokens", []))
        if cnt >= 1:
            if cnt >= budget:
                sys.exit(0)
            inter = len(p_tokens & last)
            union = len(p_tokens | last) or 1
            if inter / union >= 0.2:  # not a topic pivot → skip
                sys.exit(0)

        lessons_path = os.environ.get("LESSONS_PATH") or os.path.join(proj, "docs", "lessons.md")
        try:
            with open(lessons_path, encoding="utf-8", errors="replace") as fh:
                md = fh.read()
        except OSError:
            sys.exit(0)

        scored = []
        for i, (_head, block) in enumerate(_split_lessons(md)):
            score = len(p_tokens & _tokens(block))
            if score > 0:
                sc, dt = _seen(block)
                scored.append((score, sc, dt, i, block))
        if not scored:
            sys.exit(0)
        # primary: overlap desc. TIEBREAK ONLY: Seen-count desc, then recency-date desc, then file
        # order — Seen never enters the overlap score, so a zero-overlap lesson stays dropped.
        scored.sort(key=lambda t: (-t[0], -t[1], _date_desc(t[2]), t[3]))

        picked = [_snippet(b) for *_x, b in scored[:top_n]]
        context = (
            "Relevant past lessons (docs/lessons.md, auto-surfaced by keyword overlap — "
            "verify before relying on them):\n\n" + "\n\n".join(picked)
        )
        # Persist state before printing: bump the count and accumulate injected topics so a later
        # same-topic prompt is recognized as NOT a pivot (union, not just the last prompt).
        try:
            with open(state_f, "w", encoding="utf-8") as fh:
                json.dump({"injected_count": cnt + 1, "last_tokens": sorted(p_tokens | last)}, fh)
        except OSError:
            pass
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context,
            }
        }))
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - never brick a prompt
        sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    main()

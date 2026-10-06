#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""PreToolUse hook — in UNATTENDED mode only, tier AskUserQuestion forks and either let a cloud peer
answer a REVERSIBLE fork or escalate a LOAD-BEARING one (issues #513, #709).

SAFETY GATE (load-bearing — ships to ~18 fleet repos): a NO-OP pass-through (exit 0, no decision, the
human answers) UNLESS env CLAUDE_UNATTENDED_ANSWER is truthy (1/true/yes/on). Default-absent MUST pass
through untouched.

When active, each question in tool_input.questions[] is classified by _is_reversible() — a CONSERVATIVE
allow-list. ANYTHING not matched is treated as LOAD-BEARING (fail-safe).

  - REVERSIBLE (naming/formatting/ordering, no load-bearing veto word) -> ask the cloud peer
    (`${AUTOPILOT_PEER:-glm-5.3:cloud}` at `${UNATTENDED_ANSWER_URL:-http://127.0.0.1:11434}/api/chat`,
    native Ollama API, stream:false) for exactly one offered label + a short why; map it to the closest
    EXACT offered label; DENY-with-answer (the #513 contract) encoding `<header>: chose "<label>" — <why>`.
  - LOAD-BEARING, OR peer unavailable/error, OR a low-confidence reply (no offered label matched) ->
    ESCALATE: write a questionnaire item to `<cwd>/.claude/state/<branch>/autopilot-questions/<uuid>.md`
    (front-matter `task:` = ${AUTOPILOT_TASK_ID}) and DENY so the loop parks this task. NEVER a silent
    allow-through, NEVER a guessed answer on a non-reversible fork.

If a payload mixes reversible + load-bearing questions, the WHOLE call escalates (conservative). All peer
I/O is wrapped so ANY error escalates. NEVER the local GPU — a configured CLOUD peer only.

Test seams (network-free): AUTOPILOT_PEER=__stub__ (canned peer answer = the first offered label, or the
body in UNATTENDED_ANSWER_STUB_FILE if set) and AUTOPILOT_PEER=__unreachable__ (simulated peer failure).
Dependency-free: stdlib urllib only.
"""
import datetime
import json
import os
import subprocess
import sys
import urllib.request
import uuid
from typing import NoReturn

# #782 — shared denial-capture helper (sibling module). Guarded: missing module → no-capture, never crash.
try:
    from _denial_telemetry import emit_denial as _emit_denial, set_context as _set_denial_context
except Exception:  # noqa: BLE001 - capture is best-effort; never block hook load
    _emit_denial = None
    _set_denial_context = None

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_PEER = "glm-5.3:cloud"
SYSTEM_PROMPT = (
    "You are a decisive product owner standing in for an absent human. You are given a decision and a "
    "fixed list of allowed options. Choose exactly ONE option by returning its label VERBATIM, then a "
    "brief reason of at most 15 words. Do not invent options. Format: <label> — <why>."
)

# Conservative reversible allow-list. A fork is reversible ONLY if a POSITIVE keyword matches AND no VETO
# keyword does. Everything else is load-bearing (fail-safe). ponytail: keyword heuristic with a known
# ceiling — upgrade to structured per-option metadata classification if forks carry richer shape.
_REVERSIBLE_KW = (
    "name", "naming", "rename", "wording", "phrasing", "comment", "format", "indent", "whitespace",
    "ordering", "order of", "sort", "alphabet", "casing", "capitaliz", "label text", "heading",
    "title", "filename",
)
_VETO_KW = (
    "delete", "drop", "remove", "migrat", "production", "deploy", "publish", "credential", "secret",
    "password", "database", "schema", "architecture", "dependenc", "package", "license", "revert",
    "force", "overwrite", "api ", "endpoint", "auth", "payment", "billing", "irreversible", "destroy",
    "wipe", "erase", "reset", "truncate", "rollback", "uninstall", "shutdown", "rm ",
    "volume", "/dev/", "disk", "partition",  # disk-format context — "format" is a reversible kw
)


def _truthy(v):
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def _block(reason) -> NoReturn:
    if _emit_denial is not None:  # #782 — metadata-only deny row; never affects the block below
        _emit_denial("unattended_answer", reason)
    # Dual-form deny JSON matching grill_gate/stale_base_guard: deprecated top-level `decision` +
    # current hookSpecificOutput.permissionDecision=deny; reason to stderr; exit 2.
    print(json.dumps({
        "decision": "block",
        "reason": reason,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }))
    print(reason, file=sys.stderr)
    sys.exit(2)


def _question_text(question):
    parts = [question.get("question", ""), question.get("header", "")]
    for o in question.get("options") or []:
        parts.append(o.get("label", ""))
        parts.append(o.get("description", ""))
    return " ".join(p for p in parts if p).lower()


def _is_reversible(question):
    """Conservative allow-list: reversible iff a positive keyword matches and no veto keyword does.
    Unmatched -> False (load-bearing) — the fail-safe default the whole task hinges on."""
    text = _question_text(question)
    if any(kw in text for kw in _VETO_KW):
        return False
    return any(kw in text for kw in _REVERSIBLE_KW)


def _peer_context(cwd):
    """Best-effort spec path + changed-file list for peer context (G4). Never raises."""
    spec = os.environ.get("AUTOPILOT_SPEC", "")
    changed = ""
    try:
        out = subprocess.run(
            ["git", "-C", cwd or ".", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=8,
        ).stdout.strip()
        changed = out
    except Exception:  # noqa: BLE001
        pass
    return spec, changed


def _ask(question, cwd):
    """Return the peer's raw content string for one reversible question. Raises on any transport error.
    __unreachable__ simulates a peer failure; __stub__ returns a canned answer (no network)."""
    peer = os.environ.get("AUTOPILOT_PEER", DEFAULT_PEER)
    options = question.get("options") or []
    labels = [o.get("label", "") for o in options if o.get("label")]
    spec, changed = _peer_context(cwd)
    user = (
        "Decision: {q}\nAllowed options (choose exactly one, return its label verbatim):\n{opts}\n"
        "Spec: {spec}\nChanged files:\n{changed}"
    ).format(
        q=question.get("question", ""),
        opts="\n".join("- %s" % lbl for lbl in labels),
        spec=spec or "(none)",
        changed=changed or "(none)",
    )

    if peer == "__unreachable__":
        raise ConnectionError("peer __unreachable__ (simulated)")
    if peer == "__stub__":
        stub = os.environ.get("UNATTENDED_ANSWER_STUB_FILE")
        if stub:
            with open(stub, "r", encoding="utf-8") as fh:
                return json.loads(fh.read())["message"]["content"]
        # canned: the peer picks the first offered option.
        return "%s — stub peer default" % (labels[0] if labels else "")

    url = os.environ.get("UNATTENDED_ANSWER_URL", DEFAULT_URL).rstrip("/") + "/api/chat"
    payload = json.dumps({
        "model": peer,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:  # raises URLError/HTTPError on failure
        body = resp.read().decode("utf-8")
    return json.loads(body)["message"]["content"]


def _map_label(content, options):
    """Closest EXACT offered label present in the peer content, or None. Longest label wins so a short
    label can't match inside a longer one."""
    text = (content or "").lower()
    best = None
    for o in options or []:
        lbl = o.get("label", "")
        if lbl and lbl.lower() in text:
            if best is None or len(lbl) > len(best):
                best = lbl
    return best


def _why(content, label):
    rest = (content or "").replace(label, " ", 1)
    words = [w for w in rest.replace("—", " ").replace("-", " ").split() if w]
    why = " ".join(words[:15]).strip(" .,:;")
    return why or "(no rationale given)"


def _branch(cwd):
    try:
        out = subprocess.run(
            ["git", "-C", cwd or ".", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=8,
        ).stdout.strip()
        return out or "detached"
    except Exception:  # noqa: BLE001
        return "unknown"


def _write_questionnaire(cwd, branch, questions):
    """Write ONE questionnaire item covering the escalated fork(s). Returns the path. Raises on write
    failure so the caller surfaces it (never a silently-lost escalation)."""
    task = os.environ.get("AUTOPILOT_TASK_ID", "unknown")
    d = os.path.join(cwd or ".", ".claude", "state", branch, "autopilot-questions")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%s.md" % uuid.uuid4().hex)
    lines = [
        "---",
        "task: %s" % task,
        "branch: %s" % branch,
        "created: %s" % datetime.datetime.now().isoformat(timespec="seconds"),
        "kind: autopilot-question",
        "---",
        "",
    ]
    spec, changed = _peer_context(cwd)
    for q in questions:
        lines.append("# %s" % (q.get("header") or q.get("question", "") or "decision"))
        lines.append("")
        lines.append(q.get("question", ""))
        lines.append("")
        opts = q.get("options") or []
        if opts:
            lines.append("## Options")
            for o in opts:
                lines.append("- %s: %s" % (o.get("label", ""), o.get("description", "")))
            lines.append("")
    lines.append("## Context")
    lines.append("- spec: %s" % (spec or "(none)"))
    lines.append("- changed files: %s" % (changed.replace("\n", ", ") if changed else "(none)"))
    lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def _breadcrumb(cwd, branch, entry):
    """Best-effort audit trail of a peer answer. Never raises."""
    try:
        d = os.path.join(cwd or ".", ".claude", "state", branch)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "autopilot-answers.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _escalate(cwd, questions, why_reason) -> NoReturn:
    """Write the questionnaire item and DENY so the loop parks. If the write itself fails, DENY anyway
    (fail CLOSED) — surface the write error rather than allow the fork through."""
    branch = _branch(cwd)
    try:
        path = _write_questionnaire(cwd, branch, questions)
        _block(
            "unattended-answer: %s — a questionnaire item was written to %s (front-matter `task:` names "
            "the blocked task). This task is PARKED for a human. Re-run without CLAUDE_UNATTENDED_ANSWER "
            "to answer interactively." % (why_reason, path)
        )
    except Exception as e:  # noqa: BLE001
        _block(
            "unattended-answer: %s — and FAILED to write the questionnaire item (%s). This task is "
            "PARKED for a human; nothing was auto-answered." % (why_reason, str(e) or type(e).__name__)
        )


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0
    if _set_denial_context is not None:  # #782 — attribute a later deny to tool + session
        _set_denial_context(data.get("tool_name", ""), data.get("session_id", ""))
    if data.get("tool_name") != "AskUserQuestion":
        return 0
    if not _truthy(os.environ.get("CLAUDE_UNATTENDED_ANSWER")):
        return 0  # SAFETY GATE — default-absent: pass through, the human answers.

    # Once active, EVERY path must end in a DENY (_block raises SystemExit). A load-bearing fork, a peer
    # error, or a low-confidence reply all escalate; nothing falls through to an allow.
    cwd = data.get("cwd") or "."
    try:
        questions = (data.get("tool_input") or {}).get("questions") or []

        # Conservative: if ANY question is load-bearing, escalate the whole call.
        load_bearing = [q for q in questions if not _is_reversible(q)]
        if load_bearing:
            _escalate(cwd, questions, "a load-bearing decision needs a human")

        branch = _branch(cwd)
        lines = []
        for q in questions:
            header = q.get("header") or q.get("question", "") or "decision"
            options = q.get("options") or []
            try:
                content = _ask(q, cwd)
            except Exception as e:  # noqa: BLE001 — any peer transport/parse failure -> escalate
                _escalate(cwd, questions, "the peer was unavailable (%s)" % (str(e) or type(e).__name__))
            label = _map_label(content, options)
            if not label:
                # low-confidence: the peer named no offered option -> escalate, never fabricate.
                _escalate(cwd, questions, 'the peer returned no offered option for "%s"' % header)
            why = _why(content, label)
            _breadcrumb(cwd, branch, {"question": header, "label": label, "why": why})
            lines.append('%s: chose "%s" — %s' % (header, label, why))

        reason = (
            "unattended-answer (CLAUDE_UNATTENDED_ANSWER active — a cloud peer answered a reversible fork "
            "for the absent human):\n" + "\n".join(lines) +
            "\nProceed as if the human selected the above. Re-run without CLAUDE_UNATTENDED_ANSWER to prompt a human."
        )
        _block(reason)
    except Exception as e:  # noqa: BLE001 — any unexpected error while active -> escalate, never allow
        _escalate(cwd, [], "an unexpected error occurred (%s)" % (str(e) or type(e).__name__))


if __name__ == "__main__":
    sys.exit(main())

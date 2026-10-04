#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Stop hook — opt-in autonomy continue-driver (the one accelerator besides teammate_idle).

Fires in TWO opt-in cases: (1) the RALPH lane — an ad-hoc todo loop armed via
`.claude/ralph-state.json` (bin/ralph-arm / the /ralph-loop command), session-scoped and taking
precedence; or (2) the PLAN lane — this branch's newest plan declares `autonomy: unattended`. While
the todo/plan still has unchecked `- [ ]` boxes (or, in the plan lane, a `gates:` ledger with an
unmet gate; in the ralph lane, a ticked line whose `| verify:` still fails), no park sentinel is
set, we're within budget and not stalled -> emit a Stop block
({"decision":"block","reason":"next unchecked item: X"}) + exit 0, which re-drives the session (same
convention as plan_gate/close_gate — a Stop block is JSON on stdout with exit 0, NOT exit 2).
Terminates via: park sentinel, budget (max_turns ~= max stops), stall (N zero-progress stops), and
block-reason fingerprint repeat. Fails OPEN (exit 0, no block) on any error.

Plan parsing is inlined (not a shared module): hooks run standalone under `uv run --script` and
cannot import siblings — same reason docs_gate copied tdd_gate's logic.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

PLAN_DIR = "docs/superpowers/plans"
UNCHECKED_RE = re.compile(r"^\s*[-*]\s+\[ \]\s+(.*)$")
STALL_N = 3
# --- plan lane session binding (#775): TOFU-bind an unattended plan's loop to one session (mirrors
# the ralph lane) so a merged foreign plan can't hijack an unrelated session's stop. ---
PLAN_LOOP_STATE = ".claude/state/plan-loop.json"

# --- ralph lane (low-ceremony "point at a todo.md" loop) ---
RALPH_STATE = ".claude/ralph-state.json"
TODO_BOX_RE = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(.*)$")


def _run(cwd, args, timeout=8):
    try:
        r = subprocess.run(args, cwd=cwd or None, capture_output=True, text=True,
                           timeout=timeout, check=False)
    except Exception:  # noqa: BLE001 — fail open
        return None
    return r.stdout if r.returncode == 0 else None


def resolve_plan(cwd):
    """Newest .md under docs/superpowers/plans by mtime.
    ponytail: newest-mtime, not branch-scoped merge-base; adequate for the single-active-plan case,
    fails safe (picks a plan or none). Upgrade to merge-base filtering if multi-plan branches appear.
    """
    p = os.path.join(cwd or ".", PLAN_DIR)
    if not os.path.isdir(p):
        return None
    # Skip `*.gates.md` acceptance ledgers — they live beside their plan but are NOT plans themselves.
    files = [os.path.join(p, f) for f in os.listdir(p)
             if f.endswith(".md") and not f.endswith(".gates.md")]
    return max(files, key=os.path.getmtime) if files else None


def parse_plan(path):
    autonomy = None
    max_turns = None
    gates = None
    status = None
    unchecked = []
    try:
        text = open(path, encoding="utf-8").read()
    except Exception:  # noqa: BLE001
        return {"unchecked": 0, "next_item": None, "autonomy": None, "max_turns": None,
                "gates": None, "status": None}
    fm = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if fm:
        for line in fm.group(1).splitlines():
            m = re.match(r"\s*autonomy:\s*(\S+)", line)
            if m:
                autonomy = m.group(1).strip()
            m = re.match(r"\s*max_turns:\s*(\d+)", line)
            if m:
                max_turns = int(m.group(1))
            m = re.match(r"\s*gates:\s*(\S+)", line)
            if m:
                gates = m.group(1).strip()
            m = re.match(r"\s*status:\s*(\S+)", line)
            if m:
                status = m.group(1).strip()
    for line in text.splitlines():
        m = UNCHECKED_RE.match(line)
        if m:
            unchecked.append(m.group(1).strip())
    return {"unchecked": len(unchecked), "items": unchecked,
            "next_item": unchecked[0] if unchecked else None,
            "autonomy": autonomy, "max_turns": max_turns, "gates": gates, "status": status}


# --- escalation parking (#709): a task with a pending questionnaire item is PARKED ---
QUESTIONS_DIRNAME = "autopilot-questions"


def _task_of(text):
    """The `task:` front-matter value of a questionnaire item, or None."""
    fm = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    block = fm.group(1) if fm else text
    for line in block.splitlines():
        m = re.match(r"\s*task:\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip()
    return None


def parked_task_ids(cwd):
    """Set of `task:` ids named by pending questionnaire items under
    .claude/state/**/autopilot-questions/*.md (Task 3's escalation output). Recursive so a slashy
    branch (nested state dirs) is covered. Never raises — any scan error yields an empty set
    (fail-open: park nothing, keep driving)."""
    root = os.path.join(cwd or ".", ".claude", "state")
    ids = set()
    try:
        for dirpath, _dirnames, filenames in os.walk(root):
            if os.path.basename(dirpath) != QUESTIONS_DIRNAME:
                continue
            for fn in filenames:
                if not fn.endswith(".md"):
                    continue
                try:
                    text = open(os.path.join(dirpath, fn), encoding="utf-8").read()
                except Exception:  # noqa: BLE001 — an unreadable item can't park; skip it
                    continue
                tid = _task_of(text)
                if tid:
                    ids.add(tid)
    except Exception:  # noqa: BLE001 — fail-open
        pass
    return ids


def _is_parked(box_text, parked_ids):
    """A box is parked iff some parked task-id matches its text on a word boundary — so parked
    `Task 2` parks `Task 2: …` but no longer false-parks `Task 20`. re.escape neutralizes any
    metachar in the id; box_text is the subject, not the pattern (no injection)."""
    return any(tid and re.search(r"\b" + re.escape(tid) + r"\b", box_text, re.I) for tid in parked_ids)


GATE_BOX_RE = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+\S")
GATE_CHECKED_RE = re.compile(r"^\s*[-*]\s+\[[xX]\]\s+\S")
EVIDENCE_RE = re.compile(r"^\s+EVIDENCE:\s*(.*)$")  # indented only — the oracle rejects a column-0 EVIDENCE
PENDING_RE = re.compile(r"(?i)^pending$")


def ledger_unmet(cwd, gates_rel):
    """Is the acceptance-gate ledger complete? Returns True (>=1 gate unmet -> keep driving),
    False (every gate met), or None (ledger unreadable/absent -> fail-open, don't freeze the loop).

    PURE TEXT — never invokes gate-check, so the hook stays node-free (dissolves v1 H1). Mirrors the
    real oracle bin/gate/lib/gates.mjs::gateState: a gate is MET only when its box is [x] AND its
    EVIDENCE: is present, non-empty, and not exactly 'pending'. A checked box with a MISSING or EMPTY
    evidence line is unmet-no-evidence (NOT met) — never let the loop stop on unproven work. Parse
    per-gate (associate each EVIDENCE with its preceding box) so a stray evidence line can't mark a
    different, evidence-less gate as met (silent-failure-hunter Findings 1/2)."""
    path = os.path.join(cwd or ".", gates_rel)
    try:
        text = open(path, encoding="utf-8").read()
    except Exception:  # noqa: BLE001 — fail open, but leave a breadcrumb (Finding 4)
        sys.stderr.write(f"build_loop: gates ledger unreadable ({gates_rel}) — allowing stop.\n")
        return None
    gates = []  # each: [checked: bool, evidence: str|None]
    cur = None
    for line in text.splitlines():
        if GATE_BOX_RE.match(line):
            cur = [bool(GATE_CHECKED_RE.match(line)), None]
            gates.append(cur)
            continue
        m = EVIDENCE_RE.match(line)
        if m and cur is not None:
            cur[1] = m.group(1).strip()
    if not gates:
        # `gates:` points at a readable ledger with no parseable gates -> misconfig; keep driving so a
        # mangled/empty ledger is never read as "done", and surface why (Finding 3).
        sys.stderr.write(f"build_loop: gates ledger has no parseable gates ({gates_rel}) — driving.\n")
        return True
    for checked, ev in gates:
        pending = ev is None or ev == "" or PENDING_RE.match(ev) is not None
        if not checked or pending:
            return True
    return False


def ledger_path(cwd, session_id):
    # Pure path — no dir creation (makedirs lives in _persist so a read never crashes the hook).
    d = os.path.join(cwd or ".", ".claude", "session-logs")
    return os.path.join(d, f"loop-{session_id or 'nosess'}.json")


def _load_ledger(path):
    try:
        return json.load(open(path))
    except Exception:  # noqa: BLE001
        return {"stops": []}


def _persist(path, payload):
    """Write the ledger; return True on success, False on ANY failure. The caller must NOT drive when
    this returns False — an unpersisted stop means the stall/budget/livelock counters can't advance,
    which would drive the loop forever (silent-failure-hunter Finding 1). Fail-open here = don't drive."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(payload, f)
        return True
    except Exception:  # noqa: BLE001
        return False


def _park(cwd, reason):
    """Write the NEEDS-HUMAN.md handback sentinel. ALWAYS surface the reason on stderr first so an
    escalation is never fully silent even if the file write fails (silent-failure-hunter Finding 2)."""
    sys.stderr.write(reason + "\n")
    try:
        d = os.path.join(cwd or ".", ".claude")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "NEEDS-HUMAN.md"), "w") as f:
            f.write(reason + "\n")
    except Exception:  # noqa: BLE001
        pass


def _drive(reason):
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def _terminate_or_drive(cwd, session_id, reason, max_turns, count):
    """Shared terminator tail for BOTH lanes: budget/stall/livelock park, else record + drive.
    Returns 0 on park or an unpersistable stop; _drive() exits 0 on a real drive."""
    sha = (_run(cwd, ["git", "rev-parse", "HEAD"]) or "").strip()
    dirty = bool((_run(cwd, ["git", "status", "--porcelain", "--untracked-files=no"]) or "").strip())
    lp = ledger_path(cwd, session_id)
    ledger = _load_ledger(lp)
    stops = ledger.get("stops", [])

    if max_turns is not None and len(stops) >= max_turns:
        _park(cwd, f"build_loop: budget reached ({max_turns} stops).")
        return 0
    recent = stops[-STALL_N:]
    if len(recent) >= STALL_N and all(
        s.get("sha") == sha and s.get("dirty") == dirty for s in recent
    ):
        _park(cwd, f"build_loop: stalled — no progress across {STALL_N} stops. Handing back to a human.")
        return 0
    fp = hashlib.sha256((reason + sha).encode()).hexdigest()
    if ledger.get("last_fp") == fp and len(stops) >= 2:
        _park(cwd, "build_loop: same block twice, no new commit — possible livelock. Handing back.")
        return 0
    stops.append({"checked": count, "sha": sha, "dirty": dirty})
    if not _persist(lp, {"stops": stops, "last_fp": fp}):
        sys.stderr.write("build_loop: could not persist the loop ledger — not driving "
                         "(stall/budget detection would be blind). Handing back this stop.\n")
        return 0
    _drive(reason)  # prints block + exits 0
    return 0


def parse_todo(path):
    """Parse an ad-hoc todo.md → [{text, checked, verify}]. `- [ ] task | verify: <shell>`:
    a line MAY carry an inline verify command; no `| verify:` = self-attested (tick trusted)."""
    todos = []
    try:
        text = open(path, encoding="utf-8").read()
    except Exception:  # noqa: BLE001 — fail open (caller treats [] as "nothing to drive")
        return []
    for line in text.splitlines():
        m = TODO_BOX_RE.match(line)
        if not m:
            continue
        rest, verify = m.group(2), None
        if "| verify:" in rest:
            rest, v = rest.split("| verify:", 1)
            verify = v.strip()
        todos.append({"text": rest.strip(), "checked": m.group(1) in "xX", "verify": verify})
    return todos


def run_verify(cwd, cmd):
    """Run an inline verify under a pinned PATH (node-dir + /usr/bin:/bin + repo bin/), 8s timeout.
    Returns (ok, detail): ok = exit 0; detail = a truncated failure line (stderr/stdout, or the
    exception) surfaced INTO the re-drive reason so the driven agent knows WHY it failed (e.g.
    `command not found` from the pinned PATH) rather than a blind "fix it". A verify is no more
    privileged than the loop's own agent commands — no hashing, no arm approval."""
    parts = ["/usr/bin", "/bin"]
    node = shutil.which("node")
    if node:
        parts.insert(0, os.path.dirname(node))
    repo_bin = os.path.join(cwd or ".", "bin")
    if os.path.isdir(repo_bin):
        parts.append(repo_bin)
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(parts)
    try:
        r = subprocess.run(["sh", "-c", cmd], cwd=cwd or None, env=env, capture_output=True,
                           text=True, timeout=8, check=False)
    except Exception as e:  # noqa: BLE001 — a verify that can't even run is not "met"
        return False, f"could not run: {e}"
    if r.returncode == 0:
        return True, ""
    return False, (r.stderr or r.stdout or f"exit {r.returncode}").strip()[:200]


def _verify_met(cwd, cmd):
    """Run a verify, retrying ONCE on failure (#613). A ralph verify is inherently non-deterministic
    (curl to a slow-starting server, an 8s timeout on a busy machine, a network blip); re-running the
    eager sweep every stop over a long loop would otherwise let a transient flake drive the agent to
    "fix" a non-bug. Only a DOUBLE failure counts as a real regression. Returns (ok, detail)."""
    ok, _ = run_verify(cwd, cmd)
    if ok:
        return True, ""
    return run_verify(cwd, cmd)  # retry once — a genuine regression fails both times


def ralph_state(cwd):
    """Load .claude/ralph-state.json → dict, or None (absent OR malformed → not in the ralph lane).
    Absent is the normal case (silent); a present-but-corrupt/non-object file leaves a breadcrumb —
    an armed loop silently vanishing is the costliest place to be silent (the walked-away scenario)."""
    path = os.path.join(cwd or ".", RALPH_STATE)
    try:
        s = json.load(open(path))
    except FileNotFoundError:
        return None  # normal — not in the ralph lane
    except Exception:  # noqa: BLE001 — present but unreadable/corrupt: surface it, then degrade
        sys.stderr.write("build_loop: .claude/ralph-state.json present but unreadable/corrupt — "
                         "ignoring; delete it or re-run bin/ralph-arm.\n")
        return None
    if not isinstance(s, dict):  # valid JSON but not an object -> .get() would crash main() (fail-open)
        sys.stderr.write("build_loop: .claude/ralph-state.json is not a JSON object — ignoring.\n")
        return None
    return s


def _write_state(cwd, state):
    try:
        with open(os.path.join(cwd or ".", RALPH_STATE), "w") as f:
            json.dump(state, f)
    except Exception:  # noqa: BLE001 — best-effort session binding; surface so lost cross-session guard is visible
        sys.stderr.write("build_loop: could not persist ralph-state session binding — "
                         "cross-session guard may not stick this run.\n")


def _delete_state(cwd):
    try:
        os.remove(os.path.join(cwd or ".", RALPH_STATE))
    except Exception:  # noqa: BLE001 — self-disarm is best-effort; a ghost file is inert but confusing
        sys.stderr.write("build_loop: completed but could not remove .claude/ralph-state.json — "
                         "delete it manually to fully disarm.\n")


def ralph_lane(cwd, session_id, state):
    """The low-ceremony lane. Session-scoped (TOFU-bound at first stop). Drive on the first unchecked
    box; when all ticked, run each ticked line's optional verify — a failing one re-drives; all
    pass/none → delete the state file (self-disarm) and allow the stop. Returns 0 (or _drive exits)."""
    # Foreign/stale-session states are filtered by main() before we're called (it enters this lane
    # only when the stored session_id is None or == the current session); no guard needed here.
    bound = state.get("session_id")
    todo_rel = state.get("todo")
    todo_path = os.path.join(cwd or ".", todo_rel) if todo_rel else None
    if not todo_path or not os.path.exists(todo_path):
        sys.stderr.write(f"build_loop: ralph todo missing ({todo_rel}) — allowing stop.\n")
        return 0
    todos = parse_todo(todo_path)
    if not todos:
        sys.stderr.write(f"build_loop: ralph todo has no `- [ ]` boxes (or is unreadable): "
                         f"{todo_rel} — allowing stop.\n")
        return 0  # no boxes — nothing to drive, allow stop
    if bound is None:  # trust-on-first-use: bind to the session whose stop first sees this state
        state["session_id"] = session_id
        _write_state(cwd, state)
    max_turns = state.get("max_turns")

    # Eager per-item verify (#613): re-check every already-ticked box's verify FIRST — so a regression
    # in a done item (a dead server, a deleted file) is caught before more work piles on top of it,
    # not only at the very end. A failing one re-drives the fix ahead of any new work. This subsumes
    # the old end-of-list sweep: when all boxes are ticked, this loop verifies them all.
    for t in todos:
        if t["checked"] and t["verify"]:
            ok, detail = _verify_met(cwd, t["verify"])
            if not ok:
                tail = f" ({detail})" if detail else ""
                reason = (f"build_loop (ralph) ⛔ — verify regressed for a done item: {t['text']}{tail}. "
                          "Fix it, then continue. To hand back to a human, create .claude/NEEDS-HUMAN.md.")
                return _terminate_or_drive(cwd, session_id, reason, max_turns, 0)

    unchecked = [t for t in todos if not t["checked"]]
    if unchecked:
        reason = (f"build_loop (ralph) ⛔ — todo not complete. Next unchecked item: "
                  f"{unchecked[0]['text']}. Continue with it; when done, tick its box. "
                  "To hand back to a human, create .claude/NEEDS-HUMAN.md.")
        return _terminate_or_drive(cwd, session_id, reason, max_turns, len(unchecked))

    _delete_state(cwd)  # all boxes ticked AND every verify passed above — complete, self-disarm
    return 0


def plan_loop_foreign(cwd, session_id, plan_relpath):
    """TOFU session-binding for the plan lane (mirrors the ralph lane's session-scoping — #775).
    Store .claude/state/plan-loop.json = {"plan": <relpath>, "session_id": <sid>}. Returns True (a
    DIFFERENT session owns this unattended plan's loop -> allow the stop, don't gate) or False (this
    session owns it, or just (re)bound it -> proceed). Plan-keyed: a new plan (relpath != stored) or a
    stored None sid counts as unbound and (re)binds to this session. Fail-open on IO error (proceed)."""
    path = os.path.join(cwd or ".", PLAN_LOOP_STATE)
    state = None
    try:
        state = json.load(open(path))
        if not isinstance(state, dict):
            state = None
    except FileNotFoundError:
        pass  # absent — normal first-run / TOFU path, silent (re)bind below
    except Exception:  # noqa: BLE001 — corrupt JSON / unreadable: breadcrumb, then (re)bind (fail-open)
        sys.stderr.write("build_loop: plan-loop.json unreadable or corrupt — rebinding session loop.\n")
        state = None
    if state is None or state.get("plan") != plan_relpath or state.get("session_id") is None:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump({"plan": plan_relpath, "session_id": session_id}, f)
        except Exception:  # noqa: BLE001 — best-effort bind; surface, then proceed (fail-open)
            sys.stderr.write("build_loop: could not persist plan-loop session binding — "
                             "cross-session guard may not stick this run.\n")
        return False  # (re)bound to this session -> proceed
    return state.get("session_id") != session_id  # non-None + plan matches -> foreign iff a different sid


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0
    cwd = data.get("cwd") or "."
    session_id = data.get("session_id")

    if os.path.exists(os.path.join(cwd, ".claude", "NEEDS-HUMAN.md")):
        return 0  # clean handback

    # Ralph lane first: an ad-hoc todo loop armed via .claude/ralph-state.json takes precedence over
    # the plan lane. Session-scoped, so a foreign/stale state is ignored (returns 0, plan lane below).
    rstate = ralph_state(cwd)
    if rstate is not None and (rstate.get("session_id") in (None, session_id)):
        return ralph_lane(cwd, session_id, rstate)

    plan_path = resolve_plan(cwd)
    if not plan_path:
        return 0
    plan = parse_plan(plan_path)
    if plan["autonomy"] != "unattended":
        return 0
    # #776: a plan explicitly marked done/abandoned is not active — allow the stop (a stale unchecked
    # box on a merged, finished plan must not be a tripwire). No `status:` key stays active.
    if plan.get("status") in ("done", "abandoned"):
        return 0

    # Session-scope the plan lane (#775): bind this unattended plan's loop to one session (TOFU); a
    # different session's stop is not gated — a merged foreign plan can't hijack unrelated sessions.
    if plan_loop_foreign(cwd, session_id, os.path.relpath(plan_path, cwd or ".")):
        return 0

    # Decide WHY we'd drive: unchecked plan boxes first, then unmet acceptance gates. When every plan
    # box is ticked but a `gates:` ledger still has an unmet gate, "done" isn't earned — keep driving.
    if plan["unchecked"] > 0:
        # Skip PARKED tasks (a pending questionnaire item names them — #709). Drive the first
        # un-parked box; if EVERY remaining unchecked box is parked, stop cleanly (no drive).
        parked = parked_task_ids(cwd)
        unparked = [b for b in plan["items"] if not _is_parked(b, parked)]
        if not unparked:
            sys.stderr.write("build_loop: %d task(s) awaiting your questionnaire answers — stopping "
                             "cleanly (each is parked; a pending questionnaire item names it).\n"
                             % plan["unchecked"])
            return 0
        reason = (f"build_loop ⛔ — plan not complete. Next unchecked item: {unparked[0]}. "
                  "Continue with it; when proven, tick its box. To hand back to a human, create .claude/NEEDS-HUMAN.md.")
        count = len(unparked)
    else:
        gates_rel = plan.get("gates")
        if not gates_rel:
            return 0  # all boxes ticked, no acceptance ledger -> complete (backward-compatible)
        unmet = ledger_unmet(cwd, gates_rel)
        if unmet is None or unmet is False:
            return 0  # unreadable/absent/no-gates (fail-open) OR every gate met -> allow stop
        reason = (f"build_loop ⛔ — plan boxes ticked but acceptance gates unmet. "
                  f"Run `claude-template gate-run verify {gates_rel}` to re-verify, fix any RED gate, then stop. "
                  "To hand back to a human, create .claude/NEEDS-HUMAN.md.")
        count = plan["unchecked"]

    return _terminate_or_drive(cwd, session_id, reason, plan["max_turns"], count)


if __name__ == "__main__":
    sys.exit(main())

"""One docs map — DOCS_GLOBS / DOCS_HISTORICAL — read by `docs_gate` and the H6 commit-docs
reminder (D1, cloud-parity train 2 / docs-impact-design spec part A). Two keys in the existing
`.claude/worktrees.conf`, not a new config file (R4).

`DOCS_GLOBS` is what counts as documentation (space-separated fnmatch-style globs, `**` allowed).
`DOCS_HISTORICAL` is point-in-time records — never reported as stale, and never a doc for gating
purposes even when a `DOCS_GLOBS` entry would also match it (e.g. `docs/**/*.md` matches
`docs/superpowers/specs/x.md`, but that path is historical, so `is_doc` returns False for it).

Precedence (globs): env `DOCS_GLOBS` > `.claude/worktrees.conf` `DOCS_GLOBS=` > env/conf
`DOCS_GATE_DOCS_GLOBS` (deprecated alias — the pre-D1 override name) > `DEFAULT_GLOBS`.
Precedence (historical): env `DOCS_HISTORICAL` > conf `DOCS_HISTORICAL=` > `DEFAULT_HISTORICAL`.
"""

import os
import re

DEFAULT_GLOBS = ("README.md", "CLAUDE.md", "docs/**/*.md")
DEFAULT_HISTORICAL = (
    "docs/superpowers/**", "docs/decisions/**", "docs/archived/**", "docs/lessons*.md",
)

_CONF_KEYS = ("DOCS_GLOBS", "DOCS_HISTORICAL", "DOCS_GATE_DOCS_GLOBS")


def _glob_to_regex(glob):
    """Translate an fnmatch-style glob to a regex, with `**` support fnmatch lacks: `**/` matches
    any number of whole path segments (incl. zero), a lone `*` matches within one segment only."""
    out = []
    i, n = 0, len(glob)
    while i < n:
        c = glob[i]
        if c == "*":
            if glob[i:i + 2] == "**":
                if i + 2 < n and glob[i + 2] == "/":
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
            continue
        if c == "?":
            out.append("[^/]")
            i += 1
            continue
        out.append(re.escape(c))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def _match(path, glob):
    return _glob_to_regex(glob).match(path) is not None


def is_doc(path, globs, historical=()):
    """True if `path` counts as documentation under `globs` — unless it also matches a
    `historical` glob, in which case it is never a doc for gating purposes."""
    norm = path.replace("\\", "/")
    if any(_match(norm, h) for h in historical):
        return False
    return any(_match(norm, g) for g in globs)


def doc_tree_roots(globs):
    """Directory roots implied by a `**`-rooted glob (e.g. `docs/**/*.md` -> `docs/`). A path
    under one of these roots is neither source nor doc for the H6 staleness heuristic, even when
    it doesn't itself match any glob (e.g. a non-`.md` asset under `docs/`) — it belongs to a doc
    tree, not to product code. Only a glob whose FIRST wildcard is a `**` right after a `/` counts;
    `plugins/*/docs/**/*.md` does not (its first wildcard is a single `*` spanning the whole
    `plugins/` tree, not a doc-tree root) — so this never over-excludes product code."""
    roots = []
    for g in globs:
        idx = next((i for i, c in enumerate(g) if c in "*?"), -1)
        if idx <= 0 or not g[:idx].endswith("/") or g[idx:idx + 2] != "**":
            continue
        roots.append(g[:idx])
    return roots


def is_source_excluded(path, globs, historical):
    """True if `path` must never count as "source" for the H6 docs-staleness heuristic: it matches
    `DOCS_HISTORICAL`, or sits under a doc-tree root implied by `DOCS_GLOBS` (see `doc_tree_roots`).
    Either way it's "neither source nor doc" — not a signal that product code changed without a
    docs update."""
    norm = path.replace("\\", "/")
    if any(_match(norm, h) for h in historical):
        return True
    return any(norm.startswith(r) for r in doc_tree_roots(globs))


def _split(raw):
    return raw.replace(",", " ").split()


def _read_conf(cwd):
    conf_path = os.path.join(cwd or ".", ".claude", "worktrees.conf")
    try:
        with open(conf_path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        text = ""
    out = {}
    for key in _CONF_KEYS:
        m = re.search(r'^' + key + r'\s*=\s*"?([^"\n]*)"?', text, re.MULTILINE)
        out[key] = m.group(1).strip() if m else ""
    return out


def load(cwd):
    """Returns (globs: list[str], historical: list[str]) per the precedence above."""
    conf = _read_conf(cwd)

    globs_raw = os.environ.get("DOCS_GLOBS")
    if globs_raw is None:
        globs_raw = conf["DOCS_GLOBS"]
    if not globs_raw.strip():
        alias = os.environ.get("DOCS_GATE_DOCS_GLOBS")
        if alias is None:
            alias = conf["DOCS_GATE_DOCS_GLOBS"]
        globs_raw = alias

    historical_raw = os.environ.get("DOCS_HISTORICAL")
    if historical_raw is None:
        historical_raw = conf["DOCS_HISTORICAL"]

    globs = _split(globs_raw) if globs_raw and globs_raw.strip() else list(DEFAULT_GLOBS)
    historical = (
        _split(historical_raw) if historical_raw and historical_raw.strip() else list(DEFAULT_HISTORICAL)
    )
    return globs, historical

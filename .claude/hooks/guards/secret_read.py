"""H11 — block reading an obviously-secret file, via a shell dumper or the Read tool (hook
consolidation PR 5)."""

import os

from _lib.shell import SHELL_SEGMENT_SPLIT_RE, _process_env_override, _segment_has_leading_override, _strip_leading_tokens
from guards.secret_file import _is_secret_filename


# H11 — secret-read guard (#506): block READING an obviously-secret file, both via the Read tool and
# via a shell dumper (`cat .env`, `head ~/.ssh/id_rsa`). Complements H10 (which blocks STAGING a
# secret file): H10 stops secrets going OUT through git, H11 stops them coming IN to the model's
# context. Purely additive — it can only ever ADD a block. Override for one command/read with
# CT_ALLOW_SECRET_READ=1 (segment-scoped for Bash, process-env for the Read tool).
SECRET_READ_BASENAMES = frozenset({
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "credentials", ".netrc", ".pgpass", ".npmrc",
})


SECRET_READ_EXTS = (".p12", ".pfx", ".ppk")  # .pem/.key already caught by _is_secret_filename


SECRET_READ_DIR_MARKERS = ("/.aws/", "/.ssh/", "/.gnupg/")


# Shell commands that dump a file's CONTENTS to stdout (and thus into context).
# ponytail: best-effort denylist for the CASUAL/accidental case. It does NOT contain a
# hostile agent: any non-listed reader (grep/awk/sed/cut/sort/dd, python -c, sh -c, `<`
# redirection, `cat *` glob, symlinks) bypasses it. The Read-tool leg is the real gate;
# H10 (secret-file staging) owns the egress boundary. Widen toward reader-detection: #521-followup.
SECRET_READ_CMDS = frozenset({
    "cat", "bat", "less", "more", "head", "tail", "nl", "tac",
    "xxd", "od", "hexdump", "strings", "base64",
})


def _is_secret_read_path(path: str) -> bool:
    """True if `path` names an obviously-secret file (reuses H10's `_is_secret_filename` for
    .env*/*.pem/*.key/id_rsa/credentials.json, plus extra key/credential names + ~/.aws|.ssh|.gnupg
    dirs). `*.pub` public keys are explicitly NOT secret."""
    if not path:
        return False
    p = path.strip().strip("\"'")
    if not p:
        return False
    base_lower = os.path.basename(p).lower()
    if base_lower.endswith(".pub"):
        return False
    if _is_secret_filename(p):
        return True
    if base_lower in SECRET_READ_BASENAMES:
        return True
    if base_lower.endswith(SECRET_READ_EXTS):
        return True
    norm = "/" + p.replace("\\", "/").lstrip("/")
    return any(marker in norm for marker in SECRET_READ_DIR_MARKERS)


def _check_secret_read(command: str):
    """H11 — block a shell dumper (`cat`/`head`/`base64`/…) reading a secret file into context."""
    if not command.strip():
        return
    for segment in SHELL_SEGMENT_SPLIT_RE.split(command):
        raw = segment.strip()
        if not raw:
            continue
        if _segment_has_leading_override(raw, "CT_ALLOW_SECRET_READ"):
            continue
        seg = _strip_leading_tokens(raw).strip()
        toks = seg.split()
        if not toks:
            continue
        exe = os.path.basename(toks[0])
        if exe not in SECRET_READ_CMDS:
            continue
        for tok in toks[1:]:
            if tok.startswith("-"):
                continue
            if _is_secret_read_path(tok):
                return (
                    f"Blocked: reading secret file '{tok}' via {exe} would pull credentials into "
                    "context (H11). Read only the specific non-secret value you need, or override "
                    "this one command with CT_ALLOW_SECRET_READ=1 <cmd>."
                )


def check_bash(ctx):
    return _check_secret_read(ctx.command)


def check_read(ctx):
    # H11 — reading a secret file pulls credentials into context. Process-env override
    # only (the Read tool carries no shell segment to lead with an assignment).
    file_path = ctx.tool_input.get("file_path", "")
    if _is_secret_read_path(file_path) and not _process_env_override("CT_ALLOW_SECRET_READ"):
        return (
            f"Blocked: {file_path} looks like a secret file — reading it pulls credentials into "
            "context (H11). Read only the specific non-secret value you need, or set "
            "CT_ALLOW_SECRET_READ=1 in the hook environment to override."
        )
    return None

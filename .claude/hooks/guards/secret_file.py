"""H10 — block staging an obviously-secret FILE by name (hook consolidation PR 5)."""

import os

from _lib.git import GIT_ADD_RE, GIT_COMMIT_INVOCATION_RE, _add_command_targets, _resolve_git_cwd, _staged_names
from _lib.shell import SHELL_SEGMENT_SPLIT_RE, _process_env_override, _segment_has_leading_override


# H10 — secret-file staging: block staging an obviously-secret FILE by NAME (complements H3, which
# scans staged diff CONTENT — H10 catches the file itself). MED fix: `.env*` is now an ALLOW-LIST
# (deny everything starting with `.env`, case-insensitively, EXCEPT these known-safe suffixes) —
# was an allow-by-default denylist that missed `.env.local`/`.env.production`/`.ENV`. Override
# CT_ALLOW_SECRET_FILE=1 (segment-scoped).
SECRET_FILENAME_ALLOW = (".env.example", ".env.sample", ".env.test")


def _is_secret_filename(path: str) -> bool:
    """Case-insensitive throughout (MED fix — `.ENV` must deny same as `.env`)."""
    base_lower = os.path.basename(path).lower()
    if base_lower.startswith(".env"):
        # MED fix: ALLOW-LIST, not a denylist — every `.env*` is secret EXCEPT these known-safe
        # suffixes, so `.env.local`/`.env.production`/etc. (anything not explicitly allow-listed)
        # denies. The old version only denied the bare `.env` name, missing every real-world
        # per-environment variant.
        return base_lower not in SECRET_FILENAME_ALLOW
    if base_lower.endswith(".pem"):
        return True
    if base_lower == "id_rsa":
        return True
    if base_lower.endswith(".key"):
        return True
    if base_lower == "credentials.json":
        return True
    if "service-account" in base_lower and base_lower.endswith(".json"):
        return True
    return False


def _check_secret_file_staging(command: str, cwd: str):
    if _process_env_override("CT_ALLOW_SECRET_FILE"):
        return
    for segment in SHELL_SEGMENT_SPLIT_RE.split(command):
        if GIT_ADD_RE.search(segment):
            for path in _add_command_targets(segment, cwd):
                if not _is_secret_filename(path):
                    continue
                if _segment_has_leading_override(segment, "CT_ALLOW_SECRET_FILE"):
                    continue
                return (
                    f"Blocked: '{path}' looks like a secret file (.env/*.pem/id_rsa/*.key/"
                    "credentials.json/*service-account*.json) — don't stage it. Set "
                    "CT_ALLOW_SECRET_FILE=1 to override."
                )
        elif GIT_COMMIT_INVOCATION_RE.search(segment):  # #237: `git -C <p> commit` too
            for path in _staged_names(_resolve_git_cwd(segment, cwd)):  # #237: -C target's index
                if not _is_secret_filename(path):
                    continue
                if _segment_has_leading_override(segment, "CT_ALLOW_SECRET_FILE"):
                    continue
                return (
                    f"Blocked: staged file '{path}' looks like a secret file (.env/*.pem/id_rsa/"
                    "*.key/credentials.json/*service-account*.json). Set "
                    "CT_ALLOW_SECRET_FILE=1 to override."
                )


def check(ctx):
    return _check_secret_file_staging(ctx.command, ctx.cwd)

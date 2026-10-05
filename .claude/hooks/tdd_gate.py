#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Retired by hook consolidation PR 6 — runs ONLY the `tdd_gate` checks of pre_tool.py, in this
hook's old output form, so a repo still wired to this name behaves exactly as before. Removed in the
post-propagate cleanup."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -P / PYTHONSAFEPATH (PR 5 grill C2)
from pre_tool import main  # noqa: E402

sys.exit(main(only="tdd_gate"))

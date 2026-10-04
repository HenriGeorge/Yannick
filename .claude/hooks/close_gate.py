#!/usr/bin/env python3
# dependencies = []
"""Retired by hook consolidation PR 7 — runs ONLY the `close_gate` module of stop_gate.py, so a repo
still wired to this name behaves as before. Removed in the post-propagate cleanup."""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from stop_gate import main  # noqa: E402

sys.exit(main(only="close_gate"))

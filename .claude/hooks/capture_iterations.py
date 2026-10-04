#!/usr/bin/env python3
# dependencies = []
"""Retired by hook consolidation PR 4 — runs ONLY the `capture_iterations` module of telemetry.py, so a repo
still wired to this name behaves exactly as before. Removed in the post-propagate cleanup."""
import sys

from telemetry import main

sys.exit(main(only="capture_iterations"))

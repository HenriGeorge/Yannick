#!/usr/bin/env python3
# dependencies = []
"""Retired by hook consolidation PR 4 — runs ONLY the `merge_autoff` module of post_nudges.py, so a repo
still wired to this name behaves exactly as before. Removed in the post-propagate cleanup."""
import sys

from post_nudges import main

sys.exit(main(only="merge_autoff"))

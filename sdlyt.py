#!/usr/bin/env python3
"""Thin entry point kept for compatibility with ``python sdlyt.py``."""
from __future__ import annotations

import sys

from sdlyt.launcher import main

if __name__ == "__main__":
    sys.exit(main())
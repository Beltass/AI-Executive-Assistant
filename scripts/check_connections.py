#!/usr/bin/env python3
"""Convenience wrapper to run all integration connection checks.

Equivalent to ``python -m ai_assistant.health`` but runnable directly:

    python scripts/check_connections.py
"""

import os
import sys

# Make ``src/`` importable when running the script from the repo root.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from ai_assistant.health import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

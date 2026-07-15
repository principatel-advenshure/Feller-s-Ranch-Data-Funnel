"""
Shared pytest configuration.

Ensures the repository root is importable so tests can do
`from extract... import ...` / `from load... import ...` regardless of
the directory pytest is invoked from.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

"""Root shim for the ``rankstein`` CLI.

Usage:
    python rankstein.py add-domain <domain>
    python rankstein.py list-domains
    python rankstein.py show-domain <handle>
    python rankstein.py run --domain <handle>

This file exists so the project can be invoked as a single command from
the project root without users needing to remember ``python -m
rankstein.cli``. Real logic lives in ``rankstein/cli.py``.
"""

from __future__ import annotations

import sys

from rankstein.cli import main

if __name__ == "__main__":
    sys.exit(main())

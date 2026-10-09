"""One article-remaster child per domain and event loop in this process.

The CLI can import its worker again under its package name during late
reconciliation. Keeping the guard here makes both module identities share
the same lock; the browser-profile lease still protects other processes.
"""

from __future__ import annotations

import asyncio
from weakref import WeakKeyDictionary

_LOOP_LOCKS: WeakKeyDictionary = WeakKeyDictionary()


def article_campaign_lock(domain_handle: str) -> asyncio.Lock:
    handle = str(domain_handle).strip().casefold()
    if not handle:
        raise ValueError("Article campaign lock requires a domain handle")
    loop = asyncio.get_running_loop()
    locks = _LOOP_LOCKS.setdefault(loop, {})
    return locks.setdefault(handle, asyncio.Lock())

from __future__ import annotations

import asyncio

import pytest

from rankstein.campaign_guard import article_campaign_lock


@pytest.mark.unit
@pytest.mark.asyncio
async def test_campaign_guard_is_shared_for_normalized_domain_only() -> None:
    lock = article_campaign_lock(" RecetaDolce ")
    assert lock is article_campaign_lock("recetadolce")
    assert lock is not article_campaign_lock("recetagenial")
    with pytest.raises(ValueError):
        article_campaign_lock(" ")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_campaign_guard_serializes_same_domain_without_blocking_other_domains() -> None:
    release = asyncio.Event()
    started = asyncio.Event()
    entered = []

    async def campaign(handle):
        async with article_campaign_lock(handle):
            entered.append(handle)
            started.set()
            await release.wait()

    first = asyncio.create_task(campaign("one"))
    await started.wait()
    second = asyncio.create_task(campaign("one"))
    other = asyncio.create_task(campaign("two"))
    await asyncio.sleep(0)
    assert entered == ["one", "two"]
    release.set()
    await asyncio.gather(first, second, other)
    assert entered == ["one", "two", "one"]

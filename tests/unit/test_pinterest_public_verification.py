from __future__ import annotations

from types import SimpleNamespace

import pytest

from pinterest_automation.pinterest_driver import PinterestDriver


class FakeResponse:
    def __init__(self, body: str, status: int = 200) -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body


class FakeRequest:
    def __init__(self, title: str, link: str) -> None:
        self.title = title
        self.link = link

    async def get(self, url: str, **kwargs):
        if url.endswith("/mediacomaas/"):
            return FakeResponse(f'/pin/1148488342513342707/ "{self.title}"')
        if url.endswith("/pin/1148488342513342707/"):
            return FakeResponse(f'"title":"{self.title}" "link":"{self.link}"')
        return FakeResponse("", status=404)


def _driver(monkeypatch) -> PinterestDriver:
    monkeypatch.setenv("PINTEREST_PUBLIC_USERNAME_MAP", '{"media":"mediacomaas"}')
    driver = object.__new__(PinterestDriver)
    driver.config = SimpleNamespace(accounts={})
    driver._session = None
    driver.account_handle = "media"
    driver._logger = None
    driver.info = lambda *args, **kwargs: None
    driver.debug = lambda *args, **kwargs: None
    return driver


@pytest.mark.unit
@pytest.mark.asyncio
async def test_uncertain_publish_is_verified_by_exact_public_pin(monkeypatch) -> None:
    title = "Ensalada de garbanzos crujientes"
    link = "https://recetagenial.com/ensalada-de-garbanzos-crujientes"
    page = SimpleNamespace(context=SimpleNamespace(request=FakeRequest(title, link)))

    pin_id = await _driver(monkeypatch)._verify_recent_public_pin(
        page,
        title=title,
        link=link,
        account_handle="media",
    )

    assert pin_id == "1148488342513342707"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_public_pin_with_wrong_destination_is_rejected(monkeypatch) -> None:
    title = "Ensalada de garbanzos crujientes"
    page = SimpleNamespace(
        context=SimpleNamespace(request=FakeRequest(title, "https://recetagenial.com/another-article"))
    )

    pin_id = await _driver(monkeypatch)._verify_recent_public_pin(
        page,
        title=title,
        link="https://recetagenial.com/ensalada-de-garbanzos-crujientes",
        account_handle="media",
    )

    assert pin_id is None

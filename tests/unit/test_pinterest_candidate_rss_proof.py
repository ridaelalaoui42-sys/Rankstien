"""Creation-candidate RSS proof must bind identity, ownership and publication time."""

from __future__ import annotations

import asyncio
import unicodedata
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from html import escape
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from pinterest_automation.pinterest_driver import PinterestDriver

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

CANDIDATE = "1148488342519896651"
OTHER_PIN = "1148488342513342707"
PIN_URL = f"https://www.pinterest.com/pin/{CANDIDATE}/"
OTHER_PIN_URL = f"https://www.pinterest.com/pin/{OTHER_PIN}/"
FEED_URL = "https://www.pinterest.com/mediacomaas/feed.rss"
TITLE = "Croquetas Caseras"
DESCRIPTION = "Receta casera cremosa"
DESTINATION = "https://example.test/recipe"
OWNER_URL = "https://www.pinterest.com/mediacomaas/"


@pytest.fixture
def candidate_driver():
    now = datetime.now(UTC).replace(microsecond=0)
    driver = object.__new__(PinterestDriver)
    driver.config = SimpleNamespace(accounts={})
    driver.info = Mock()
    driver.debug = Mock()
    driver._public_username = Mock(return_value="mediacomaas")
    driver._pin_create_event = asyncio.Event()
    driver._pin_create_data = {
        "pin_id": CANDIDATE,
        "generation_started_at": (now - timedelta(seconds=60)).timestamp(),
        "observed_at": (now - timedelta(seconds=30)).timestamp(),
    }
    driver._verify_recent_public_pin = AsyncMock(side_effect=AssertionError("No profile discovery"))
    return driver, now


def _public_html(*, source=DESTINATION, pinner=OWNER_URL, extra_tags=""):
    # Pinterest streams the exact ownership/source tags after the page body;
    # its SEO tags can still describe an older canonical pin.
    tags = []
    for key, value in (("pinterestapp:source", source), ("pinterestapp:pinner", pinner)):
        if value is not None:
            tags.append(f'<meta property="{key}" content="{escape(value, quote=True)}">')
    return (
        '<html><head><meta property="og:title" content="Otra receta">'
        f'<meta property="og:url" content="{OTHER_PIN_URL}">'
        f'<link rel="canonical" href="{OTHER_PIN_URL}"></head>'
        f"<body>{TITLE} {DESCRIPTION} {DESTINATION} {OWNER_URL}</body>"
        + "".join(tags)
        + extra_tags
        + "</html>"
    )


def _rss(now, *, title=TITLE, link=PIN_URL, guid=PIN_URL, pub_date="default", body=""):
    if pub_date == "default":
        pub_date = format_datetime(now - timedelta(seconds=40), usegmt=True)
    date_tag = "" if pub_date is None else f"<pubDate>{escape(pub_date)}</pubDate>"
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>mediacomaas</title><link>{OWNER_URL}</link><item>"
        f"<title>{escape(title)}</title><link>{escape(link)}</link>"
        f'<guid isPermaLink="true">{escape(guid)}</guid>{date_tag}'
        f"<description>{escape(body)}</description></item></channel></rss>"
    )


def _page(now, *, html=None, rss=None, pin_status=200, pin_url=PIN_URL, feed_status=200, feed_url=FEED_URL):
    pin = SimpleNamespace(
        status=pin_status,
        url=pin_url,
        text=AsyncMock(return_value=_public_html() if html is None else html),
    )
    feed = SimpleNamespace(
        status=feed_status,
        url=feed_url,
        text=AsyncMock(return_value=_rss(now) if rss is None else rss),
    )
    request = SimpleNamespace(get=AsyncMock(side_effect=[pin, feed]))
    return SimpleNamespace(context=SimpleNamespace(request=request)), pin, feed


async def _verify(driver, page, *, title=TITLE, description=DESCRIPTION):
    result = await driver._verify_intercepted_public_pin(
        page,
        title=title,
        link=DESTINATION,
        account_handle="media",
        description=description,
    )
    driver._verify_recent_public_pin.assert_not_awaited()
    return result


def _assert_feed_requests(page):
    assert [call.args[0] for call in page.context.request.get.await_args_list] == [PIN_URL, FEED_URL]


def _assert_bounded_diagnostic(driver):
    diagnostic = driver._pin_candidate_verification
    assert isinstance(diagnostic, dict)
    assert 3 <= len(diagnostic) <= 32
    assert isinstance(diagnostic.get("reason"), str) and diagnostic["reason"]
    assert isinstance(diagnostic.get("method"), str) and diagnostic["method"]
    assert any(isinstance(value, bool) for value in diagnostic.values())
    assert all(not isinstance(value, str) or len(value) <= 200 for value in diagnostic.values())


async def test_fresh_description_receipt_proves_only_intercepted_id_despite_other_seo_canonical(
    candidate_driver,
):
    driver, now = candidate_driver
    page, _pin, _feed = _page(now, rss=_rss(now, title=DESCRIPTION))

    result = await _verify(driver, page)

    assert result == CANDIDATE
    assert result != OTHER_PIN
    _assert_feed_requests(page)
    _assert_bounded_diagnostic(driver)


@pytest.mark.parametrize("description", ["", None])
async def test_exact_queued_title_receipt_does_not_require_optional_description(
    candidate_driver, description
):
    driver, now = candidate_driver
    page, _pin, _feed = _page(now)

    assert await _verify(driver, page, description=description) == CANDIDATE
    _assert_feed_requests(page)


async def test_receipt_title_normalizes_case_whitespace_nfc_and_queued_title_truncation(candidate_driver):
    driver, now = candidate_driver
    queued_title = unicodedata.normalize("NFD", "Croquetas fáciles " + "muy cremosas " * 12)
    receipt_title = unicodedata.normalize("NFC", queued_title[:100]).upper().replace(" ", "  ")
    page, _pin, _feed = _page(now, rss=_rss(now, title=receipt_title))

    assert await _verify(driver, page, title=queued_title) == CANDIDATE
    _assert_feed_requests(page)


@pytest.mark.parametrize("offset", [-65, -25])
async def test_publication_time_allows_only_five_second_generation_boundary_slack(candidate_driver, offset):
    driver, now = candidate_driver
    published = format_datetime(now + timedelta(seconds=offset), usegmt=True)
    page, _pin, _feed = _page(now, rss=_rss(now, pub_date=published))

    assert await _verify(driver, page) == CANDIDATE


@pytest.mark.parametrize("offset", [-66, -24, -3600])
async def test_publication_time_outside_current_generation_is_rejected(candidate_driver, offset):
    driver, now = candidate_driver
    published = format_datetime(now + timedelta(seconds=offset), usegmt=True)
    page, _pin, _feed = _page(now, rss=_rss(now, pub_date=published))

    assert await _verify(driver, page) is None
    _assert_feed_requests(page)
    _assert_bounded_diagnostic(driver)


@pytest.mark.parametrize("pub_date", [None, "not a date", "Fri, 16 Oct 2026 12:00:00"])
async def test_receipt_without_aware_rfc_publication_date_is_rejected(candidate_driver, pub_date):
    driver, now = candidate_driver
    page, _pin, _feed = _page(now, rss=_rss(now, pub_date=pub_date))

    assert await _verify(driver, page) is None
    _assert_feed_requests(page)


@pytest.mark.parametrize("field", ["link", "guid"])
async def test_both_receipt_identity_fields_must_name_current_candidate(candidate_driver, field):
    driver, now = candidate_driver
    page, _pin, _feed = _page(now, rss=_rss(now, **{field: OTHER_PIN_URL}))

    assert await _verify(driver, page) is None
    _assert_feed_requests(page)


@pytest.mark.parametrize("field", ["link", "guid"])
async def test_receipt_identity_cannot_be_substring_or_foreign_host(candidate_driver, field):
    driver, now = candidate_driver
    forged = f"https://www.pinterest.com.evil.invalid/pin/{CANDIDATE}/"
    page, _pin, _feed = _page(now, rss=_rss(now, **{field: forged}))

    assert await _verify(driver, page) is None


@pytest.mark.parametrize("receipt_title", ["Otra receta", TITLE + " extra", DESCRIPTION + " extra", ""])
async def test_rss_body_mentions_or_title_substrings_do_not_prove_receipt(candidate_driver, receipt_title):
    driver, now = candidate_driver
    body = f"{TITLE} {DESCRIPTION} {DESTINATION} {PIN_URL}"
    page, _pin, _feed = _page(now, rss=_rss(now, title=receipt_title, body=body))

    assert await _verify(driver, page) is None
    _assert_feed_requests(page)


@pytest.mark.parametrize(
    "feed_url",
    [
        "https://www.pinterest.com/anotheraccount/feed.rss",
        "http://www.pinterest.com/mediacomaas/feed.rss",
        "https://www.pinterest.com.evil.invalid/mediacomaas/feed.rss",
        FEED_URL + "?owner=mediacomaas",
    ],
)
async def test_redirected_or_nonexact_owner_feed_is_rejected(candidate_driver, feed_url):
    driver, now = candidate_driver
    page, _pin, _feed = _page(now, feed_url=feed_url)

    assert await _verify(driver, page) is None
    _assert_feed_requests(page)


@pytest.mark.parametrize("feed_status", [403, 404, 500])
async def test_unsuccessful_feed_http_status_is_rejected(candidate_driver, feed_status):
    driver, now = candidate_driver
    page, _pin, feed = _page(now, feed_status=feed_status)

    assert await _verify(driver, page) is None
    feed.text.assert_not_awaited()


async def test_invalid_feed_xml_is_rejected_without_profile_discovery(candidate_driver):
    driver, now = candidate_driver
    page, _pin, _feed = _page(now, rss=f"<rss><item>{TITLE} {PIN_URL}")

    assert await _verify(driver, page) is None
    _assert_feed_requests(page)


@pytest.mark.parametrize(
    "fields",
    [
        {"source": None},
        {"source": DESTINATION + "/"},
        {"source": "https://other.test/?next=" + DESTINATION},
        {"pinner": None},
        {"pinner": "https://www.pinterest.com/anotheraccount/"},
        {"pinner": OWNER_URL + "boards/"},
        {"pinner": "https://www.pinterest.com.evil.invalid/mediacomaas/"},
        {"extra_tags": '<meta property="pinterestapp:source" content="https://other.test/recipe">'},
        {"extra_tags": '<meta property="pinterestapp:pinner" content="https://www.pinterest.com/another/">'},
    ],
)
async def test_missing_wrong_or_conflicting_exact_source_and_owner_cannot_fetch_rss(candidate_driver, fields):
    driver, now = candidate_driver
    page, _pin, feed = _page(now, html=_public_html(**fields))

    assert await _verify(driver, page) is None
    assert page.context.request.get.await_count == 1
    feed.text.assert_not_awaited()


@pytest.mark.parametrize(
    "pin_url",
    [OTHER_PIN_URL, PIN_URL + "?candidate=" + CANDIDATE, "https://example.test/pin/" + CANDIDATE + "/"],
)
async def test_public_response_must_resolve_to_exact_candidate_before_fetching_rss(candidate_driver, pin_url):
    driver, now = candidate_driver
    page, _pin, feed = _page(now, pin_url=pin_url)

    assert await _verify(driver, page) is None
    assert page.context.request.get.await_count == 1
    feed.text.assert_not_awaited()


@pytest.mark.parametrize("missing_field", ["generation_started_at", "observed_at", "both"])
async def test_candidate_without_creation_timestamps_never_fetches_rss(candidate_driver, missing_field):
    driver, now = candidate_driver
    if missing_field == "both":
        driver._pin_create_data = {"pin_id": CANDIDATE}
    else:
        del driver._pin_create_data[missing_field]
    page, _pin, feed = _page(now)

    assert await _verify(driver, page) is None
    assert page.context.request.get.await_count <= 1
    assert all(call.args[0] == PIN_URL for call in page.context.request.get.await_args_list)
    feed.text.assert_not_awaited()


@pytest.mark.parametrize(
    "case",
    ["stale", "future", "reversed", "nan", "infinite", "boolean", "numeric_string"],
)
async def test_invalid_or_stale_creation_window_never_fetches_rss(candidate_driver, case):
    driver, now = candidate_driver
    if case == "stale":
        driver._pin_create_data.update(
            generation_started_at=(now - timedelta(seconds=800)).timestamp(),
            observed_at=(now - timedelta(seconds=750)).timestamp(),
        )
    elif case == "future":
        driver._pin_create_data["observed_at"] = (now + timedelta(seconds=30)).timestamp()
    elif case == "reversed":
        driver._pin_create_data["generation_started_at"] = now.timestamp()
    else:
        driver._pin_create_data["observed_at"] = {
            "nan": float("nan"),
            "infinite": float("inf"),
            "boolean": True,
            "numeric_string": str(now.timestamp()),
        }[case]
    page, _pin, feed = _page(now)

    assert await _verify(driver, page) is None
    assert all(call.args[0] == PIN_URL for call in page.context.request.get.await_args_list)
    feed.text.assert_not_awaited()


async def test_explicit_candidate_cannot_reuse_another_intercepted_candidates_timestamps(candidate_driver):
    driver, now = candidate_driver
    driver._pin_create_data["pin_id"] = OTHER_PIN
    page, _pin, feed = _page(now)

    result = await driver._verify_intercepted_public_pin(
        page,
        title=TITLE,
        link=DESTINATION,
        account_handle="media",
        description=DESCRIPTION,
        candidate_id=CANDIDATE,
    )

    assert result is None
    assert all(call.args[0] == PIN_URL for call in page.context.request.get.await_args_list)
    feed.text.assert_not_awaited()


@pytest.mark.parametrize("stage", ["public_html", "rss"])
async def test_new_interception_generation_during_read_discards_receipt(candidate_driver, stage):
    driver, now = candidate_driver
    page, pin, feed = _page(now)

    async def replace_generation():
        driver._pin_create_event = asyncio.Event()
        driver._pin_create_data = {"pin_id": CANDIDATE}
        return _public_html() if stage == "public_html" else _rss(now)

    (pin if stage == "public_html" else feed).text.side_effect = replace_generation

    assert await _verify(driver, page) is None


@pytest.mark.parametrize("stage", ["public_html", "rss"])
async def test_replaced_candidate_data_during_read_discards_receipt_even_with_same_event(
    candidate_driver, stage
):
    driver, now = candidate_driver
    page, pin, feed = _page(now)

    async def replace_candidate_data():
        driver._pin_create_data = dict(driver._pin_create_data)
        return _public_html() if stage == "public_html" else _rss(now)

    (pin if stage == "public_html" else feed).text.side_effect = replace_candidate_data

    assert await _verify(driver, page) is None


@pytest.mark.parametrize("stage", ["public_html", "rss"])
async def test_cancellation_during_either_proof_request_propagates(candidate_driver, stage):
    driver, now = candidate_driver
    page, pin, feed = _page(now)
    page.context.request.get.side_effect = (
        [asyncio.CancelledError(), feed]
        if stage == "public_html"
        else [
            pin,
            asyncio.CancelledError(),
        ]
    )

    with pytest.raises(asyncio.CancelledError):
        await _verify(driver, page)

    driver._verify_recent_public_pin.assert_not_awaited()

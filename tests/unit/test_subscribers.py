from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request

import pytest

from rankstein.subscribers import (
    SubscriberError,
    SupabaseSubscribersClient,
    SupabaseTarget,
    export_subscribers_csv,
    normalize_email,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[Request] = []

    def __call__(self, request: Request) -> FakeResponse:
        self.requests.append(request)
        return FakeResponse(self.responses.pop(0))


def make_client(opener: FakeOpener) -> SupabaseSubscribersClient:
    return SupabaseSubscribersClient(
        SupabaseTarget("https://example.supabase.co", "service-key"),
        opener=opener,
    )


@pytest.mark.unit
class TestNormalizeEmail:
    def test_lowercases_and_strips(self) -> None:
        assert normalize_email(" Test@Example.COM ") == "test@example.com"

    def test_rejects_invalid_email(self) -> None:
        with pytest.raises(SubscriberError):
            normalize_email("not-an-email")


@pytest.mark.unit
class TestSubscribersClient:
    def test_list_active_subscribers(self) -> None:
        opener = FakeOpener([[{"email": "a@example.test", "status": "active"}]])
        rows = make_client(opener).list()

        assert rows == [{"email": "a@example.test", "status": "active"}]
        assert opener.requests[0].get_method() == "GET"
        assert "status=eq.active" in opener.requests[0].full_url

    def test_add_inserts_when_missing(self) -> None:
        opener = FakeOpener([[], [{"email": "a@example.test", "status": "active"}]])
        row = make_client(opener).add("A@Example.Test", source="cli")

        assert row["email"] == "a@example.test"
        assert opener.requests[1].get_method() == "POST"
        assert opener.requests[1].headers["Prefer"] == "return=representation"
        assert json.loads(opener.requests[1].data.decode("utf-8")) == [
            {"email": "a@example.test", "status": "active", "source": "cli"}
        ]

    def test_add_returns_existing_active_subscriber(self) -> None:
        opener = FakeOpener([[{"email": "a@example.test", "status": "active"}]])
        row = make_client(opener).add("a@example.test")

        assert row["email"] == "a@example.test"
        assert len(opener.requests) == 1

    def test_unsubscribe_patches_status(self) -> None:
        opener = FakeOpener([[{"email": "a@example.test", "status": "unsubscribed"}]])
        row = make_client(opener).update_status("a@example.test", "unsubscribed")

        assert row["status"] == "unsubscribed"
        assert opener.requests[0].get_method() == "PATCH"
        assert json.loads(opener.requests[0].data.decode("utf-8")) == {"status": "unsubscribed"}


@pytest.mark.unit
class TestExportSubscribersCsv:
    def test_writes_expected_columns(self, tmp_path: Path) -> None:
        output = tmp_path / "subscribers.csv"
        export_subscribers_csv(
            [{"email": "a@example.test", "status": "active", "source": "cli"}],
            output,
        )

        text = output.read_text(encoding="utf-8")
        assert text.splitlines()[0] == "email,status,source,created_at,updated_at,id"
        assert "a@example.test,active,cli" in text

"""Exact published-Pin edits without browsers, production profiles, or HTTP writes."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from scripts.debug import repair_pinterest_pin_destinations as repair

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolated_account_policy(monkeypatch):
    policy = Mock()
    monkeypatch.setattr(repair, "_assert_account_available", policy)
    return policy


@pytest.fixture
def entry():
    return {
        "id": "existing-job",
        "account": "account_a",
        "pin_id": "1234567890123456",
        "pin_url": "https://www.pinterest.com/pin/1234567890123456/",
        "current_destination": "https://recipes.example/recipe-source-1-viral-visual",
        "proposed_destination": "https://recipes.example/recipe",
        "proposed_domain": "recipes",
        "expected_pinner": "https://www.pinterest.com/expected_owner/",
        "expected_username": "expected_owner",
        "expected_owner_id": "9876543210987654",
        "ready_for_owner_ui_destination_edit": True,
        "canonical_recipe_proof": {
            "verified": True,
            "proof": {
                "status": 200,
                "domain_handle": "recipes",
                "canonical_url": "https://recipes.example/recipe",
                "recipe_schema": {"@type": "Recipe", "name": "A real recipe"},
            },
        },
    }


def _public(entry, source=None):
    return {
        "pin_id": entry["pin_id"],
        "pinner": entry["expected_pinner"],
        "source": source or entry["current_destination"],
    }


def test_exact_plan_selection_and_owner_validation(entry):
    assert repair.validate_plan({"entries": [entry]}, {"account_a"}, [entry["pin_id"]], "account_a") == [
        entry
    ]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("pin_url", "https://www.pinterest.com/pin/1111111111111111/"),
        ("account", "unknown"),
        ("expected_owner_id", ""),
        ("expected_pinner", "https://www.pinterest.com/someone_else/"),
        ("ready_for_owner_ui_destination_edit", False),
        ("proposed_destination", "https://recipes.example/recipe-source-1-viral-visual"),
    ],
)
def test_invalid_plan_is_rejected_before_any_action(entry, key, value):
    entry[key] = value
    with pytest.raises(ValueError):
        repair.validate_plan({"entries": [entry]}, {"account_a"})


def test_plan_requires_verified_recipe_and_unique_existing_ids(entry):
    unverified = copy.deepcopy(entry)
    unverified["canonical_recipe_proof"]["verified"] = False
    with pytest.raises(ValueError, match="Recipe"):
        repair.validate_plan({"entries": [unverified]}, {"account_a"})
    with pytest.raises(ValueError, match="duplicate"):
        repair.validate_plan({"entries": [entry, entry]}, {"account_a"})
    with pytest.raises(ValueError, match="Select"):
        repair.validate_plan({"entries": [entry]}, {"account_a"}, ["1111111111111111"])
    with pytest.raises(ValueError, match="configured account"):
        repair.validate_plan({"entries": [entry]}, {"account_a"}, account="other")


@pytest.mark.parametrize("missing", ["ids", "account", "hash"])
def test_apply_requires_explicit_pin_ids_account_and_exact_plan_hash(entry, missing):
    with pytest.raises(ValueError, match="exact expected plan SHA256"):
        repair.validate_apply_request(
            [entry],
            pin_ids=None if missing == "ids" else [entry["pin_id"]],
            account=None if missing == "account" else entry["account"],
            expected_sha256="changed" if missing == "hash" else "exact-plan-hash",
            actual_sha256="exact-plan-hash",
        )


def test_exact_apply_request_accepts_single_account(entry):
    repair.validate_apply_request(
        [entry],
        pin_ids=[entry["pin_id"]],
        account=entry["account"],
        expected_sha256="exact-plan-hash",
        actual_sha256="exact-plan-hash",
    )
    with pytest.raises(ValueError, match="one account"):
        repair.validate_apply_request(
            [entry, {**entry, "account": "account_b"}],
            pin_ids=[entry["pin_id"]],
            account=entry["account"],
            expected_sha256="exact-plan-hash",
            actual_sha256="exact-plan-hash",
        )


@pytest.mark.parametrize(
    ("dry_run", "preflight", "results", "expected"),
    [
        (True, ["ready"], [], 0),
        (True, ["blocked"], [], 1),
        (False, ["ready"], ["verified_updated"], 0),
        (False, ["already_correct"], ["already_correct"], 0),
        (False, ["ready"], ["uncertain_after_save"], 1),
        (False, ["ready"], [], 1),
    ],
)
def test_cli_exit_status_never_reports_blocked_uncertain_or_partial_apply_as_success(
    dry_run, preflight, results, expected
):
    report = {
        "dry_run": dry_run,
        "preflight": [{"state": state} for state in preflight],
        "results": [{"state": state} for state in results],
    }
    assert repair.report_exit_code(report, 1) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("already_correct", [False, True])
async def test_http_preflight_never_needs_a_browser(entry, already_correct):
    public = _public(entry, entry["proposed_destination"] if already_correct else None)
    results = await repair.preflight(
        [entry],
        pin_fetcher=lambda url: public,
        article_fetcher=lambda url: entry["canonical_recipe_proof"]["proof"],
    )
    assert results[0]["state"] == ("already_correct" if already_correct else "ready")


@pytest.mark.asyncio
async def test_changed_recipe_or_owner_blocks_preflight(entry):
    wrong_owner = {**_public(entry), "pinner": "https://www.pinterest.com/another_owner/"}
    results = await repair.preflight(
        [entry],
        pin_fetcher=lambda url: wrong_owner,
        article_fetcher=lambda url: entry["canonical_recipe_proof"]["proof"],
    )
    assert results[0]["state"] == "blocked"
    fetch_pin = Mock()
    results = await repair.preflight(
        [entry],
        pin_fetcher=fetch_pin,
        article_fetcher=Mock(side_effect=ValueError("soft 404")),
    )
    assert results[0]["state"] == "blocked"
    fetch_pin.assert_not_called()


def test_public_html_requires_same_id_owner_and_exact_destination(entry, monkeypatch):
    class Response:
        status = 200
        url = entry["pin_url"]

        def read(self, limit):
            return (
                f'<meta property="og:url" content="{entry["pin_url"]}">'
                f'<link href="{entry["pin_url"]}" rel="canonical">'
                f'<meta property="pinterestapp:pinner" content="{entry["expected_pinner"]}">'
                f'<meta property="pinterestapp:source" content="{entry["current_destination"]}">'
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(repair, "urlopen", lambda request, timeout: Response())
    assert repair.check_public(entry, repair.fetch_public_pin(entry["pin_url"])) == "ready"
    with pytest.raises(ValueError, match="destination"):
        repair.check_public(entry, _public(entry, "https://recipes.example/unexpected"))
    Response.url = "https://www.pinterest.com/pin/1111111111111111/"
    with pytest.raises(ValueError, match="identity"):
        repair.fetch_public_pin(entry["pin_url"])
    Response.url = entry["pin_url"]
    original_read = Response.read
    Response.read = lambda self, limit: original_read(self, limit).replace(
        entry["pin_url"].encode(), b"https://co.pinterest.com/pin/1111111111111111/"
    )
    with pytest.raises(ValueError, match="same Pin ID"):
        repair.fetch_public_pin(entry["pin_url"])


@pytest.mark.parametrize("locale", ["es", "co", "de", "ar", "www"])
def test_numeric_pin_identity_accepts_only_bounded_pinterest_locales(entry, locale):
    assert repair._pin_id(f"https://{locale}.pinterest.com/pin/{entry['pin_id']}/") == entry["pin_id"]
    for host in ("pinterest.com.evil.example", "evil-pinterest.com", "nested.es.pinterest.com"):
        with pytest.raises(ValueError):
            repair._pin_id(f"https://{host}/pin/{entry['pin_id']}/")


class Locator:
    def __init__(self, items):
        self.items = items

    @property
    def first(self):
        return self.items[0] if self.items else Control("missing", visible=False)

    async def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]


class Control:
    def __init__(self, name, *, visible=True, click=None):
        self.name = name
        self.visible = visible
        self.clicked = 0
        self.on_click = click
        self.enabled = True
        self.test_id = None

    async def get_attribute(self, key):
        return self.test_id if key == "data-test-id" else None

    async def is_visible(self):
        return self.visible

    async def is_enabled(self):
        return self.enabled

    async def wait_for(self, **kwargs):
        if not self.visible:
            raise ValueError("control unavailable")

    async def click(self, **kwargs):
        self.clicked += 1
        if self.on_click:
            self.on_click()


class Field(Control):
    def __init__(self, value, name="edit-pin-link"):
        super().__init__(name)
        self.value = value
        self.filled = []

    async def is_editable(self):
        return True

    async def input_value(self):
        return self.value

    async def get_attribute(self, key):
        return self.name if key == "id" else None

    async def fill(self, value, **kwargs):
        self.filled.append(value)
        self.value = value


class Dialog(Control):
    def __init__(self, fields, save):
        super().__init__("Edit Pin")
        self.fields, self.save = fields, save

    def locator(self, selector):
        assert selector == "input,textarea"
        return Locator(self.fields)

    def get_by_role(self, role, name):
        assert role == "button" and name.search("Save")
        return Locator([self.save])


class Page:
    def __init__(self, entry, *, direct=True):
        self.entry = entry
        self.url = entry["pin_url"]
        self.saved = False
        self.field = Field(entry["current_destination"])
        self.save = Control("Save", click=self._save)
        self.edit = Control("Edit Pin")
        self.more = Control("More options")
        self.more_controls = [self.more]
        self.dialog = Dialog([self.field], self.save)
        self.direct = direct
        self.owner = {"ids": [entry["expected_owner_id"]], "usernames": [entry["expected_username"]]}

    def _save(self):
        self.saved = True

    def fetch_pin(self, url):
        assert url == self.entry["pin_url"]
        return _public(self.entry, self.entry["proposed_destination"] if self.saved else None)

    async def goto(self, url, **kwargs):
        assert url == self.entry["pin_url"]
        self.url = url

    async def wait_for_function(self, expression, **kwargs):
        pass

    async def evaluate(self, expression):
        assert "document.getElementById" in expression
        return self.owner

    def get_by_role(self, role, name=None):
        if role == "dialog":
            return Locator([self.dialog])
        if role == "menuitem":
            return Locator([self.edit])
        if name.search("More options"):
            return Locator(self.more_controls)
        return Locator([self.edit] if self.direct else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("direct", [True, False])
async def test_normal_edit_changes_only_link_saves_once_and_verifies_same_id(entry, direct):
    page = Page(entry, direct=direct)
    progress = Mock()
    result = await repair.edit_same_pin(
        page, entry, guard=Mock(), progress=progress, pin_fetcher=page.fetch_pin
    )
    assert result["state"] == "verified_updated"
    assert result["pin_id"] == entry["pin_id"]
    assert page.field.filled == [entry["proposed_destination"]]
    assert page.save.clicked == 1
    assert page.more.clicked == (0 if direct else 1)
    progress.assert_called_once()


@pytest.mark.asyncio
async def test_primary_more_actions_excludes_same_label_recommendations(entry):
    page = Page(entry, direct=False)
    page.more.name = "More actions"
    recommendations = [Control("More actions") for _ in range(12)]
    for control in recommendations:
        control.test_id = "more-actions-button"
    # A recommendation may appear first in the locator; selection is not first().
    page.more_controls = [recommendations[0], page.more, *recommendations[1:]]
    result = await repair.edit_same_pin(
        page, entry, guard=Mock(), progress=Mock(), pin_fetcher=page.fetch_pin
    )
    assert result["state"] == "verified_updated"
    assert page.more.clicked == 1
    assert all(control.clicked == 0 for control in recommendations)
    assert page.save.clicked == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["only_recommendations", "ambiguous_primary", "disabled_primary"])
async def test_uncertain_primary_action_never_clicks_any_pin_or_save(entry, failure):
    page = Page(entry, direct=False)
    recommendation = Control("More actions")
    recommendation.test_id = "more-actions-button"
    if failure == "only_recommendations":
        page.more_controls = [recommendation]
    elif failure == "ambiguous_primary":
        page.more_controls = [page.more, Control("More actions"), recommendation]
    else:
        page.more.enabled = False
        page.more_controls = [page.more, recommendation]
    with pytest.raises(ValueError, match="primary Pin"):
        await repair.edit_same_pin(page, entry, guard=Mock(), progress=Mock(), pin_fetcher=page.fetch_pin)
    assert all(control.clicked == 0 for control in page.more_controls)
    assert page.edit.clicked == page.save.clicked == 0


@pytest.mark.asyncio
async def test_already_correct_pin_is_idempotent_without_opening_editor(entry):
    page = Page(entry)
    page.saved = True
    result = await repair.edit_same_pin(
        page, entry, guard=Mock(), progress=Mock(), pin_fetcher=page.fetch_pin
    )
    assert result["state"] == "already_correct"
    assert page.edit.clicked == page.save.clicked == 0
    assert page.field.filled == []


@pytest.mark.asyncio
async def test_localized_browser_same_id_can_edit_without_logging_query(entry):
    page = Page(entry)

    async def localized_goto(url, **kwargs):
        page.url = f"https://es.pinterest.com/pin/{entry['pin_id']}/?tracking=private_value"

    page.goto = localized_goto
    result = await repair.edit_same_pin(
        page, entry, guard=Mock(), progress=Mock(), pin_fetcher=page.fetch_pin
    )
    assert result["state"] == "verified_updated"
    assert page.save.clicked == 1


@pytest.mark.asyncio
async def test_failure_diagnostics_exclude_query_and_capture_only_bounded_controls(entry, tmp_path):
    controls = [{"tag": "BUTTON", "label": "Edit Pin"}]
    page = SimpleNamespace(
        url=f"https://es.pinterest.com/pin/{entry['pin_id']}/?tracking=private_value#secret_fragment",
        evaluate=AsyncMock(return_value=controls),
        screenshot=AsyncMock(),
    )
    result = await repair.failure_diagnostics(page, entry, tmp_path / "report.json")
    assert result["observed_url"] == {"host": "es.pinterest.com", "path": f"/pin/{entry['pin_id']}/"}
    assert result["visible_controls"] == controls
    assert "private_value" not in json.dumps(result)
    assert "secret_fragment" not in json.dumps(result)
    page.screenshot.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["owner", "old_link", "ambiguous", "not_link", "disabled", "lost_lease"])
async def test_owner_field_and_lease_guards_prevent_save(entry, failure):
    page = Page(entry)
    guard = Mock()
    if failure == "owner":
        page.owner["ids"] = ["1111111111111111"]
    elif failure == "old_link":
        page.field.value = "https://recipes.example/unexpected"
    elif failure == "ambiguous":
        page.dialog.fields.append(Field(entry["current_destination"]))
    elif failure == "not_link":
        page.field.name = "title"
    elif failure == "disabled":
        page.save.enabled = False
    else:
        guard.side_effect = [None, None, RuntimeError("ownership lost")]
    with pytest.raises((ValueError, RuntimeError)):
        await repair.edit_same_pin(page, entry, guard=guard, progress=Mock(), pin_fetcher=page.fetch_pin)
    assert page.save.clicked == 0


@pytest.mark.asyncio
async def test_uncertain_save_is_never_repeated_or_reported_as_success(entry, monkeypatch):
    page = Page(entry)
    page.save.on_click = Mock(side_effect=TimeoutError("click result uncertain"))
    monkeypatch.setattr(repair.asyncio, "sleep", AsyncMock())
    result = await repair.edit_same_pin(
        page, entry, guard=Mock(), progress=Mock(), pin_fetcher=page.fetch_pin
    )
    assert result["state"] == "uncertain_after_save"
    assert result["save_attempted"] is True
    assert result["save_clicked"] is False
    assert page.save.clicked == 1


@pytest.mark.asyncio
async def test_timed_out_save_can_be_proven_publicly_without_clicking_again(entry):
    page = Page(entry)

    def uncertain_click():
        page.saved = True
        raise TimeoutError("result uncertain")

    page.save.on_click = uncertain_click
    result = await repair.edit_same_pin(
        page, entry, guard=Mock(), progress=Mock(), pin_fetcher=page.fetch_pin
    )
    assert result["state"] == "verified_updated"
    assert result["save_clicked"] is False
    assert page.save.clicked == 1


@pytest.mark.asyncio
async def test_save_may_be_disabled_until_destination_changes(entry):
    page = Page(entry)
    page.save.enabled = False
    original_fill = page.field.fill

    async def fill(value, **kwargs):
        await original_fill(value, **kwargs)
        page.save.enabled = True

    page.field.fill = fill
    result = await repair.edit_same_pin(
        page, entry, guard=Mock(), progress=Mock(), pin_fetcher=page.fetch_pin
    )
    assert result["state"] == "verified_updated"
    assert page.save.clicked == 1


class Lease:
    def __init__(self, worker_count):
        assert worker_count == 0
        self._owned = False
        self.release = Mock()

    def acquire(self):
        self._owned = True

    def heartbeat(self):
        pass

    def stop_requested(self):
        return False


@pytest.mark.asyncio
async def test_foreign_lease_blocks_before_profile_creation(entry):
    lease = Lease(0)
    lease.acquire = Mock(side_effect=RuntimeError("already owned"))
    pool_factory = Mock()
    with pytest.raises(RuntimeError, match="already owned"):
        await repair.apply_entries(
            [entry], {"results": []}, Mock(), lease_factory=lambda **kwargs: lease, pool_factory=pool_factory
        )
    pool_factory.assert_not_called()


@pytest.mark.asyncio
async def test_paused_human_recovery_account_blocks_before_lease_or_profile(entry, isolated_account_policy):
    isolated_account_policy.side_effect = RuntimeError("paused for human recovery")
    lease_factory, pool_factory = Mock(), Mock()
    with pytest.raises(RuntimeError, match="paused"):
        await repair.apply_entries(
            [entry],
            {"results": []},
            Mock(),
            lease_factory=lease_factory,
            pool_factory=pool_factory,
        )
    lease_factory.assert_not_called()
    pool_factory.assert_not_called()


@pytest.mark.asyncio
async def test_batch_stops_on_uncertain_edit_and_closes_own_resources(entry, monkeypatch):
    second = {**entry, "pin_id": "1111111111111111"}
    edit = AsyncMock(return_value={"pin_id": entry["pin_id"], "state": "uncertain_after_save"})
    monkeypatch.setattr(repair, "edit_same_pin", edit)
    pool = SimpleNamespace(
        acquire=AsyncMock(return_value=SimpleNamespace(page=object())), close_all=AsyncMock()
    )
    lease = Lease(0)
    report = {"results": []}
    await repair.apply_entries(
        [entry, second], report, Mock(), lease_factory=lambda **kwargs: lease, pool_factory=lambda: pool
    )
    assert edit.await_count == 1
    assert len(report["results"]) == 1
    pool.close_all.assert_awaited_once()
    lease.release.assert_called_once()


@pytest.mark.asyncio
async def test_lost_ownership_cannot_continue_after_silent_heartbeat(entry, monkeypatch):
    lease = Lease(0)
    lease.heartbeat = lambda: setattr(lease, "_owned", False)
    pool = SimpleNamespace(
        acquire=AsyncMock(return_value=SimpleNamespace(page=object())), close_all=AsyncMock()
    )
    edit = AsyncMock()
    monkeypatch.setattr(repair, "edit_same_pin", edit)
    with pytest.raises(RuntimeError, match="ownership"):
        await repair.apply_entries(
            [entry], {"results": []}, Mock(), lease_factory=lambda **kwargs: lease, pool_factory=lambda: pool
        )
    edit.assert_not_awaited()
    pool.close_all.assert_awaited_once()
    lease.release.assert_called_once()


@pytest.mark.asyncio
async def test_close_failure_still_releases_maintenance_lease(entry, monkeypatch):
    lease = Lease(0)
    pool = SimpleNamespace(
        acquire=AsyncMock(return_value=SimpleNamespace(page=object())),
        close_all=AsyncMock(side_effect=RuntimeError("close failed")),
    )
    monkeypatch.setattr(
        repair,
        "edit_same_pin",
        AsyncMock(return_value={"pin_id": entry["pin_id"], "state": "already_correct"}),
    )
    with pytest.raises(RuntimeError, match="close failed"):
        await repair.apply_entries(
            [entry], {"results": []}, Mock(), lease_factory=lambda **kwargs: lease, pool_factory=lambda: pool
        )
    lease.release.assert_called_once()

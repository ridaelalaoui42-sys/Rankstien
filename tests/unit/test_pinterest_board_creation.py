"""Board creation follows the visible Name label, not placeholder wording."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.scripts.pinterest_batch_core import _submit_board_creation


class _Field:
    def __init__(self, dialog, *, present=True, submit=False):
        self.dialog = dialog
        self.present = present
        self.submit = submit
        self.first = self

    async def count(self):
        return int(self.present)

    async def is_visible(self):
        return self.present

    async def is_enabled(self):
        return not self.submit or (bool(self.dialog.value) and not self.dialog.disabled)

    async def fill(self, value, **_kwargs):
        self.dialog.value = value

    async def input_value(self):
        return self.dialog.value

    async def click(self, **_kwargs):
        self.dialog.submissions += 1


class _Dialog:
    def __init__(self, label="Name", *, disabled=False, field_present=True, closes=True):
        self.label = label
        self.value = ""
        self.disabled = disabled
        self.field_present = field_present
        self.submissions = 0
        self.wait_for = AsyncMock(side_effect=None if closes else TimeoutError("modal remains open"))

    def get_by_label(self, pattern):
        return _Field(self, present=self.field_present and bool(pattern.fullmatch(self.label)))

    def get_by_role(self, role, **_kwargs):
        if role == "textbox":
            return _Field(self, present=self.field_present)
        assert role == "button"
        return _Field(self, submit=True)

    def locator(self, _selector):
        # Current Pinterest placeholder is `Like "Places to Go" or "Recipes to Make"`;
        # none of the old Name/Nombre-placeholder or boardEditName selectors match.
        return _Field(self, present=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("label", ["Name", "Nombre", "Board name"])
async def test_current_board_form_fills_label_and_confirms_dialog_closure(label):
    dialog = _Dialog(label)
    assert await _submit_board_creation(dialog, "Chocolate") is True
    assert dialog.value == "Chocolate"
    assert dialog.submissions == 1
    dialog.wait_for.assert_awaited_once_with(state="hidden", timeout=10000)


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [{"field_present": False}, {"disabled": True}])
async def test_missing_name_or_disabled_create_does_not_submit(options):
    dialog = _Dialog(**options)
    assert await _submit_board_creation(dialog, "Chocolate") is False
    assert dialog.submissions == 0


@pytest.mark.asyncio
async def test_open_modal_is_not_reported_as_created_board():
    dialog = _Dialog(closes=False)
    assert await _submit_board_creation(dialog, "Chocolate") is False
    assert dialog.submissions == 1

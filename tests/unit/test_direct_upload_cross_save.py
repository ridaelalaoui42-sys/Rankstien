from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "rms_direct_cross_save", PROJECT_ROOT / "rankstein_mcp_server.py"
)
rms = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(rms)  # type: ignore[union-attr]


class FakeQueue:
    def __init__(self) -> None:
        self.jobs = []

    async def enqueue_async(self, job):
        self.jobs.append(job)
        return f"job-{len(self.jobs)}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_direct_upload_enqueues_cross_save_jobs_for_other_accounts(monkeypatch) -> None:
    queue = FakeQueue()

    async def fake_upload_pin_via_driver(**kwargs):
        assert kwargs["account_handle"] == ""
        return {
            "success": True,
            "pin_id": "123",
            "pin_url": "https://www.pinterest.com/pin/123/",
        }

    import pinterest_automation

    monkeypatch.setattr(rms, "_AUTO_AVAILABLE", True)
    monkeypatch.setattr(rms, "upload_pin_via_driver", fake_upload_pin_via_driver)
    monkeypatch.setattr(pinterest_automation, "get_job_queue", lambda: queue)
    monkeypatch.setattr(
        pinterest_automation,
        "get_config",
        lambda: SimpleNamespace(accounts={"rida": object(), "media": object()}),
    )
    monkeypatch.setenv("PINTEREST_DEFAULT_ACCOUNT_HANDLE", "rida")
    monkeypatch.setenv("PINTEREST_CROSS_SAVE_LIMIT", "1")

    result = await rms.automation_upload_pin_direct(
        image_path="/tmp/pin.jpg",
        title="Pin title",
        description="Pin description",
        link="https://example.invalid/article",
        board_name="Postres y Dulces",
        domain_handle="recetadolce",
    )

    assert result["success"] is True
    assert result["cross_save_jobs"] == [{"job_id": "job-1", "account_handle": "media"}]
    assert len(queue.jobs) == 1
    job = queue.jobs[0]
    assert job.type == "pin_save"
    assert job.priority == 3
    assert job.payload == {
        "pin_url": "https://www.pinterest.com/pin/123/",
        "account_handle": "media",
        "board_name": "Chocolate",
        "domain_handle": "recetadolce",
        "source": "automation_upload_pin_direct",
        "source_account": "rida",
        "originator_account": "rida",
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_direct_upload_uses_explicit_account_for_domain(monkeypatch) -> None:
    captured = {}

    async def fake_upload_pin_via_driver(**kwargs):
        captured.update(kwargs)
        return {"success": True, "pin_id": "456", "pin_url": "https://www.pinterest.com/pin/456/"}

    import pinterest_automation

    monkeypatch.setattr(rms, "_AUTO_AVAILABLE", True)
    monkeypatch.setattr(rms, "upload_pin_via_driver", fake_upload_pin_via_driver)
    monkeypatch.setattr(
        pinterest_automation,
        "get_config",
        lambda: SimpleNamespace(accounts={"rida": object(), "media": object()}),
    )
    monkeypatch.setenv("PINTEREST_CROSS_SAVE_LIMIT", "0")

    result = await rms.automation_upload_pin_direct(
        image_path="/tmp/pin.jpg",
        title="Pin title",
        description="Pin description",
        link="https://recetagenial.com/article",
        board_name="ENSALADES",
        domain_handle="recetagenial",
        account_handle="media",
    )

    assert result["success"] is True
    assert captured["domain_handle"] == "recetagenial"
    assert captured["account_handle"] == "media"

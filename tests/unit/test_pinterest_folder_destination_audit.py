"""Discovery and canonical-proof planning never update live queue tables."""

import hashlib
import json
import sqlite3
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from scripts.dev.audit_pinterest_folder_destinations import discover, verify_articles


def database(tmp_path):
    path = tmp_path / "jobs.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE jobs(id TEXT,type TEXT,status TEXT,payload_json TEXT,result_json TEXT,"
            "attempt INTEGER,max_attempts INTEGER,next_retry_at REAL)"
        )
        connection.execute("CREATE TABLE dlq(id TEXT,job_json TEXT,moved_at REAL)")
    return path


def add_job(db, root, job_id, *, status="pending", domain="blog", account="known", missing_image=False):
    image = root / "blog" / "2026-10-16" / "tarta-de-queso" / f"{job_id}-source-01.jpg"
    image.parent.mkdir(parents=True, exist_ok=True)
    if not missing_image:
        image.write_bytes(b"retained")
    payload = {
        "image_path": str(image),
        "link": "https://incorrect.example/tarta-de-queso-source-01",
        "domain_handle": domain,
        "account_handle": account,
        "title": "Tarta De Queso Source 01",
        "extra": {"domain_handle": domain, "account_handle": account, "campaign_type": "folder_batch"},
    }
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",
            (job_id, "pin_upload", status, json.dumps(payload), None, 2, 3, 9999999999.0),
        )


def test_discovery_derives_registry_target_and_preserves_all_storage(tmp_path):
    db = database(tmp_path)
    root = tmp_path / "remaster_final"
    add_job(db, root, "candidate", domain="wrong-blog")
    add_job(db, root, "held-work", status="held")
    add_job(db, root, "leased-work", status="processing")
    with sqlite3.connect(db) as connection:
        connection.execute("INSERT INTO dlq VALUES ('uncertain','uncertain-publication',123.0)")
    before = hashlib.sha256(db.read_bytes()).hexdigest()

    report = discover(db, {"blog": SimpleNamespace(domain="configured.example")}, {"known"}, root)

    assert report["apply_performed"] is False and report["read_only"]
    assert [job["id"] for job in report["jobs"]] == ["candidate"]
    candidate = report["jobs"][0]
    assert candidate["proposed_destination"] == "https://configured.example/tarta-de-queso"
    assert candidate["derived_domain_handle"] == "blog"
    assert candidate["attempt"] == 2 and candidate["next_retry_at"] == 9999999999.0
    assert set(candidate["metadata_mismatches"]) == {
        "destination",
        "domain_handle",
        "extra.domain_handle",
        "extra.slug",
        "filename_title_metadata",
    }
    assert [row["id"] for row in report["held_rows_preserved"]] == ["held-work"]
    assert report["dlq_rows_preserved"]["selected"] == 0
    assert report["dlq_rows_preserved"]["count"] == 1
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("issue", ["missing_image", "unknown_account", "unknown_domain"])
def test_unsafe_candidates_are_preserved_and_excluded(tmp_path, issue):
    db = database(tmp_path)
    root = tmp_path / "remaster_final"
    add_job(
        db,
        root,
        "unsafe",
        missing_image=issue == "missing_image",
        account="other" if issue == "unknown_account" else "known",
    )
    domains = {} if issue == "unknown_domain" else {"blog": SimpleNamespace(domain="configured.example")}

    report = discover(db, domains, {"known"}, root)

    assert report["jobs"] == []
    assert [row["id"] for row in report["excluded_preserved"]] == ["unsafe"]


def test_404_targets_are_excluded_without_redirecting_to_a_similar_recipe():
    good = "https://configured.example/tarta-de-queso"
    bad = "https://configured.example/unknown-recipe"
    report = {
        "jobs": [
            {"id": "good", "proposed_destination": good, "derived_domain_handle": "custom-handle"},
            {"id": "bad", "proposed_destination": bad, "derived_domain_handle": "custom-handle"},
        ]
    }

    def proof(url):
        if url == bad:
            raise HTTPError(url, 404, "Not Found", None, None)
        return url, {
            "status": 200,
            "canonical_url": url,
            "domain_handle": "wrong-inferred-handle",
            "recipe_schema": {"@type": "Recipe", "name": "Tarta de queso"},
        }

    verified = verify_articles(report, proof)

    assert [row["id"] for row in verified["jobs"]] == ["good"]
    assert [row["id"] for row in verified["unproven_jobs_preserved"]] == ["bad"]
    assert verified["rejected_articles"][bad]["http_status"] == 404
    assert verified["article_proofs"][good]["domain_handle"] == "custom-handle"
    assert verified["canonical_proof_pending"] is False


def test_mismatched_canonical_proof_is_rejected():
    url = "https://configured.example/tarta-de-queso"
    report = {"jobs": [{"id": "one", "proposed_destination": url, "derived_domain_handle": "blog"}]}
    verified = verify_articles(
        report, lambda target: (target, {"status": 200, "canonical_url": "https://configured.example/other"})
    )
    assert verified["jobs"] == [] and url in verified["rejected_articles"]


@pytest.mark.parametrize(
    "schema", [None, {"@type": "Article", "name": "Recipe"}, {"@type": "Recipe", "name": " "}]
)
def test_http200_without_named_recipe_is_not_eligible(schema):
    url = "https://configured.example/tarta-de-queso"
    report = {"jobs": [{"id": "one", "proposed_destination": url, "derived_domain_handle": "blog"}]}
    verified = verify_articles(
        report,
        lambda target: (target, {"status": 200, "canonical_url": target, "recipe_schema": schema}),
    )
    assert verified["jobs"] == [] and url in verified["rejected_articles"]

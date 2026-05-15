"""Verify every published article URL renders without known broken markers."""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rankstein.domain import Domain, get_registry

REPORT_DIR = Path("data/reports")
BROKEN_MARKERS = re.compile(r"\\n\\n|\[HERO_IMAGE\]|\[PINTEREST_IFRAME", re.IGNORECASE)
RECIPE_SIGNALS = ("recipeIngredient", "Ingredientes", "Instrucciones", "RecipeDetails")


@dataclass
class LiveArticleCheck:
    domain: str
    slug: str
    url: str
    status_code: int | None
    ok: bool
    broken_markers: bool = False
    recipe_signals: bool = False
    cache: str | None = None
    age: str | None = None
    error: str | None = None


def _headers(domain: Domain) -> dict[str, str]:
    key = domain.supabase_service_role_key.get_secret_value()
    if not key:
        raise RuntimeError(f"Missing Supabase service role key for {domain.handle}")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _fetch_published_posts(domain: Domain) -> list[dict[str, Any]]:
    response = requests.get(
        f"{domain.supabase_url}/rest/v1/posts?select=slug,title,is_published,status&order=created_at.desc",
        headers=_headers(domain),
        timeout=45,
    )
    if response.status_code != 200:
        raise RuntimeError(f"{domain.handle} post fetch failed: {response.status_code} {response.text[:240]}")
    rows = response.json()
    return [
        row
        for row in rows
        if row.get("slug")
        and (row.get("is_published") is True or str(row.get("status") or "").casefold() == "published")
    ]


def _check_url(domain: Domain, slug: str, timeout: float, attempts: int = 3) -> LiveArticleCheck:
    url = f"https://{domain.domain}/{slug}"
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            response = requests.get(
                url, headers={"User-Agent": "RanksteinLiveArticleAudit/1.0"}, timeout=timeout
            )
            body = response.text or ""
            broken_markers = bool(BROKEN_MARKERS.search(body))
            recipe_signals = any(signal in body for signal in RECIPE_SIGNALS)
            ok = response.status_code == 200 and not broken_markers and recipe_signals
            return LiveArticleCheck(
                domain=domain.handle,
                slug=slug,
                url=url,
                status_code=response.status_code,
                ok=ok,
                broken_markers=broken_markers,
                recipe_signals=recipe_signals,
                cache=response.headers.get("X-Vercel-Cache"),
                age=response.headers.get("Age"),
            )
        except Exception as exc:
            last_error = exc
    return LiveArticleCheck(
        domain=domain.handle,
        slug=slug,
        url=url,
        status_code=None,
        ok=False,
        error=str(last_error) if last_error else "unknown fetch failure",
    )


def _write_report(results: list[LiveArticleCheck]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = REPORT_DIR / f"live-article-quality-{stamp}.json"
    md_path = REPORT_DIR / "live-article-quality-latest.md"
    failures = [result for result in results if not result.ok]
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "checked": len(results),
        "passed": len(results) - len(failures),
        "failed": len(failures),
        "results": [asdict(result) for result in results],
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Live Article Quality Check",
        "",
        f"- Checked: {payload['checked']}",
        f"- Passed: {payload['passed']}",
        f"- Failed: {payload['failed']}",
        f"- JSON report: `{json_path}`",
        "",
    ]
    if failures:
        lines.append("## Failures")
        lines.append("")
        for failure in failures:
            reason = (
                failure.error
                or f"status={failure.status_code} broken={failure.broken_markers} recipe={failure.recipe_signals}"
            )
            lines.append(f"- `{failure.domain}` [{failure.slug}]({failure.url}) - {reason}")
    else:
        lines.append("All published article URLs passed the live broken-marker and recipe-signal checks.")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


def main() -> int:
    registry = get_registry()
    jobs: list[tuple[Domain, str]] = []
    for domain in registry.all():
        jobs.extend((domain, str(post["slug"])) for post in _fetch_published_posts(domain))

    results: list[LiveArticleCheck] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_check_url, domain, slug, 30) for domain, slug in jobs]
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda result: (result.domain, result.slug))
    report = _write_report(results)
    failed = sum(1 for result in results if not result.ok)
    print(f"checked={len(results)} failed={failed} report={report}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

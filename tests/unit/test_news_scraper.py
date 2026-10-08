import pytest

from backend.services import news_scraper


@pytest.mark.unit
def test_source_search_discards_title_only_rss_results(monkeypatch) -> None:
    monkeypatch.setattr(news_scraper, "_ddg_api_search", lambda keyword, count: [])
    monkeypatch.setattr(news_scraper, "_ddg_lite_search", lambda keyword, count: [])
    monkeypatch.setattr(
        news_scraper,
        "_google_news_rss",
        lambda keyword, lang, country, count: [
            {
                "title": "Recipe headline",
                "url": "",
                "snippet": "Title-only context",
                "source": "Example",
            }
        ],
    )

    assert news_scraper.scrape_google_news("tarta de queso", count=5) == []


@pytest.mark.unit
def test_source_search_keeps_direct_extractable_results(monkeypatch) -> None:
    direct = {
        "title": "Tarta de queso al horno",
        "url": "https://recipes.example/tarta-queso",
        "snippet": "Una receta completa",
        "source": "recipes.example",
    }
    monkeypatch.setattr(news_scraper, "_ddg_api_search", lambda keyword, count: [direct, direct])

    assert news_scraper.scrape_google_news("tarta de queso", count=2) == [direct, direct]

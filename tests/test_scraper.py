"""Runs the Python scraper's per-profile step against fixture pages served in place of linkedin.com."""

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")

from linkedin_scraper.parsing import parse_target  # noqa: E402
from linkedin_scraper.scraper import scrape_target  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def page():
    exe = os.environ.get("LINKEDIN_SCRAPER_CHROMIUM")
    with playwright.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
        except Exception as exc:
            pytest.skip(f"Chromium not available: {exc}")
        page = browser.new_page()
        page.route("https://www.linkedin.com/**", lambda r: r.fulfill(
            status=200, content_type="text/html",
            body=(FIXTURES / ("activity.html" if "/company/" in r.request.url else "activity_new_layout.html")).read_text()))
        yield page
        browser.close()


def test_scrape_target_new_layout(page):
    posts = scrape_target(page, parse_target("in/cecilia-example"), max_posts=10, since=None, max_scrolls=1)
    assert [p.author for p in posts] == ["Cecilia Example", "DIGITALEUROPE"]
    assert posts[0].source == "https://www.linkedin.com/in/cecilia-example/"
    assert posts[0].to_row()["links"] == "https://example.eu/speech"


def test_scrape_target_since_filter(page):
    since = datetime(2024, 10, 1, tzinfo=timezone.utc)
    posts = scrape_target(page, parse_target("company/acme"), max_posts=10, since=since, max_scrolls=1)
    assert [p.urn for p in posts] == ["urn:li:activity:7250000000000000000", "urn:li:activity:7249000000000000000"]
    later = datetime(2024, 10, 10, tzinfo=timezone.utc)
    posts = scrape_target(page, parse_target("company/acme"), max_posts=10, since=later, max_scrolls=1)
    assert [p.urn for p in posts] == ["urn:li:activity:7250000000000000000"]

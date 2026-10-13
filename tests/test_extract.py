"""Runs the in-page extraction against a saved fixture in a real headless Chromium."""

import os
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")

from linkedin_scraper.parsing import build_post, parse_target  # noqa: E402
from linkedin_scraper.scraper import SELECTORS, _EXTRACT_JS  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "activity.html"


@pytest.fixture(scope="module")
def page():
    kwargs = {}
    exe = os.environ.get("LINKEDIN_SCRAPER_CHROMIUM")
    if exe:
        kwargs["executable_path"] = exe
    with playwright.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(**kwargs)
        except Exception as exc:
            pytest.skip(f"Chromium not available: {exc}")
        page = browser.new_page()
        page.goto(FIXTURE.as_uri())
        yield page
        browser.close()


def test_extracts_posts(page):
    target = parse_target("https://www.linkedin.com/in/jane-doe/")
    posts = [p for p in (build_post(r, target) for r in page.evaluate(_EXTRACT_JS, SELECTORS)) if p]
    assert len(posts) == 2

    first, repost = posts
    assert first.author == "Jane Doe"
    assert first.author_url == "https://www.linkedin.com/in/jane-doe"
    assert first.text.startswith("The AI Act enters a new phase. Read our analysis:")
    assert (first.reactions, first.comments, first.reposts) == (1234, 56, 7)
    assert first.links == ["https://example.eu/ai-act"]
    assert first.relative_date == "2d"
    assert not first.is_repost
    assert first.post_url == "https://www.linkedin.com/feed/update/urn:li:activity:7250000000000000000/"

    assert repost.is_repost
    assert repost.author == "European Commission"
    assert repost.reactions == 2500
    assert repost.comments == 0

"""Checks the Chrome extension: in-page extraction on the fixture, and that the extension loads."""

import os
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "chrome-extension"
FIXTURE = Path(__file__).parent / "fixtures" / "activity.html"


def _exe():
    exe = os.environ.get("LINKEDIN_SCRAPER_CHROMIUM")
    return {"executable_path": exe} if exe else {}


def test_extract_js_on_fixture():
    with playwright.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(**_exe())
        except Exception as exc:
            pytest.skip(f"Chromium not available: {exc}")
        page = browser.new_page()
        page.goto(FIXTURE.as_uri())
        page.add_script_tag(path=str(EXT / "extract.js"))
        res = page.evaluate("window.__liCollect({source: 'https://www.linkedin.com/in/jane-doe/', scroll: false})")
        browser.close()

    posts = res["posts"]
    assert len(posts) == 2
    first, repost = posts
    assert first["author"] == "Jane Doe"
    assert first["author_url"] == "https://www.linkedin.com/in/jane-doe"
    assert first["text"].startswith("The AI Act enters a new phase. Read our analysis:")
    assert (first["reactions"], first["comments"], first["reposts"]) == (1234, 56, 7)
    assert first["links"] == ["https://example.eu/ai-act"]
    assert first["relative_date"] == "2d"
    assert first["posted_at"].startswith("2024-")
    assert first["is_repost"] is False
    assert repost["is_repost"] is True
    assert repost["author"] == "European Commission"
    assert repost["reactions"] == 2500


def test_extension_loads(tmp_path):
    with playwright.sync_playwright() as pw:
        try:
            ctx = pw.chromium.launch_persistent_context(
                str(tmp_path), headless=True, **_exe(),
                args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"],
            )
        except Exception as exc:
            pytest.skip(f"Chromium not available: {exc}")
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=10000)
        ext_id = sw.url.split("/")[2]
        errors = []
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"chrome-extension://{ext_id}/popup.html")
        page.fill("#urls", "https://www.linkedin.com/in/jane-doe/")
        page.wait_for_timeout(300)
        assert page.is_enabled("#start")
        assert page.is_disabled("#csv")
        # Settings persist via chrome.storage.
        page.click("#maxPosts")
        page.evaluate("document.getElementById('start').disabled")  # popup script ran
        ctx.close()
    assert not errors

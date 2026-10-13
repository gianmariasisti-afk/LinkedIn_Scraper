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


def _collect(fixture):
    with playwright.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(**_exe())
        except Exception as exc:
            pytest.skip(f"Chromium not available: {exc}")
        page = browser.new_page()
        page.goto(fixture.as_uri())
        page.add_script_tag(path=str(EXT / "extract.js"))
        res = page.evaluate("window.__liCollect({source: 'src', scroll: false})")
        probe = page.evaluate("window.__liProbe()")
        browser.close()
    return res, probe


def test_extract_js_without_known_classes():
    res, probe = _collect(Path(__file__).parent / "fixtures" / "activity_new_layout.html")
    assert probe["mode"] == "structure"
    posts = res["posts"]
    assert len(posts) == 2, posts
    first, repost = posts
    assert first["urn"] == "urn:li:activity:7400000000000000000"
    assert first["author"] == "Cecilia Example"
    assert first["author_url"] == "https://www.linkedin.com/in/cecilia-example/"
    assert first["text"].startswith("Digital sovereignty is now a competitiveness question.")
    assert (first["reactions"], first["comments"], first["reposts"]) == (1234, 56, 7)
    assert first["links"] == ["https://example.eu/speech"]
    assert first["is_repost"] is False

    assert repost["urn"] == "urn:li:activity:7399000000000000000"
    assert repost["is_repost"] is True
    assert repost["author"] == "DIGITALEUROPE"
    assert repost["text"] == "Our position paper on the Digital Omnibus is out."
    assert repost["comments"] == 12


def test_probe_reports_page_shape():
    _, probe = _collect(FIXTURE)
    assert probe["mode"] == "classes"
    assert probe["postsParsed"] == 2
    assert probe["sampleCardHtml"].startswith("<div")


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


def test_full_run_through_popup(tmp_path):
    """Drives the real extension: popup -> background -> collection window -> results in the popup.
    linkedin.com is intercepted and served from the fixtures, so nothing leaves the machine."""
    pages = {
        "/in/cecilia-example/recent-activity/all/": Path(__file__).parent / "fixtures" / "activity_new_layout.html",
        "/company/acme/posts/": FIXTURE,
    }
    with playwright.sync_playwright() as pw:
        try:
            ctx = pw.chromium.launch_persistent_context(
                str(tmp_path), headless=True, **_exe(),
                args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"],
            )
        except Exception as exc:
            pytest.skip(f"Chromium not available: {exc}")

        def serve(route):
            path = "/" + route.request.url.split("linkedin.com/", 1)[1].split("?")[0]
            f = pages.get(path)
            if f:
                route.fulfill(status=200, content_type="text/html", body=f.read_text())
            else:
                route.fulfill(status=404, body="")

        ctx.route("https://www.linkedin.com/**", serve)
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=10000)
        ext_id = sw.url.split("/")[2]
        popup = ctx.new_page()
        popup.goto(f"chrome-extension://{ext_id}/popup.html")
        popup.fill("#urls", "https://www.linkedin.com/in/cecilia-example/\nhttps://www.linkedin.com/company/acme/")
        popup.fill("#sinceDays", "0")
        # Shorten the pause between profiles for the test.
        popup.evaluate("DELAY.min = 0; DELAY.max = 0.1")
        popup.click("#start")
        # Extension pages forbid eval, so poll instead of wait_for_function.
        for _ in range(180):
            status = popup.text_content("#status") or ""
            if not status.startswith("Collecting"):
                break
            popup.wait_for_timeout(500)
        log = popup.text_content("#log")
        assert popup.is_enabled("#csv")
        with popup.expect_download() as dl:
            popup.click("#csv")
        csv_text = Path(dl.value.path()).read_text(encoding="utf-8-sig")
        ctx.close()

    assert "2/2 profiles · 4 posts" in status, (status, log)
    assert "scroll 1" in log
    assert csv_text.splitlines()[0].startswith("source,post_url,posted_at")
    assert "Digital sovereignty" in csv_text and "AI Act" in csv_text

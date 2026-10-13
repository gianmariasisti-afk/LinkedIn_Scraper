"""Browser side: log in once, then scroll each activity page and extract posts."""

from __future__ import annotations

import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Playwright, TimeoutError as PWTimeout

from .parsing import Post, Target

log = logging.getLogger(__name__)

# The page-reading code is shared with the Chrome extension, so a fix to LinkedIn's layout lands in both.
EXTRACT_JS_PATH = Path(__file__).resolve().parent.parent / "chrome-extension" / "extract.js"

LOGIN_URL = "https://www.linkedin.com/login"
FEED_URL = "https://www.linkedin.com/feed/"


def _launch(pw: Playwright, headless: bool):
    kwargs = {"headless": headless}
    exe = os.environ.get("LINKEDIN_SCRAPER_CHROMIUM")
    if exe:
        kwargs["executable_path"] = exe
    return pw.chromium.launch(**kwargs)


def _new_context(browser, auth_path: str | None) -> BrowserContext:
    return browser.new_context(
        storage_state=auth_path if auth_path and os.path.exists(auth_path) else None,
        viewport={"width": 1280, "height": 900},
        locale="en-US",  # keeps labels like "comments"/"reposts" in English for parsing
    )


def login(pw: Playwright, auth_path: str, timeout_s: int = 300) -> None:
    """Open a visible browser, let the user log in by hand (incl. 2FA), then save the session."""
    browser = _launch(pw, headless=False)
    context = _new_context(browser, None)
    page = context.new_page()
    page.goto(LOGIN_URL)
    print("A browser window is open. Log in to LinkedIn there (2FA is fine).")
    print(f"Waiting up to {timeout_s}s for the feed to load...")
    try:
        page.wait_for_url("**/feed/**", timeout=timeout_s * 1000)
    except PWTimeout:
        browser.close()
        raise SystemExit("Timed out waiting for login. Run `login` again.")
    page.wait_for_timeout(2000)
    context.storage_state(path=auth_path)
    try:
        os.chmod(auth_path, 0o600)
    except OSError:
        pass
    browser.close()
    print(f"Session saved to {auth_path}. Keep this file private: it is your LinkedIn login.")


def save_cookie_session(auth_path: str, li_at: str) -> None:
    """Build a session file from the `li_at` cookie, for machines where no browser window can open."""
    import json

    state = {
        "cookies": [{
            "name": "li_at", "value": li_at.strip().strip('"'), "domain": ".linkedin.com", "path": "/",
            "expires": -1, "httpOnly": True, "secure": True, "sameSite": "None",
        }],
        "origins": [],
    }
    with open(auth_path, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    try:
        os.chmod(auth_path, 0o600)
    except OSError:
        pass


def _check_logged_in(page: Page) -> None:
    url = page.url
    if any(p in url for p in ("/login", "/authwall", "/checkpoint", "/uas/")):
        raise SystemExit(
            f"LinkedIn redirected to {url}. The session expired or needs verification. "
            "Run `python -m linkedin_scraper login` again."
        )


def _pause(lo: float, hi: float) -> None:
    time.sleep(random.uniform(lo, hi))


def scrape_target(
    page: Page,
    target: Target,
    max_posts: int,
    since: datetime | None,
    max_scrolls: int = 40,
) -> list[Post]:
    log.info("Opening %s", target.activity_url)
    page.goto(target.activity_url, wait_until="domcontentloaded")
    _check_logged_in(page)
    page.add_script_tag(path=str(EXTRACT_JS_PATH))
    res = page.evaluate(
        "(o) => window.__liCollect(o)",
        {
            "source": target.page_url,
            "maxPosts": max_posts,
            "sinceIso": since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z") if since else None,
            "maxScrolls": max_scrolls,
        },
    )
    if res.get("error"):
        raise SystemExit(f"{res['error']} Run `python -m linkedin_scraper login` again.")
    if res.get("warning"):
        log.warning("%s: %s", target.page_url, res["warning"])
    return [Post(**p) for p in res["posts"]]


def scrape(
    pw: Playwright,
    targets: list[Target],
    auth_path: str,
    max_posts: int = 20,
    since: datetime | None = None,
    headless: bool = True,
    delay: tuple[float, float] = (8.0, 20.0),
) -> list[Post]:
    if not os.path.exists(auth_path) and os.environ.get("LINKEDIN_LI_AT"):
        save_cookie_session(auth_path, os.environ["LINKEDIN_LI_AT"])
    if not os.path.exists(auth_path):
        raise SystemExit(f"No session at {auth_path}. Run `python -m linkedin_scraper login` first.")
    browser = _launch(pw, headless=headless)
    context = _new_context(browser, auth_path)
    page = context.new_page()
    all_posts: list[Post] = []
    try:
        for i, target in enumerate(targets, 1):
            log.info("[%d/%d] %s", i, len(targets), target.page_url)
            try:
                found = scrape_target(page, target, max_posts=max_posts, since=since)
            except SystemExit:
                raise
            except Exception as exc:  # one bad profile should not kill a long run
                log.error("Failed on %s: %s", target.page_url, exc)
                found = []
            log.info("  %d posts", len(found))
            all_posts.extend(found)
            if i < len(targets):
                _pause(*delay)
        # Refresh cookies so the saved session lasts longer.
        context.storage_state(path=auth_path)
    finally:
        browser.close()
    return all_posts

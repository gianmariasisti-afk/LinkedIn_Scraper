"""Browser side: log in once, then scroll each activity page and extract posts."""

from __future__ import annotations

import logging
import os
import random
import time
from datetime import datetime, timezone

from playwright.sync_api import BrowserContext, Page, Playwright, TimeoutError as PWTimeout

from .parsing import Post, Target, build_post

log = logging.getLogger(__name__)

# LinkedIn changes its markup regularly. When the scraper stops finding posts,
# this is the one place to update. Each entry is a CSS selector list tried in order.
SELECTORS = {
    "post": "div.feed-shared-update-v2[data-urn], div[data-urn^='urn:li:activity:']",
    "text": ".update-components-text, .feed-shared-inline-show-more-text, .feed-shared-update-v2__description",
    "author": ".update-components-actor__title, .update-components-actor__name",
    "author_link": "a.update-components-actor__meta-link, a.update-components-actor__image",
    "date": ".update-components-actor__sub-description",
    "header": ".update-components-header",
    "reactions": ".social-details-social-counts__reactions-count, .social-details-social-counts__social-proof-fallback-number",
    "comments": ".social-details-social-counts__comments",
    "reposts": ".social-details-social-counts__item--right-aligned:not(.social-details-social-counts__comments), button[aria-label*='repost']",
}

# Runs inside the page. Returns plain dicts so the parsing stays in Python and is testable.
_EXTRACT_JS = """
(sel) => {
  const pick = (root, s) => {
    for (const part of s.split(',')) {
      const el = root.querySelector(part.trim());
      if (el) return el;
    }
    return null;
  };
  const txt = (el) => el ? (el.innerText || el.textContent || '').trim() : '';
  // Names are rendered twice: an aria-hidden visible copy and a visually-hidden one for screen readers.
  const visible = (el) => el ? txt(el.querySelector('[aria-hidden="true"]') || el) : '';
  const seen = new Set();
  const out = [];
  for (const card of document.querySelectorAll(sel.post)) {
    const urn = card.getAttribute('data-urn') || '';
    // Nested cards (e.g. the original inside a repost) share ancestors; keep the outermost.
    if (!urn || seen.has(urn) || card.parentElement?.closest('[data-urn^="urn:li:activity:"]')) continue;
    seen.add(urn);
    const textEl = pick(card, sel.text);
    const authorLink = pick(card, sel.author_link);
    const commentsEl = pick(card, sel.comments);
    let repostsText = '';
    for (const part of sel.reposts.split(',')) {
      for (const el of card.querySelectorAll(part.trim())) {
        const t = txt(el) || el.getAttribute('aria-label') || '';
        if (/repost/i.test(t)) { repostsText = t; break; }
      }
      if (repostsText) break;
    }
    out.push({
      urn,
      text: textEl ? (textEl.textContent || '') : '',
      author: visible(pick(card, sel.author)),
      authorUrl: authorLink ? authorLink.href : '',
      date: txt(pick(card, sel.date)),
      header: txt(pick(card, sel.header)),
      reactions: txt(pick(card, sel.reactions)),
      comments: txt(commentsEl) || (commentsEl && commentsEl.getAttribute('aria-label')) || '',
      reposts: repostsText,
      links: textEl ? [...textEl.querySelectorAll('a[href]')]
        .map(a => a.href)
        .filter(h => !h.includes('/feed/hashtag/') && !h.includes('linkedin.com/in/')) : [],
    });
  }
  return out;
}
"""

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
    try:
        page.wait_for_selector(SELECTORS["post"].split(",")[0], timeout=15000)
    except PWTimeout:
        log.warning("No posts found for %s (no activity, private, or selectors out of date)", target.page_url)
        return []

    posts: dict[str, Post] = {}
    stale_rounds = 0
    for _ in range(max_scrolls):
        before = len(posts)
        for raw in page.evaluate(_EXTRACT_JS, SELECTORS):
            post = build_post(raw, target)
            if post and post.urn not in posts:
                posts[post.urn] = post

        ordered = sorted(posts.values(), key=lambda p: p.posted_at, reverse=True)
        if len(posts) >= max_posts:
            break
        # Pinned posts can be old, so judge by the oldest post loaded, not the first.
        if since and ordered and ordered[-1].posted_at and ordered[-1].posted_at < since.isoformat():
            break
        stale_rounds = stale_rounds + 1 if len(posts) == before else 0
        if stale_rounds >= 3:
            break

        page.mouse.wheel(0, random.randint(2500, 4000))
        _pause(1.5, 3.5)
        # Company pages and long feeds use a "Show more results" button instead of infinite scroll.
        more = page.locator("button.scaffold-finite-scroll__load-button")
        if more.count() and more.first.is_visible():
            more.first.click()
            _pause(1.5, 3.0)

    result = sorted(posts.values(), key=lambda p: p.posted_at, reverse=True)
    if since:
        result = [p for p in result if p.posted_at and p.posted_at >= since.isoformat()]
    return result[:max_posts]


def scrape(
    pw: Playwright,
    targets: list[Target],
    auth_path: str,
    max_posts: int = 20,
    since: datetime | None = None,
    headless: bool = True,
    delay: tuple[float, float] = (8.0, 20.0),
) -> list[Post]:
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


def utcnow() -> datetime:
    return datetime.now(timezone.utc)

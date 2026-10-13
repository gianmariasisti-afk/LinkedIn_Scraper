// Injected into a LinkedIn activity page. Defines window.__liCollect(opts), which scrolls the
// page, reads every post card and resolves with an array of post objects.
// LinkedIn changes its markup every few months: when posts stop showing up, update SELECTORS.

(() => {
  if (window.__liCollect) return;

  const SELECTORS = {
    post: "div.feed-shared-update-v2[data-urn], div[data-urn^='urn:li:activity:']",
    text: ".update-components-text, .feed-shared-inline-show-more-text, .feed-shared-update-v2__description",
    author: ".update-components-actor__title, .update-components-actor__name",
    authorLink: "a.update-components-actor__meta-link, a.update-components-actor__image",
    date: ".update-components-actor__sub-description",
    header: ".update-components-header",
    reactions: ".social-details-social-counts__reactions-count, .social-details-social-counts__social-proof-fallback-number",
    comments: ".social-details-social-counts__comments",
    reposts: ".social-details-social-counts__item--right-aligned:not(.social-details-social-counts__comments), button[aria-label*='repost']",
    loadMore: "button.scaffold-finite-scroll__load-button",
  };

  const pick = (root, s) => {
    for (const part of s.split(",")) {
      const el = root.querySelector(part.trim());
      if (el) return el;
    }
    return null;
  };
  const txt = (el) => (el ? (el.innerText || el.textContent || "").trim() : "");
  // Names are rendered twice: an aria-hidden visible copy and a visually-hidden one for screen readers.
  const visible = (el) => (el ? txt(el.querySelector('[aria-hidden="true"]') || el) : "");

  const clean = (s) =>
    (s || "")
      .replace(/ /g, " ")
      .replace(/[ \t]+/g, " ")
      .replace(/\n\s*\n\s*\n+/g, "\n\n")
      .replace(/\s*…\s*(see more|more)\s*$/i, "")
      .trim();

  // '1,234' -> 1234, '1.2K' -> 1200, '12 comments' -> 12
  const count = (s) => {
    const m = /(\d+(?:[.,]\d+)*)\s*([KkMm])?/.exec(s || "");
    if (!m) return 0;
    if (m[2]) return Math.round(parseFloat(m[1].replace(",", ".")) * (/k/i.test(m[2]) ? 1e3 : 1e6));
    return parseInt(m[1].replace(/[.,]/g, ""), 10);
  };

  // LinkedIn activity IDs embed the creation time: the top 41 bits are Unix milliseconds.
  const idTime = (id) => new Date(Number(BigInt(id) >> 22n)).toISOString();

  function readCards(source) {
    const out = [];
    for (const card of document.querySelectorAll(SELECTORS.post)) {
      const urn = card.getAttribute("data-urn") || "";
      const m = /urn:li:(?:activity|share|ugcPost):(\d+)/.exec(urn);
      // Nested cards (the original inside a repost) are skipped; the outer card is the post.
      if (!m || card.parentElement?.closest('[data-urn^="urn:li:activity:"]')) continue;
      const textEl = pick(card, SELECTORS.text);
      const authorLink = pick(card, SELECTORS.authorLink);
      const commentsEl = pick(card, SELECTORS.comments);
      let repostsText = "";
      outer: for (const part of SELECTORS.reposts.split(",")) {
        for (const el of card.querySelectorAll(part.trim())) {
          const t = txt(el) || el.getAttribute("aria-label") || "";
          if (/repost/i.test(t)) { repostsText = t; break outer; }
        }
      }
      out.push({
        source,
        post_url: `https://www.linkedin.com/feed/update/urn:li:activity:${m[1]}/`,
        urn,
        posted_at: idTime(m[1]),
        author: clean(visible(pick(card, SELECTORS.author))).split("\n")[0],
        author_url: authorLink ? authorLink.href.split("?")[0] : "",
        is_repost: /repost/i.test(txt(pick(card, SELECTORS.header))),
        text: clean(textEl ? textEl.textContent : ""),
        reactions: count(txt(pick(card, SELECTORS.reactions))),
        comments: count(txt(commentsEl) || (commentsEl && commentsEl.getAttribute("aria-label"))),
        reposts: count(repostsText),
        relative_date: clean(txt(pick(card, SELECTORS.date))).split("•")[0].trim(),
        links: textEl
          ? [...textEl.querySelectorAll("a[href]")]
              .map((a) => a.href)
              .filter((h) => !h.includes("/feed/hashtag/") && !h.includes("linkedin.com/in/"))
          : [],
      });
    }
    return out;
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const jitter = (lo, hi) => lo + Math.random() * (hi - lo);

  window.__liCollect = async ({ source, maxPosts = 20, sinceIso = null, maxScrolls = 40, scroll = true } = {}) => {
    const url = location.href;
    if (/\/(login|authwall|checkpoint|uas)\//.test(url)) {
      return { error: "Not logged in to LinkedIn (or a security check is showing). Log in and try again." };
    }
    // Wait up to 15s for the first post to render.
    for (let i = 0; i < 30 && !document.querySelector(SELECTORS.post); i++) await sleep(500);

    const posts = new Map();
    let stale = 0;
    for (let i = 0; i < (scroll ? maxScrolls : 1); i++) {
      const before = posts.size;
      for (const p of readCards(source || url)) if (!posts.has(p.urn)) posts.set(p.urn, p);
      const sorted = [...posts.values()].sort((a, b) => b.posted_at.localeCompare(a.posted_at));
      if (!scroll || posts.size >= maxPosts) break;
      // Pinned posts can be old, so judge by the oldest post loaded, not the first.
      if (sinceIso && sorted.length && sorted[sorted.length - 1].posted_at < sinceIso) break;
      stale = posts.size === before ? stale + 1 : 0;
      if (stale >= 3) break;
      window.scrollBy(0, jitter(2500, 4000));
      await sleep(jitter(1500, 3500));
      const more = document.querySelector(SELECTORS.loadMore);
      if (more && more.offsetParent) { more.click(); await sleep(jitter(1500, 3000)); }
    }
    let result = [...posts.values()].sort((a, b) => b.posted_at.localeCompare(a.posted_at));
    if (sinceIso) result = result.filter((p) => p.posted_at >= sinceIso);
    return { posts: result.slice(0, maxPosts) };
  };
})();

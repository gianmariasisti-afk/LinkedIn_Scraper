// Injected into a LinkedIn activity page. Defines:
//   window.__liCollect(opts)  scrolls the page, reads every post, resolves with { posts } or { error }
//   window.__liProbe()        reports what the page looks like, for debugging when nothing is found
//
// LinkedIn changes its markup often and ships different layouts to different accounts, so posts are
// found in two ways: known class names first, then a structural fallback that needs no class names
// (any element carrying a post ID, widened to the smallest block that holds a Like/Comment bar).

(() => {
  if (window.__liCollect) return;

  const SELECTORS = {
    post: "div.feed-shared-update-v2[data-urn], div[data-urn^='urn:li:activity:']",
    text: "[data-testid='expandable-text-box'], .update-components-text, .feed-shared-inline-show-more-text, .feed-shared-update-v2__description",
    author: ".update-components-actor__title, .update-components-actor__name",
    authorLink: "a.update-components-actor__meta-link, a.update-components-actor__image",
    date: ".update-components-actor__sub-description",
    header: ".update-components-header",
    reactions: ".social-details-social-counts__reactions-count, .social-details-social-counts__social-proof-fallback-number",
    comments: ".social-details-social-counts__comments",
    reposts: ".social-details-social-counts__item--right-aligned:not(.social-details-social-counts__comments), button[aria-label*='repost']",
    loadMore: "button.scaffold-finite-scroll__load-button",
  };

  const ID_RE = /urn(?::|%3A)li(?::|%3A)(activity|ugcPost|share)(?::|%3A)(\d{18,20})/i;
  const ID_RE_G = new RegExp(ID_RE.source, "gi");
  // Action-bar labels in the languages LinkedIn most often serves in the EU.
  const ACTION_RE = /^(like|react|comment|repost|send|consiglia|commenta|diffondi|invia|j.aime|réagir|commenter|republier|envoyer|gefällt mir|kommentieren|reposten|senden|recomendar|comentar|compartir|enviar|vind ik leuk|reageren)\b/i;
  const COMMENTS_RE = /([\d.,]+\s*[KkMm]?)\s*(comments?|commenti|commento|commentaires?|kommentare?|comentarios?|reacties|reactie)\b/i;
  const REPOSTS_RE = /([\d.,]+\s*[KkMm]?)\s*(reposts?|diffusioni|diffusione|republications?|repostings?|veces compartido|compartidos?)\b/i;
  const REACTIONS_RE = /([\d.,]+\s*[KkMm]?)\s*(reactions?|reazioni|reazione|réactions?|reaktionen|reacciones|likes?)\b/i;
  const REPOST_HEADER_RE = /(reposted|ha diffuso|a republié|hat .* repostet|ha compartido|heeft .* gerepost)/i;

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
      .replace(/\s*…\s*(see more|more|altro|plus|mehr|más)\s*$/i, "")
      .trim();

  // '1,234' -> 1234, '1.2K' -> 1200, '12 comments' -> 12
  const count = (s) => {
    const m = /(\d+(?:[.,]\d+)*)\s*([KkMm])?/.exec(s || "");
    if (!m) return 0;
    if (m[2]) return Math.round(parseFloat(m[1].replace(",", ".")) * (/k/i.test(m[2]) ? 1e3 : 1e6));
    return parseInt(m[1].replace(/[.,]/g, ""), 10);
  };

  // LinkedIn post IDs embed the creation time: the top 41 bits are Unix milliseconds.
  const idTime = (id) => new Date(Number(BigInt(id) >> 22n)).toISOString();

  const attrsText = (el) => {
    let s = "";
    for (const a of el.attributes) s += " " + a.value;
    return s;
  };

  // First post ID referenced by the element itself or anything inside it, in document order.
  function firstId(card) {
    const own = ID_RE.exec(attrsText(card));
    if (own) return own[2];
    const walker = document.createTreeWalker(card, NodeFilter.SHOW_ELEMENT);
    for (let el = walker.nextNode(); el; el = walker.nextNode()) {
      const m = ID_RE.exec(attrsText(el));
      if (m) return m[2];
    }
    return null;
  }

  const isActionButton = (b) => ACTION_RE.test((b.getAttribute("aria-label") || txt(b)).trim());
  const hasActionBar = (el) => [...el.querySelectorAll("button")].filter(isActionButton).length >= 2;

  // Structural fallback: every element whose attributes mention a post ID, widened to its card.
  function findCardsStructurally() {
    const root = document.querySelector("main") || document.body;
    const cards = new Set();
    for (const el of root.querySelectorAll("*")) {
      if (!ID_RE.test(attrsText(el))) continue;
      let card = el;
      for (let depth = 0; card && card !== root && depth < 25; depth++, card = card.parentElement) {
        if (hasActionBar(card)) break;
      }
      if (card && card !== root && hasActionBar(card)) cards.add(card);
    }
    // Drop blocks that contain other cards: they are list wrappers, not posts. (The original inside a
    // repost has no action bar of its own, so it never becomes a card.)
    return [...cards].filter((c) => ![...cards].some((o) => o !== c && c.contains(o)));
  }

  function findCards() {
    const legacy = [...document.querySelectorAll(SELECTORS.post)].filter(
      (c) => !c.parentElement?.closest('[data-urn^="urn:li:activity:"]'),
    );
    return legacy.length ? { cards: legacy, mode: "classes" } : { cards: findCardsStructurally(), mode: "structure" };
  }

  function longestTextBlock(card) {
    let best = "";
    for (const el of card.querySelectorAll("[dir='ltr'], p, span.break-words")) {
      if (el.closest("button")) continue;
      const t = (el.textContent || "").trim();
      if (t.length > best.length) best = t;
    }
    return best;
  }

  function findAuthor(card) {
    const el = pick(card, SELECTORS.author);
    if (el) return { name: visible(el), url: (pick(card, SELECTORS.authorLink) || {}).href || "" };
    for (const a of card.querySelectorAll("a[href*='/in/'], a[href*='/company/']")) {
      const name = visible(a).split("\n")[0].trim();
      if (name) return { name, url: a.href };
    }
    return { name: "", url: "" };
  }

  // Reads counts from the classes if present, otherwise from labels like "56 comments" anywhere in the card.
  function counts(card) {
    // aria-labels first: they are the social counts, while the card text also contains the post body.
    const labels = [];
    for (const el of card.querySelectorAll("[aria-label]")) labels.push(el.getAttribute("aria-label"));
    labels.push(txt(card));
    const all = labels.join("\n");
    const viaRe = (re) => { const m = re.exec(all); return m ? count(m[1]) : 0; };

    const reactEl = pick(card, SELECTORS.reactions);
    const commentsEl = pick(card, SELECTORS.comments);
    let repostsText = "";
    outer: for (const part of SELECTORS.reposts.split(",")) {
      for (const el of card.querySelectorAll(part.trim())) {
        const t = txt(el) || el.getAttribute("aria-label") || "";
        if (/repost/i.test(t)) { repostsText = t; break outer; }
      }
    }
    return {
      reactions: reactEl ? count(txt(reactEl)) : viaRe(REACTIONS_RE),
      comments: commentsEl ? count(txt(commentsEl) || commentsEl.getAttribute("aria-label")) : viaRe(COMMENTS_RE),
      reposts: repostsText ? count(repostsText) : viaRe(REPOSTS_RE),
    };
  }

  function readCards(source) {
    const out = [];
    const { cards } = findCards();
    for (const card of cards) {
      const id = firstId(card);
      if (!id) continue;
      const textEl = pick(card, SELECTORS.text);
      const author = findAuthor(card);
      const dateEl = pick(card, SELECTORS.date);
      const header = txt(pick(card, SELECTORS.header)) || txt(card).split("\n").slice(0, 2).join(" ");
      out.push({
        source,
        post_url: `https://www.linkedin.com/feed/update/urn:li:activity:${id}/`,
        urn: `urn:li:activity:${id}`,
        posted_at: idTime(id),
        author: clean(author.name).split("\n")[0],
        author_url: (author.url || "").split("?")[0],
        is_repost: REPOST_HEADER_RE.test(header),
        text: clean(textEl ? textEl.textContent : longestTextBlock(card)),
        ...counts(card),
        relative_date: dateEl ? clean(txt(dateEl)).split("•")[0].trim() : "",
        links: [...(textEl || card).querySelectorAll("a[href]")]
          .map((a) => a.href)
          .filter((h) => !/linkedin\.com|^javascript:|^#/.test(h) || /lnkd\.in/.test(h)),
      });
    }
    return out;
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const jitter = (lo, hi) => lo + Math.random() * (hi - lo);
  const progress = (msg) => {
    try { chrome.runtime.sendMessage({ type: "progress", msg }); } catch {}
  };

  window.__liProbe = () => {
    const root = document.querySelector("main") || document.body;
    const ids = new Set();
    for (const el of root.querySelectorAll("*")) for (const m of attrsText(el).matchAll(ID_RE_G)) ids.add(m[2]);
    const { cards, mode } = findCards();
    return {
      url: location.href,
      title: document.title,
      loggedOut: /\/(login|authwall|checkpoint|uas)\//.test(location.href),
      legacyCards: document.querySelectorAll(SELECTORS.post).length,
      postIdsOnPage: ids.size,
      cardsFound: cards.length,
      mode,
      postsParsed: readCards(location.href).length,
      sampleCardHtml: cards[0] ? cards[0].outerHTML.slice(0, 60000) : "",
      mainHtmlSample: cards[0] ? "" : root.outerHTML.slice(0, 200000),
    };
  };

  window.__liCollect = async ({ source, maxPosts = 20, sinceIso = null, maxScrolls = 40, scroll = true } = {}) => {
    if (/\/(login|authwall|checkpoint|uas)\//.test(location.href)) {
      return { error: "Not logged in to LinkedIn (or a security check is showing). Log in and try again." };
    }
    // Wait up to 30s for the first post to render, nudging the page now and then: some layouts only
    // load the feed once the page has been scrolled.
    for (let i = 0; i < 60 && !findCards().cards.length; i++) {
      if (i % 10 === 9) { window.scrollBy(0, 600); await sleep(300); window.scrollBy(0, -600); }
      await sleep(500);
    }

    const posts = new Map();
    let stale = 0;
    for (let i = 0; i < (scroll ? maxScrolls : 1); i++) {
      const before = posts.size;
      for (const p of readCards(source || location.href)) if (!posts.has(p.urn)) posts.set(p.urn, p);
      progress(`  scroll ${i + 1}: ${posts.size} posts`);
      const sorted = [...posts.values()].sort((a, b) => b.posted_at.localeCompare(a.posted_at));
      if (!scroll || posts.size >= maxPosts) break;
      // Pinned posts can be old, so judge by the oldest post loaded, not the first.
      if (sinceIso && sorted.length && sorted[sorted.length - 1].posted_at < sinceIso) break;
      stale = posts.size === before ? stale + 1 : 0;
      if (stale >= 3) break;
      const scroller = document.scrollingElement || document.documentElement;
      scroller.scrollBy(0, jitter(2500, 4000));
      // Some layouts scroll an inner container instead of the window.
      const inner = document.querySelector("main")?.closest("[class*='scaffold'], [class*='scroll']");
      if (inner && inner.scrollHeight > inner.clientHeight) inner.scrollBy(0, 3000);
      await sleep(jitter(1500, 3500));
      const more = document.querySelector(SELECTORS.loadMore) ||
        [...document.querySelectorAll("main button")].find((b) => /^(show more results|mostra altri risultati|afficher plus de résultats)/i.test(txt(b)));
      if (more && more.offsetParent) { more.click(); await sleep(jitter(1500, 3000)); }
    }
    let result = [...posts.values()].sort((a, b) => b.posted_at.localeCompare(a.posted_at));
    if (sinceIso) result = result.filter((p) => p.posted_at >= sinceIso);
    if (!posts.size) {
      const p = window.__liProbe();
      return {
        posts: [],
        warning: `No posts recognised (${p.postIdsOnPage} post IDs, ${p.cardsFound} cards; ` +
          `tab ${document.visibilityState}, page "${document.title.slice(0, 60)}", ${location.pathname}). ` +
          `Use "Diagnose this page" on that tab.`,
      };
    }
    return { posts: result.slice(0, maxPosts) };
  };
})();

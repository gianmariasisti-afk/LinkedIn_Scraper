// Runs the collection job so it keeps going after the popup closes.
// Progress and results live in chrome.storage.local under "job"; the popup just renders them.

const PROFILE_RE = /^\/(in|company|school|showcase)\/([^/?#]+)/i;

function parseTarget(raw) {
  let url = raw.trim().split(",")[0].replace(/^"|"$/g, "");
  if (!url || url.startsWith("#")) return null;
  if (!/^https?:/.test(url)) url = "https://www.linkedin.com/" + url.replace(/^\/+/, "");
  let u;
  try { u = new URL(url); } catch { return null; }
  if (!u.hostname.endsWith("linkedin.com")) return null;
  const m = PROFILE_RE.exec(u.pathname);
  if (!m) return null;
  const kind = m[1].toLowerCase();
  const page = `https://www.linkedin.com/${kind}/${m[2]}/`;
  return { page, activity: kind === "in" ? `${page}recent-activity/all/` : `${page}posts/?feedView=all` };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = (lo, hi) => lo + Math.random() * (hi - lo);

let stopRequested = false;
let running = false;

// All job writes go through one queue so progress lines and results never overwrite each other.
let writes = Promise.resolve();
function setJob(patch) {
  writes = writes.then(async () => {
    const { job = {} } = await chrome.storage.local.get("job");
    const next = { ...job, ...(typeof patch === "function" ? patch(job) : patch) };
    await chrome.storage.local.set({ job: next });
    return next;
  });
  return writes;
}

function log(line) {
  return setJob((job) => ({
    log: [...(job.log || []), `${new Date().toLocaleTimeString()}  ${line}`].slice(-200),
  }));
}

function waitForLoad(tabId, timeoutMs = 30000) {
  return new Promise((resolve) => {
    const done = () => { chrome.tabs.onUpdated.removeListener(listener); clearTimeout(t); resolve(); };
    const listener = (id, info) => { if (id === tabId && info.status === "complete") done(); };
    const t = setTimeout(done, timeoutMs);
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function collectFromTab(tabId, opts) {
  await chrome.scripting.executeScript({ target: { tabId }, files: ["extract.js"] });
  const run = chrome.scripting.executeScript({
    target: { tabId },
    func: (o) => window.__liCollect(o),
    args: [opts],
  });
  // A page that never finishes (stuck spinner, hidden window) should not hang the whole list.
  const timeout = new Promise((resolve) =>
    setTimeout(() => resolve([{ result: { error: "Timed out after 4 minutes on this page" } }]), 240000));
  const [{ result }] = await Promise.race([run, timeout]);
  return result || { error: "No result from page" };
}

async function probeTab(tabId) {
  await chrome.scripting.executeScript({ target: { tabId }, files: ["extract.js"] });
  const [{ result }] = await chrome.scripting.executeScript({ target: { tabId }, func: () => window.__liProbe() });
  return result;
}

async function runList({ urls, maxPosts, sinceDays, delayMin, delayMax }) {
  if (running) return;
  running = true;
  stopRequested = false;
  // Calling an extension API every 20s keeps the service worker alive during long pauses.
  const keepAlive = setInterval(() => chrome.runtime.getPlatformInfo(), 20000);

  const seen = new Set();
  const targets = [];
  for (const line of urls.split(/\n/)) {
    const t = parseTarget(line);
    if (t && !seen.has(t.page)) { seen.add(t.page); targets.push(t); }
  }
  const sinceIso = sinceDays > 0 ? new Date(Date.now() - sinceDays * 864e5).toISOString() : null;
  await setJob(() => ({ status: "running", total: targets.length, done: 0, posts: [], log: [], error: null, startedAt: Date.now() }));
  if (!targets.length) {
    await setJob({ status: "error", error: "No LinkedIn profile or company URLs found." });
    running = false; clearInterval(keepAlive);
    return;
  }

  // A normal tab in the user's current window, brought to the front for each profile. LinkedIn did not
  // render posts in a separate extension-opened window, while the same page in a regular tab worked.
  const tab = await chrome.tabs.create({ url: "about:blank", active: true });
  const tabId = tab.id;
  let all = [];
  try {
    for (let i = 0; i < targets.length; i++) {
      if (stopRequested) { await log("Stopped."); break; }
      const t = targets[i];
      await setJob({ current: t.page });
      await log(`[${i + 1}/${targets.length}] ${t.page}`);
      try {
        const loaded = waitForLoad(tabId);
        const current = await chrome.tabs.update(tabId, { url: t.activity, active: true });
        await loaded;
        await chrome.windows.update(current.windowId, { focused: true });
        const res = await collectFromTab(tabId, { source: t.page, maxPosts, sinceIso });
        if (res.warning) await log(`  ${res.warning}`);
        if (res.error) {
          await log(`  ${res.error}`);
          if (/Not logged in/.test(res.error)) { await setJob({ status: "error", error: res.error }); break; }
        } else {
          all = all.concat(res.posts);
          await log(`  ${res.posts.length} posts`);
        }
      } catch (e) {
        await log(`  failed: ${e.message}`);
      }
      await setJob({ done: i + 1, posts: all });
      if (i < targets.length - 1 && !stopRequested) await sleep(jitter(delayMin * 1000, delayMax * 1000));
    }
  } finally {
    clearInterval(keepAlive);
    running = false;
    try { await chrome.tabs.remove(tabId); } catch {}
    const job = await setJob({}); // waits for queued writes, returns the latest job
    if (job.status === "running") await setJob({ status: stopRequested ? "stopped" : "done", current: null });
    await log(`Finished: ${all.length} posts.`);
  }
}

async function runCurrentTab({ tabId, url, maxPosts, sinceDays }) {
  const t = parseTarget(url);
  const sinceIso = sinceDays > 0 ? new Date(Date.now() - sinceDays * 864e5).toISOString() : null;
  await setJob(() => ({ status: "running", total: 1, done: 0, posts: [], log: [], error: null, current: url }));
  await log(`Collecting from ${url}`);
  try {
    // Profile pages show a short preview; posts live on the activity page.
    if (t && !/recent-activity|\/posts/.test(url)) {
      const loaded = waitForLoad(tabId);
      await chrome.tabs.update(tabId, { url: t.activity });
      await loaded;
    }
    const res = await collectFromTab(tabId, { source: t ? t.page : url, maxPosts, sinceIso });
    if (res.error) return void (await setJob({ status: "error", error: res.error }));
    if (res.warning) await log(res.warning);
    await setJob({ status: "done", done: 1, posts: res.posts, current: null });
    await log(`Finished: ${res.posts.length} posts.`);
  } catch (e) {
    await setJob({ status: "error", error: e.message });
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg.type === "probe") {
    probeTab(msg.tabId).then(reply, (e) => reply({ error: e.message }));
    return true; // reply arrives asynchronously
  }
  if (msg.type === "progress") { log(msg.msg); return; }
  if (msg.type === "start") runList(msg);
  else if (msg.type === "current") runCurrentTab(msg);
  else if (msg.type === "stop") stopRequested = true;
  reply({ ok: true });
});

// If the browser killed the service worker mid-run, don't leave the popup stuck on "running".
chrome.storage.local.get("job").then(({ job }) => {
  if (job && job.status === "running" && !running) {
    setJob({ status: "stopped", error: "Interrupted (browser closed or extension reloaded). Partial results kept." });
  }
});

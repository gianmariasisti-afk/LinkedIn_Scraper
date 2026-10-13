const $ = (id) => document.getElementById(id);
const FIELDS = ["source", "post_url", "posted_at", "relative_date", "author", "author_url", "is_repost",
                "text", "reactions", "comments", "reposts", "links", "urn"];
// Pause between profiles, in seconds. Keeps traffic close to a person browsing.
const DELAY = { min: 8, max: 20 };

let currentPosts = [];

async function loadSettings() {
  const { settings = {} } = await chrome.storage.local.get("settings");
  if (settings.urls) $("urls").value = settings.urls;
  if (settings.maxPosts) $("maxPosts").value = settings.maxPosts;
  if (settings.sinceDays != null) $("sinceDays").value = settings.sinceDays;
}

function readSettings() {
  const s = {
    urls: $("urls").value,
    maxPosts: Math.max(1, parseInt($("maxPosts").value, 10) || 20),
    sinceDays: Math.max(0, parseInt($("sinceDays").value, 10) || 0),
  };
  chrome.storage.local.set({ settings: s });
  return s;
}

function render(job) {
  job = job || {};
  const running = job.status === "running";
  $("start").disabled = running;
  $("current").disabled = running;
  $("stop").disabled = !running;
  currentPosts = job.posts || [];
  $("csv").disabled = $("json").disabled = currentPosts.length === 0;

  const labels = { running: "Collecting…", done: "Done", stopped: "Stopped", error: "Error" };
  $("status").textContent = job.status
    ? `${labels[job.status] || job.status} · ${job.done || 0}/${job.total || 0} profiles · ${currentPosts.length} posts`
    : "";
  $("progress").hidden = !running;
  $("progress").max = job.total || 1;
  $("progress").value = job.done || 0;
  $("error").textContent = job.error || "";
  $("log").textContent = (job.log || []).join("\n");
  $("log").scrollTop = $("log").scrollHeight;
}

function csvCell(v) {
  if (Array.isArray(v)) v = v.join(" ");
  v = v == null ? "" : String(v);
  return /[",\n\r]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

function download(name, content, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([content], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
}

const stamp = () => new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");

$("start").onclick = () => {
  const s = readSettings();
  chrome.runtime.sendMessage({ type: "start", ...s, delayMin: DELAY.min, delayMax: DELAY.max });
};

$("current").onclick = async () => {
  const s = readSettings();
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url || !tab.url.startsWith("https://www.linkedin.com/")) {
    $("error").textContent = "Open a LinkedIn profile or company page first.";
    return;
  }
  chrome.runtime.sendMessage({ type: "current", tabId: tab.id, url: tab.url, maxPosts: s.maxPosts, sinceDays: s.sinceDays });
};

$("stop").onclick = () => chrome.runtime.sendMessage({ type: "stop" });

$("csv").onclick = () => {
  const rows = [FIELDS.join(",")].concat(currentPosts.map((p) => FIELDS.map((f) => csvCell(p[f])).join(",")));
  // BOM so Excel reads accented characters correctly.
  download(`linkedin-posts-${stamp()}.csv`, "﻿" + rows.join("\r\n"), "text/csv;charset=utf-8");
};

$("json").onclick = () =>
  download(`linkedin-posts-${stamp()}.json`, JSON.stringify(currentPosts, null, 2), "application/json");

chrome.storage.onChanged.addListener((changes) => { if (changes.job) render(changes.job.newValue); });
loadSettings();
chrome.storage.local.get("job").then(({ job }) => render(job));

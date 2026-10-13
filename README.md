# LinkedIn Scraper

Collects recent posts from a list of LinkedIn profiles and company pages and saves them to CSV and JSON. It runs a real Chromium browser with your own LinkedIn session, so it sees what you see when logged in.

For each post you get: author, post URL, exact publish time (UTC), text, reactions, comments, reposts, whether it is a repost, and outbound links.

## Option A: Chrome extension (easiest)

No installs. Works inside the Chrome you are already logged into.

1. Download this repo (green **Code** button → **Download ZIP**) and unzip it.
2. In Chrome, open `chrome://extensions`, switch on **Developer mode** (top right), click **Load unpacked**, and pick the `chrome-extension` folder.
3. Pin the extension (puzzle icon in the toolbar → pin **LinkedIn Post Collector**).
4. Make sure you are logged in to LinkedIn, click the extension icon, paste your profile/company URLs, and press **Collect from list**.
5. A second Chrome window opens in front and works through the list on its own (8–20 s pause between profiles). Leave it visible: Chrome pauses pages in hidden or fully covered windows, especially on macOS. Put it side by side with your main window if you want to keep working. The popup can be closed and reopened to check progress.
6. When it says **Done**, click **Download CSV** (opens in Excel) or **Download JSON**.

**This page only** collects posts from the profile or company page open in your current tab.

**If a profile returns 0 posts:** open that profile's activity page in a normal tab, scroll a little, open the extension and click **Diagnose this page**. It reports how many posts it can see and, if it reads none, downloads a small diagnostic file describing the page layout. That file is what's needed to adapt the extension to LinkedIn's current layout (the code is `chrome-extension/extract.js`).

## Option B: Python command line

For scheduled runs or servers. Same output, more setup.

### Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 1. Log in once

```bash
python -m linkedin_scraper login
```

A browser window opens. Log in by hand (2FA works). When your feed loads, the session is saved to `auth.json`. That file is your login: keep it private. It is git-ignored.

#### No browser window available (servers, cloud sessions)

Log in to LinkedIn in your normal browser, open DevTools → Application → Cookies → `https://www.linkedin.com`, and copy the value of `li_at`. Set it as an environment variable (or an environment secret):

```bash
export LINKEDIN_LI_AT='AQEDAR...'
```

When `auth.json` is missing, `scrape` builds it from this cookie. Treat the value like a password: anyone holding it is logged in as you. Logging out of LinkedIn invalidates it.

### 2. Scrape

Put one URL per line in a file (see `profiles.example.txt`; a CSV with the URL in the first column also works):

```bash
python -m linkedin_scraper scrape -i profiles.txt --since 30d -n 25
```

Or pass URLs directly:

```bash
python -m linkedin_scraper scrape \
  -u https://www.linkedin.com/in/some-mep/ \
  -u https://www.linkedin.com/company/european-commission/
```

Results land in `output/posts-YYYYMMDD-HHMMSS.csv` and `.json`. The CSV opens cleanly in Excel, accents included.

| Option | Default | Meaning |
|---|---|---|
| `-n, --max-posts` | 20 | Max posts per profile |
| `--since` | none | `30d`, `2w`, or a date like `2025-01-31` |
| `-o, --out` | `output/` | Output folder |
| `--delay MIN MAX` | `8 20` | Random pause in seconds between profiles |
| `--show-browser` | off | Watch it work |
| `--auth` | `auth.json` | Session file, e.g. one per account |
| `-v` | off | Debug logging |

## How it works

- Visits `/in/<name>/recent-activity/all/` for people and `/company/<name>/posts/` for organisations, scrolls, and reads each post card.
- The publish time comes from the post ID itself (LinkedIn IDs embed a millisecond timestamp), so it is exact, not "2d ago".
- The page-reading code is `chrome-extension/extract.js`, shared by the extension and the Python version. It first tries LinkedIn's known class names, then falls back to a layout-independent method: any element carrying a post ID, widened to the block that holds its Like/Comment bar.

## Limits and risk

- **LinkedIn's User Agreement prohibits automated scraping.** Running this uses your account, and LinkedIn can restrict or ban accounts that scrape. Keep volumes modest (tens of profiles per run, not thousands), keep the default delays, and consider a secondary account.
- **GDPR applies.** Posts are personal data. If you store or process them in the EU you need a lawful basis (usually legitimate interest, documented), a retention limit, and a purpose you could explain to the people concerned. Public figures' professional posts are the lowest-risk case.
- If LinkedIn shows a security check, the run stops with a message. Run `login` again.
- Only posts LinkedIn shows you are captured: private profiles or posts outside your network visibility will be missing.

## Tests

```bash
pip install pytest
pytest
```

`tests/test_extract.py` runs the extraction against a saved mock page in headless Chromium. It does not touch linkedin.com.

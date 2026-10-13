# LinkedIn Scraper

Collects recent posts from a list of LinkedIn profiles and company pages and saves them to CSV and JSON. It runs a real Chromium browser with your own LinkedIn session, so it sees what you see when logged in.

For each post you get: author, post URL, exact publish time (UTC), text, reactions, comments, reposts, whether it is a repost, and outbound links.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## 1. Log in once

```bash
python -m linkedin_scraper login
```

A browser window opens. Log in by hand (2FA works). When your feed loads, the session is saved to `auth.json`. That file is your login: keep it private. It is git-ignored.

### No browser window available (servers, cloud sessions)

Log in to LinkedIn in your normal browser, open DevTools → Application → Cookies → `https://www.linkedin.com`, and copy the value of `li_at`. Set it as an environment variable (or an environment secret):

```bash
export LINKEDIN_LI_AT='AQEDAR...'
```

When `auth.json` is missing, `scrape` builds it from this cookie. Treat the value like a password: anyone holding it is logged in as you. Logging out of LinkedIn invalidates it.

## 2. Scrape

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
- All CSS selectors live in `SELECTORS` at the top of `linkedin_scraper/scraper.py`. LinkedIn changes its markup every few months; when the scraper starts returning zero posts, that dict is what to update.

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

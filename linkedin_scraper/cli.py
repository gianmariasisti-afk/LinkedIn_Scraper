"""Command line: `login` once, then `scrape` as often as you like."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from .parsing import Post, Target, parse_target, read_targets

DEFAULT_AUTH = "auth.json"


def _since(value: str | None) -> datetime | None:
    """Accept '30d', '2w', or an ISO date like 2025-01-31."""
    if not value:
        return None
    value = value.strip().lower()
    if value[:-1].isdigit() and value[-1] in "dw":
        days = int(value[:-1]) * (7 if value[-1] == "w" else 1)
        return datetime.now(timezone.utc) - timedelta(days=days)
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def write_outputs(posts: list[Post], out_dir: str) -> tuple[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    csv_path = os.path.join(out_dir, f"posts-{stamp}.csv")
    json_path = os.path.join(out_dir, f"posts-{stamp}.json")
    fields = list(Post.__dataclass_fields__)
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:  # BOM so Excel reads accents
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for p in posts:
            writer.writerow(p.to_row())
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump([p.__dict__ for p in posts], fh, ensure_ascii=False, indent=2)
    return csv_path, json_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="linkedin_scraper",
        description="Scrape recent posts from LinkedIn profiles and company pages with your own session.",
    )
    parser.add_argument("--auth", default=DEFAULT_AUTH, help="session file (default: auth.json)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="open a browser, log in by hand, save the session")
    p_login.add_argument("--timeout", type=int, default=300, help="seconds to wait for login")

    p_scrape = sub.add_parser("scrape", help="scrape posts from profiles/companies")
    src = p_scrape.add_mutually_exclusive_group(required=True)
    src.add_argument("-i", "--input", help="text/CSV file with one LinkedIn URL per line")
    src.add_argument("-u", "--url", action="append", help="a profile/company URL (repeatable)")
    p_scrape.add_argument("-n", "--max-posts", type=int, default=20, help="max posts per profile (default 20)")
    p_scrape.add_argument("--since", help="only posts newer than this: 30d, 2w, or 2025-01-31")
    p_scrape.add_argument("-o", "--out", default="output", help="output folder (default: output/)")
    p_scrape.add_argument("--show-browser", action="store_true", help="run with a visible window")
    p_scrape.add_argument(
        "--delay", type=float, nargs=2, default=(8.0, 20.0), metavar=("MIN", "MAX"),
        help="random pause in seconds between profiles (default 8 20)",
    )

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    from playwright.sync_api import sync_playwright

    from . import scraper

    if args.command == "login":
        with sync_playwright() as pw:
            scraper.login(pw, args.auth, timeout_s=args.timeout)
        return 0

    targets: list[Target] = read_targets(args.input) if args.input else [parse_target(u) for u in args.url]
    if not targets:
        parser.error("no LinkedIn URLs found in input")
    since = _since(args.since)

    with sync_playwright() as pw:
        posts = scraper.scrape(
            pw, targets, args.auth,
            max_posts=args.max_posts, since=since,
            headless=not args.show_browser, delay=tuple(args.delay),
        )
    csv_path, json_path = write_outputs(posts, args.out)
    print(f"{len(posts)} posts from {len(targets)} profiles")
    print(f"  {csv_path}\n  {json_path}")
    return 0

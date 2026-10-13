"""Pure helpers: URL normalisation, count parsing, post records. No browser code here."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

_PROFILE_RE = re.compile(r"^/(in|company|school|showcase)/([^/?#]+)", re.IGNORECASE)
_URN_ID_RE = re.compile(r"urn:li:(?:activity|share|ugcPost):(\d+)")
_COUNT_RE = re.compile(r"(\d+(?:[.,]\d+)*)\s*([KkMm])?")


@dataclass(frozen=True)
class Target:
    """A profile or company page to scrape."""

    kind: str  # "in" (person) or "company" / "school" / "showcase"
    slug: str

    @property
    def page_url(self) -> str:
        return f"https://www.linkedin.com/{self.kind}/{self.slug}/"

    @property
    def activity_url(self) -> str:
        if self.kind == "in":
            return f"{self.page_url}recent-activity/all/"
        return f"{self.page_url}posts/?feedView=all"


def parse_target(url: str) -> Target:
    """Turn any LinkedIn profile/company URL (or bare /in/slug path) into a Target."""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://www.linkedin.com/" + url.lstrip("/")
    parsed = urlparse(url)
    if "linkedin.com" not in parsed.netloc:
        raise ValueError(f"Not a LinkedIn URL: {url}")
    m = _PROFILE_RE.match(parsed.path)
    if not m:
        raise ValueError(f"Not a profile or company URL: {url}")
    return Target(kind=m.group(1).lower(), slug=m.group(2))


def read_targets(path: str) -> list[Target]:
    """Read targets from a text file (one URL per line) or a CSV whose first column is the URL."""
    targets: list[Target] = []
    seen: set[Target] = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            first = line.split(",")[0].strip().strip('"')
            if "linkedin.com" not in first and not first.startswith(("/in/", "/company/", "in/", "company/")):
                continue  # header row or junk
            t = parse_target(first)
            if t not in seen:
                seen.add(t)
                targets.append(t)
    return targets


def activity_id(urn: str | None) -> int | None:
    if not urn:
        return None
    m = _URN_ID_RE.search(urn)
    return int(m.group(1)) if m else None


def timestamp_from_id(post_id: int | None) -> datetime | None:
    """LinkedIn activity IDs embed the creation time: the top 41 bits are Unix milliseconds."""
    if not post_id:
        return None
    ms = post_id >> 22
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def parse_count(text: str | None) -> int:
    """'1,234' -> 1234, '1.2K' -> 1200, '12 comments' -> 12, '' -> 0."""
    if not text:
        return 0
    m = _COUNT_RE.search(text)
    if not m:
        return 0
    number, suffix = m.group(1), (m.group(2) or "").upper()
    if suffix:
        value = float(number.replace(",", "."))
        return int(round(value * (1_000 if suffix == "K" else 1_000_000)))
    return int(re.sub(r"[.,]", "", number))


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    text = re.sub(r"\s*…\s*(see more|more)\s*$", "", text, flags=re.IGNORECASE)
    return text.strip()


@dataclass
class Post:
    source: str  # the profile/company URL that was scraped
    post_url: str
    urn: str
    posted_at: str  # ISO 8601 UTC, derived from the URN
    author: str
    author_url: str
    is_repost: bool
    text: str
    reactions: int
    comments: int
    reposts: int
    relative_date: str = ""  # what LinkedIn displayed, e.g. "2d"
    links: list[str] = field(default_factory=list)

    def to_row(self) -> dict:
        row = asdict(self)
        row["links"] = " ".join(self.links)
        return row


def build_post(raw: dict, target: Target) -> Post | None:
    """Convert the raw dict extracted in the page into a Post. Returns None for non-post cards."""
    urn = raw.get("urn") or ""
    pid = activity_id(urn)
    if pid is None:
        return None
    ts = timestamp_from_id(pid)
    header = (raw.get("header") or "").lower()
    author_url = (raw.get("authorUrl") or "").split("?")[0]
    return Post(
        source=target.page_url,
        post_url=f"https://www.linkedin.com/feed/update/urn:li:activity:{pid}/",
        urn=urn,
        posted_at=ts.isoformat() if ts else "",
        author=clean_text(raw.get("author")).split("\n")[0],
        author_url=author_url,
        is_repost="repost" in header,
        text=clean_text(raw.get("text")),
        reactions=parse_count(raw.get("reactions")),
        comments=parse_count(raw.get("comments")),
        reposts=parse_count(raw.get("reposts")),
        relative_date=clean_text(raw.get("date")).split("•")[0].strip(),
        links=[u for u in raw.get("links") or [] if u],
    )

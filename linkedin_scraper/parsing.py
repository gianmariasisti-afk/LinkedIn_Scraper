"""Pure helpers: target URLs and the post record. No browser code here."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse

_PROFILE_RE = re.compile(r"^/(in|company|school|showcase)/([^/?#]+)", re.IGNORECASE)


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


@dataclass
class Post:
    source: str  # the profile/company URL that was scraped
    post_url: str
    urn: str
    posted_at: str  # ISO 8601 UTC, derived from the post ID
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

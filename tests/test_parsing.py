from datetime import datetime, timezone

import pytest

from linkedin_scraper.parsing import (
    build_post, clean_text, parse_count, parse_target, read_targets, timestamp_from_id,
)


@pytest.mark.parametrize("url,kind,slug,activity", [
    ("https://www.linkedin.com/in/jane-doe/", "in", "jane-doe",
     "https://www.linkedin.com/in/jane-doe/recent-activity/all/"),
    ("https://linkedin.com/in/jane-doe?trk=x", "in", "jane-doe",
     "https://www.linkedin.com/in/jane-doe/recent-activity/all/"),
    ("https://www.linkedin.com/company/european-commission/about/", "company", "european-commission",
     "https://www.linkedin.com/company/european-commission/posts/?feedView=all"),
    ("in/jane-doe", "in", "jane-doe", "https://www.linkedin.com/in/jane-doe/recent-activity/all/"),
])
def test_parse_target(url, kind, slug, activity):
    t = parse_target(url)
    assert (t.kind, t.slug, t.activity_url) == (kind, slug, activity)


@pytest.mark.parametrize("bad", ["https://example.com/in/x", "https://www.linkedin.com/feed/"])
def test_parse_target_rejects(bad):
    with pytest.raises(ValueError):
        parse_target(bad)


def test_read_targets_dedupes_and_skips_header(tmp_path):
    f = tmp_path / "list.csv"
    f.write_text("url,name\n# comment\nhttps://www.linkedin.com/in/a/,A\n"
                 "https://www.linkedin.com/in/a/?x=1,A\n\nhttps://www.linkedin.com/company/b,B\n")
    assert [t.slug for t in read_targets(str(f))] == ["a", "b"]


@pytest.mark.parametrize("text,expected", [
    ("1,234", 1234), ("1.234", 1234), ("1.2K", 1200), ("3M", 3_000_000),
    ("56 comments", 56), ("1 repost", 1), ("", 0), (None, 0), ("no number", 0),
])
def test_parse_count(text, expected):
    assert parse_count(text) == expected


def test_timestamp_from_id():
    # Known post ID -> 2024-10-07
    ts = timestamp_from_id(7249000000000000000)
    assert ts.tzinfo == timezone.utc
    assert datetime(2024, 1, 1, tzinfo=timezone.utc) < ts < datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert timestamp_from_id(None) is None


def test_clean_text():
    assert clean_text("Hello  world …see more") == "Hello world"


def test_build_post_skips_non_posts():
    assert build_post({"urn": "urn:li:fsd_profile:ABC"}, parse_target("in/x")) is None

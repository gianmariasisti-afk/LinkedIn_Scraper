import pytest

from linkedin_scraper.parsing import parse_target, read_targets


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

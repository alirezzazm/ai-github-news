from app.collectors.github_trending import parse_trending, to_raw_items
from app.models import KIND_GITHUB_REPO


def test_parse_daily_fixture(fixtures_dir):
    html = (fixtures_dir / "trending_daily.html").read_text(encoding="utf-8")
    rows = parse_trending(html, "daily")
    assert len(rows) == 8
    first = rows[0]
    assert first["full_name"] == "cloudflare/security-audit-skill"
    assert first["url"] == "https://github.com/cloudflare/security-audit-skill"
    assert first["language"] == "JavaScript"
    assert first["stars"] == 42786
    assert first["forks"] == 2669
    assert first["delta"] == 2716
    assert first["rank"] == 1
    assert "security audits" in first["description"]
    assert all(r["full_name"].count("/") == 1 for r in rows)
    assert all(isinstance(r["stars"], int) and r["stars"] > 0 for r in rows)


def test_parse_weekly_language_fixture(fixtures_dir):
    html = (fixtures_dir / "trending_python_weekly.html").read_text(encoding="utf-8")
    rows = parse_trending(html, "weekly")
    assert len(rows) == 15
    assert all(r["period"] == "weekly" for r in rows)
    assert all(r["delta"] is None or r["delta"] >= 0 for r in rows)
    # ranks are sequential
    assert [r["rank"] for r in rows] == list(range(1, 16))


def test_to_raw_items_maps_period_and_flags(fixtures_dir):
    html = (fixtures_dir / "trending_python_weekly.html").read_text(encoding="utf-8")
    raws = to_raw_items(parse_trending(html, "weekly"), "python")
    r = raws[0]
    assert r.kind == KIND_GITHUB_REPO
    assert r.external_id.startswith("gh:") and r.external_id == r.external_id.lower()
    assert "trending_weekly" in r.flags and "trending_lang:python" in r.flags
    assert r.stars_delta_week is not None and r.stars_delta_day is None
    assert r.rank is None  # rank only recorded for the global daily list


def test_parse_garbage_html_is_empty():
    assert parse_trending("<html><body>nothing here</body></html>") == []

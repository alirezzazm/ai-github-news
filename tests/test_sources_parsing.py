from app.collectors.hackernews import listing_to_raw, parse_hn_html, story_to_raw
from app.collectors.huggingface import model_to_raw, paper_to_raw
from app.collectors.linking import extract_repo_full_name
from app.collectors.prescore import compute_prescore, is_ai_related
from app.collectors.rss import parse_feed
from app.models import KIND_HF_MODEL, KIND_HF_PAPER, KIND_RSS, Item

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
<item><title>Hello &amp; welcome</title><link>https://example.com/post?utm_source=x</link>
<description><![CDATA[<p>Body <b>html</b></p>]]></description><pubDate>Fri, 24 Oct 2026 08:00:00 GMT</pubDate><author>me</author></item>
<item><title>Second</title><link>https://example.com/post/</link><description>again</description></item>
<item><title>No link</title></item>
</channel></rss>"""


def test_parse_feed_strips_html_and_normalises_links():
    raws = parse_feed(RSS, "Example", max_items=10)
    assert len(raws) == 2
    assert raws[0].kind == KIND_RSS
    assert raws[0].title == "Hello & welcome"
    assert raws[0].original_text == "Body html"
    assert raws[0].published_at is not None and raws[0].published_at.year == 2026
    # utm parameters and trailing slashes must not create different keys
    a = parse_feed(RSS.replace("https://example.com/post?utm_source=x", "https://example.com/post"), "E")[0]
    assert a.external_id == raws[0].external_id


def test_extract_repo_full_name():
    assert extract_repo_full_name("https://github.com/acme/widget") == "acme/widget"
    assert extract_repo_full_name("https://github.com/acme/widget.git") == "acme/widget"
    assert extract_repo_full_name("https://github.com/acme/widget/releases/tag/v1") == "acme/widget"
    assert extract_repo_full_name("https://github.com/topics/llm") == ""
    assert extract_repo_full_name("https://example.com/github.com/x/y") == ""
    assert extract_repo_full_name("") == ""


def test_hn_story_to_raw_flags_ai():
    raw = story_to_raw({"id": 5, "type": "story", "title": "A new LLM agent framework", "score": 250, "descendants": 30, "time": 1_760_000_000, "by": "pg"})
    assert raw is not None and raw.external_id == "hn:5"
    assert raw.url == "https://news.ycombinator.com/item?id=5"
    assert "ai" in raw.flags and raw.points == 250
    assert story_to_raw({"id": 6, "type": "comment"}) is None


def test_hf_mappers():
    m = model_to_raw({"modelId": "org/model", "likes": 10, "downloads": 1000, "pipeline_tag": "text-generation", "tags": ["transformers", "license:mit"], "createdAt": "2026-10-01T00:00:00.000Z"})
    assert m.kind == KIND_HF_MODEL and m.external_id == "hf:org/model" and "text-generation" in m.topics and "license:mit" not in m.topics
    p = paper_to_raw({"paper": {"id": "2610.1", "title": "T", "summary": "S", "upvotes": 3, "githubRepo": "https://github.com/a/b", "authors": [{"name": "X"}]}})
    assert p.kind == KIND_HF_PAPER and p.repo_full_name == "a/b" and "links_repo" in p.flags


def test_prescore_prefers_growth_and_ai():
    quiet = Item(kind="github_repo", title="dotfiles", original_text="my config", stars=500, flags=[])
    hot = Item(kind="github_repo", title="fast-llm-agent", original_text="LLM agent framework", stars=5000, stars_delta_day=900, flags=["trending_daily", "spike"], rank=1)
    assert compute_prescore(hot) > compute_prescore(quiet) + 30
    assert is_ai_related("Local LLM inference") and not is_ai_related("Bread recipes")
    rel = Item(kind="github_release", title="x v2.0.0", stars=20000, release_tag="v2.0.0")
    pre = Item(kind="github_release", title="x v2.0.0-rc1", stars=20000, release_tag="v2.0.0-rc1")
    assert compute_prescore(rel) > compute_prescore(pre)


def test_parse_hn_html_fixture(fixtures_dir):
    html = (fixtures_dir / "hn_front.html").read_text(encoding="utf-8")
    rows = parse_hn_html(html)
    assert 25 <= len(rows) <= 30
    first = rows[0]
    assert first["id"] == 50219666 and first["points"] == 44 and first["comments"] == 16
    assert first["author"] == "rramadass" and first["url"].startswith("https://www.southampton.ac.uk/")
    assert first["published_at"] is not None and first["published_at"].year == 2026
    second = rows[1]
    assert second["url"] == "https://github.com/obsproject/obs-studio/releases/tag/33.0.0" and second["points"] == 166
    raw = listing_to_raw(second)
    assert raw.external_id == "hn:50218430" and raw.comments_url.endswith("item?id=50218430")
    assert all(r["title"] for r in rows)


def test_hn_transport_fallback(db, monkeypatch):
    from app.collectors import hackernews as hn
    from app.collectors.seed import seed_sources
    from app.models import Source
    from sqlalchemy import select

    seed_sources(db)
    src = db.scalar(select(Source).where(Source.key == "hackernews"))

    def boom(client, *a, **k):
        raise ConnectionError("blocked")

    def fake_html(client, *a, **k):
        return [listing_to_raw({"id": 1, "title": "An LLM story", "url": "https://x.y", "points": 500, "comments": 10, "author": "a", "published_at": None}),
                listing_to_raw({"id": 2, "title": "Low", "url": None, "points": 3, "comments": 0, "author": "b", "published_at": None})]

    monkeypatch.setattr(hn, "TRANSPORTS", (("firebase", boom), ("html", fake_html)))
    res = hn.collect(db, src)
    assert res.created == 1  # the 3-point story is below HN_MIN_POINTS
    db.refresh(src)
    assert src.config.get("last_transport") == "html"

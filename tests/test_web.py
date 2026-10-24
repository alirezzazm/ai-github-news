import pytest
from fastapi.testclient import TestClient

from app.collectors.base import RawItem, ingest
from app.models import ENRICH_DONE, KIND_GITHUB_REPO, KIND_HACKERNEWS, Item


@pytest.fixture()
def client(db):
    from app.main import app

    with TestClient(app) as c:
        yield c


def _seed(db):
    ingest(
        db,
        None,
        [
            RawItem(kind=KIND_GITHUB_REPO, external_id="gh:a/b", url="https://github.com/a/b", title="a/b", original_text="LLM tool", repo_full_name="a/b", language="Python", stars=1200, stars_delta_day=300, flags=["trending_daily"]),
            RawItem(kind=KIND_HACKERNEWS, external_id="hn:9", url="https://example.com/x", title="Something", points=200),
        ],
    )
    db.commit()
    repo = db.query(Item).filter_by(external_id="gh:a/b").one()
    repo.title_fa = "ابزار مدل زبانی"
    repo.summary_fa = "خلاصهٔ فارسی آزمایشی"
    repo.category = "llm"
    repo.tags = ["LLM"]
    repo.importance = 8
    repo.ideas = [{"title": "ایده", "description": "توضیح", "stack": "Python"}]
    repo.enrich_status = ENRICH_DONE
    db.commit()
    return repo


def test_home_lists_items_and_marks_untranslated(client, db):
    _seed(db)
    r = client.get("/")
    assert r.status_code == 200
    assert "ابزار مدل زبانی" in r.text
    assert "ترجمه نشده" in r.text  # the HN item has no summary
    assert 'dir="rtl"' in r.text


def test_filters_and_api(client, db):
    repo = _seed(db)
    r = client.get("/api/items", params={"category": "llm", "period": "all"})
    data = r.json()
    assert data["total"] == 1 and data["items"][0]["id"] == repo.id
    assert data["items"][0]["translated"] is True
    r = client.get(f"/api/items/{repo.id}")
    assert r.json()["ideas"][0]["title"] == "ایده"
    r = client.get("/api/items", params={"ids": f"{repo.id},999999"})
    assert len(r.json()["items"]) == 1
    assert client.get("/api/items/999999").status_code == 404
    r = client.get("/api/items", params={"q": "something", "period": "all"})
    assert r.json()["total"] == 1


def test_item_page_trending_releases_ideas(client, db):
    repo = _seed(db)
    assert client.get(f"/item/{repo.id}").status_code == 200
    assert client.get("/item/424242").status_code == 404
    assert "a/b" in client.get("/trending?period=daily").text
    assert client.get("/releases").status_code == 200
    r = client.get("/ideas")
    assert r.status_code == 200 and "ایده" in r.text
    assert client.get("/bookmarks").status_code == 200
    assert client.get("/healthz").json()["ok"] is True


def test_rss_feed(client, db):
    _seed(db)
    r = client.get("/feed.xml")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/rss+xml")
    assert "<item>" in r.text and "ابزار مدل زبانی" in r.text
    assert "Something" not in r.text  # untranslated items excluded by default
    r = client.get("/feed.xml?translated=0&period=all")
    assert "Something" in r.text


def test_admin_requires_login_and_login_works(client, db):
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 303 and "/admin/login" in r.headers["location"]
    r = client.post("/admin/login", data={"username": "admin", "password": "wrong"})
    assert r.status_code == 401
    r = client.post("/admin/login", data={"username": "admin", "password": "pw"}, follow_redirects=False)
    assert r.status_code == 303
    assert client.get("/admin").status_code == 200
    assert client.get("/admin/sources").status_code == 200
    assert client.get("/admin/settings").status_code == 200
    assert client.get("/admin/usage").status_code == 200
    assert client.get("/admin/logs").status_code == 200
    # queue a job -> command row
    r = client.post("/admin/run/collect_all", follow_redirects=False)
    assert r.status_code == 303
    from app.models import Command

    assert db.query(Command).filter_by(name="collect_all").count() == 1
    # settings override + masking
    r = client.post("/admin/settings", data={"anthropic_api_key": "sk-ant-secret-123456", "llm_batch_size": "6"}, follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/admin/settings").text
    assert "sk-ant-secret-123456" not in page and "sk-a…3456" in page
    from app.settings_store import clear_cache, get_setting

    clear_cache()
    assert get_setting(db, "llm_batch_size") == 6

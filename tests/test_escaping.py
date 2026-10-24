import pytest
from fastapi.testclient import TestClient

from app.collectors.base import RawItem, ingest
from app.models import ENRICH_DONE, KIND_GITHUB_REPO, Item


@pytest.fixture()
def client(db):
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_llm_text_is_escaped(client, db):
    ingest(db, None, [RawItem(kind=KIND_GITHUB_REPO, external_id="gh:e/v", url="https://github.com/e/v", title="e/v", repo_full_name="e/v", stars=10)])
    db.commit()
    it = db.query(Item).one()
    it.summary_fa = "<script>alert(1)</script>"
    it.readme_summary_fa = "خط اول <img src=x onerror=alert(1)>\nخط دوم"
    it.title_fa = "<b>عنوان</b>"
    it.enrich_status = ENRICH_DONE
    db.commit()
    html = client.get(f"/item/{it.id}").text
    assert "<script>alert(1)</script>" not in html
    assert "onerror=alert" not in html
    assert "&lt;script&gt;" in html
    assert "خط اول" in html and "<br>" in html

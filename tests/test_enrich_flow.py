"""End-to-end enrichment with a fake provider (no network, no API key)."""
import json

from sqlalchemy import select

from app.collectors.base import RawItem, ingest
from app.llm import enrich as enrich_mod
from app.llm.base import LLMError, LLMProvider, LLMResponse
from app.models import ENRICH_DONE, ENRICH_FAILED, KIND_GITHUB_REPO, KIND_HACKERNEWS, Item, LlmUsage


class FakeProvider(LLMProvider):
    name = "fake"
    model = "fake-1"

    def __init__(self, fail_first=False):
        self.calls = 0
        self.fail_first = fail_first

    def complete(self, system, user, *, max_tokens, json_schema=None):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise LLMError("boom", retryable=False, provider=self.name)
        payload = json.loads(user.split("\n", 1)[1].rsplit("\n\n", 1)[0])
        items = [
            {
                "id": p["id"],
                "title_fa": f"عنوان {p['id']}",
                "summary_fa": "خلاصهٔ فارسی آزمایشی.",
                "readme_summary_fa": "",
                "category": "agent",
                "tags": ["ایجنت", "LLM"],
                "importance": 9,
                "ideas": [{"title": "ایدهٔ یک", "description": "توضیح", "stack": ".NET"}, {"title": "ایدهٔ دو", "description": "", "stack": "Next.js"}],
            }
            for p in payload
        ]
        return LLMResponse(text="```json\n" + json.dumps({"items": items}, ensure_ascii=False) + "\n```", input_tokens=1200, output_tokens=400, model=self.model, provider=self.name)

    def estimate_cost(self, i, o):
        return 0.001


def _seed(db):
    ingest(
        db,
        None,
        [
            RawItem(kind=KIND_GITHUB_REPO, external_id="gh:x/y", url="https://github.com/x/y", title="x/y", original_text="agent framework", repo_full_name="x/y", stars=3000, stars_delta_day=400, flags=["trending_daily"]),
            RawItem(kind=KIND_HACKERNEWS, external_id="hn:1", url="https://example.com", title="LLM news", points=400, comments_count=100),
            RawItem(kind=KIND_HACKERNEWS, external_id="hn:2", url="https://example.com/2", title="Bread recipes", points=5),
        ],
    )
    db.commit()


def test_run_enrichment_with_fake_provider(db, monkeypatch):
    _seed(db)
    fake = FakeProvider()
    monkeypatch.setattr(enrich_mod, "get_providers", lambda _db: [fake])
    monkeypatch.setattr(enrich_mod, "fetch_details", lambda _db, _items: 0)  # no GitHub calls
    stats = enrich_mod.run_enrichment(db)
    assert stats["selected"] == 3  # every seeded item clears LLM_MIN_PRESCORE (HN floor is 20)
    assert stats["enriched"] == 3 and stats["failed"] == 0 and fake.calls == 1  # one batched request
    done = db.scalars(select(Item).where(Item.enrich_status == ENRICH_DONE)).all()
    assert len(done) == 3
    repo = db.scalar(select(Item).where(Item.external_id == "gh:x/y"))
    assert repo.title_fa.startswith("عنوان") and repo.category == "agent" and repo.importance == 9
    assert len(repo.ideas) == 2 and repo.enrich_model == "fake/fake-1"
    usage = db.scalar(select(LlmUsage))
    assert usage.requests == 1 and usage.items == 3 and usage.input_tokens == 1200 and usage.cost_usd > 0
    # second run: nothing pending above threshold
    assert enrich_mod.run_enrichment(db)["selected"] == 0


def test_provider_failure_marks_items_failed_and_falls_back(db, monkeypatch):
    _seed(db)
    bad = FakeProvider(fail_first=True)
    bad.name = "bad"
    good = FakeProvider()
    monkeypatch.setattr(enrich_mod, "get_providers", lambda _db: [bad, good])
    monkeypatch.setattr(enrich_mod, "fetch_details", lambda _db, _items: 0)
    stats = enrich_mod.run_enrichment(db)
    assert stats["enriched"] == 3 and good.calls == 1  # fell through to the second provider
    errors = db.scalar(select(LlmUsage).where(LlmUsage.provider == "bad"))
    assert errors.errors == 1

    # all providers fail -> items marked failed with the error kept
    db.query(Item).update({"enrich_status": "pending"})
    db.commit()
    monkeypatch.setattr(enrich_mod, "get_providers", lambda _db: [FakeProvider(fail_first=True)])
    stats = enrich_mod.run_enrichment(db, force=True)
    assert stats["enriched"] == 0 and stats["failed"] >= 2 and "boom" in stats["error"]
    assert db.query(Item).filter(Item.enrich_status == ENRICH_FAILED).count() >= 2


def test_no_provider_marks_items_none(db, monkeypatch):
    _seed(db)
    monkeypatch.setattr(enrich_mod, "get_providers", lambda _db: [])
    stats = enrich_mod.run_enrichment(db)
    assert "کلید" in stats["error"]
    assert db.query(Item).filter(Item.enrich_status == "none").count() == 3

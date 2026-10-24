import json

import pytest

from app.llm.enrich import extract_json, normalise_result
from app.llm.prompts import JSON_SCHEMA, SYSTEM_PROMPT, build_user_prompt


def test_extract_json_plain():
    assert extract_json('{"items": []}') == {"items": []}


def test_extract_json_with_code_fence_and_prose():
    text = 'خروجی:\n```json\n{"items": [{"id": 1, "title_fa": "سلام"}],}\n```\nپایان'
    data = extract_json(text)
    assert data["items"][0]["id"] == 1


def test_extract_json_array_form():
    assert extract_json('[{"id": 2}]') == [{"id": 2}]


def test_extract_json_empty_raises():
    with pytest.raises(ValueError):
        extract_json("")
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_normalise_clamps_and_defaults():
    data = {
        "items": [
            {
                "id": "7",
                "title_fa": "عنوان",
                "summary_fa": "خلاصه",
                "category": "weird-cat",
                "importance": 42,
                "tags": ["a", "", "b"],
                "ideas": [{"title": "ایده", "description": "توضیح", "stack": ".NET"}, "ایدهٔ متنی", {"no_title": 1}],
            },
            {"no_id": True},
        ]
    }
    out = normalise_result(data)
    assert list(out) == [7]
    e = out[7]
    assert e["category"] == "other"
    assert e["importance"] == 10
    assert e["tags"] == ["a", "b"]
    assert len(e["ideas"]) == 2 and e["ideas"][1]["title"] == "ایدهٔ متنی"


def test_prompt_and_schema_are_consistent():
    assert "title_fa" in SYSTEM_PROMPT and "ideas" in SYSTEM_PROMPT
    props = JSON_SCHEMA["properties"]["items"]["items"]["properties"]
    for key in ("id", "title_fa", "summary_fa", "category", "tags", "importance", "ideas"):
        assert key in props
    user = build_user_prompt([{"id": 1, "title": "x"}])
    assert json.loads(user.split("\n", 1)[1].rsplit("\n\n", 1)[0])[0]["id"] == 1

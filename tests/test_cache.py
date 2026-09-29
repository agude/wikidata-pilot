"""Exercise cache persistence, ambiguity, API batching, and plan integration."""

import json
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError

from wikidata_pilot.cache import IdCache, case_ids
from wikidata_pilot.cli import main
from wikidata_pilot.models import Candidate, Claim, Qualifier, load_case
from wikidata_pilot.wikidata import WikidataClient
from wikidata_pilot.workflow import export_case, render_plan


def entity(identifier: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "labels": {"en": {"value": "Shared title"}},
        "descriptions": {"en": {"value": "A work"}},
        "aliases": {"en": [{"value": "Alias"}]},
        **({"datatype": "wikibase-item"} if identifier.startswith("P") else {}),
    }


def transport(request: httpx.Request) -> httpx.Response:
    ids = request.url.params["ids"].split("|")
    return httpx.Response(200, json={"entities": {key: entity(key) for key in ids}})


def test_persistence_hits_refresh_and_ambiguity(tmp_path):
    cache = IdCache(tmp_path / "data" / "ids.json")
    requests = []

    def recording(request):
        requests.append(request)
        return transport(request)

    with httpx.Client(transport=httpx.MockTransport(recording)) as http:
        client = WikidataClient(http)
        assert cache.update(["Q2", "Q1", "P50", "Q1"], client) == 3
        original = cache.path.read_bytes()
        assert cache.update(["Q1"], client) == 0
        assert len(requests) == 1
        assert cache.path.read_bytes() == original
        assert cache.update(["Q1"], client, refresh=True) == 1
    loaded = IdCache(cache.path)
    assert list(json.loads(cache.path.read_text())) == ["P50", "Q1", "Q2"]
    assert loaded.entries["P50"].datatype == "wikibase-item"
    assert loaded.entries["Q1"].retrieved == date.today()
    assert loaded.display("Q1") == "Shared title (Q1)"
    assert loaded.display("Q3") == "Q3"
    assert set(loaded.find("SHARED TITLE")) == {"Q1", "Q2", "P50"}
    assert set(loaded.find("alias")) == {"Q1", "Q2", "P50"}
    assert loaded.find("unknown") == {}


def test_batches_and_missing_english(tmp_path):
    sizes = []

    def response(request):
        ids = request.url.params["ids"].split("|")
        sizes.append(len(ids))
        assert request.url.params["languages"] == "en"
        assert "claims" not in request.url.params["props"]
        return httpx.Response(200, json={"entities": {key: {"id": key} for key in ids}})

    cache = IdCache(tmp_path / "ids.json")
    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        assert cache.update([f"Q{i}" for i in range(1, 102)], WikidataClient(http)) == 101
    assert sizes == [50, 50, 1]
    assert cache.display("Q1") == "Q1"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"entities": {}},
        {"entities": {"Q1": {"missing": ""}}},
        {"entities": {"Q1": {"id": "Q2"}}},
        {"error": {"code": "failed"}},
    ],
)
def test_failure_keeps_file_and_memory(tmp_path, payload):
    path = tmp_path / "ids.json"
    path.write_text('{"Q2": {"retrieved": "2026-09-29"}}\n')
    cache = IdCache(path)
    before = path.read_bytes()
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ) as http,
        pytest.raises(ValueError),
    ):
        cache.update(["Q1"], WikidataClient(http))
    assert path.read_bytes() == before
    assert set(cache.entries) == {"Q2"}
    assert list(tmp_path.iterdir()) == [path]


def test_invalid_ids_schema_and_save_failure(tmp_path):
    path = tmp_path / "ids.json"
    path.write_text('{"wrong": {"retrieved": "2026-09-29"}}')
    with pytest.raises(ValueError):
        IdCache(path)
    path.write_text('{"Q1": {"retrieved": "2026-09-29", "claims": []}}')
    with pytest.raises(ValidationError):
        IdCache(path)
    path.unlink()
    cache = IdCache(path)
    with httpx.Client(transport=httpx.MockTransport(transport)) as http:
        client = WikidataClient(http)
        with pytest.raises(ValueError):
            cache.update(["P0"], client)
        with pytest.raises(ValueError):
            client.metadata(["invalid"])
        with (
            patch.object(Path, "replace", side_effect=OSError("disk failure")),
            pytest.raises(OSError),
        ):
            cache.update(["Q1"], client)
    assert not list(tmp_path.iterdir())
    assert not cache.entries


def test_case_cli_and_labeled_plan(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "case.json"
    assert main(["init", str(path)]) == 0
    case = load_case(path)
    assert case_ids(case) == {"Q48997316", "Q135012308", "Q724395", "P1433", "P854", "P813"}
    with httpx.Client(transport=httpx.MockTransport(transport)) as http:
        monkeypatch.setattr("wikidata_pilot.cli.WikidataClient", lambda: WikidataClient(http))
        assert main(["cache", "--case", str(path)]) == 0
        assert main(["cache", "--case", str(path), "--refresh"]) == 0
        assert main(["cache", "Q724395"]) == 0
    assert main(["cache", "--find", "Shared title"]) == 0
    assert "Q724395" in capsys.readouterr().out
    assert main(["cache"]) == 2
    assert main(["cache", "Q1", "--find", "Alias"]) == 2
    assert main(["cache", "--case", str(path), "--file", str(path)]) == 2
    assert main(["plan", str(path)]) == 0
    assert "Shared title (P1433)" in path.with_suffix(".plan.md").read_text()
    cache = IdCache()
    snapshot: dict[str, object] = {
        "field-test": {
            "entities": {
                "Q135012308": {
                    "claims": {
                        "P1433": [{"mainsnak": {"datavalue": {"value": {"id": "Q48997316"}}}}]
                    }
                }
            }
        }
    }
    report = render_plan(case, snapshot, cache)
    assert "Shared title (Q48997316)" in report
    case.sources[0].verification = "verified"
    before = export_case(case)
    render_plan(case, snapshot, cache)
    assert export_case(case) == before
    assert main(["plan", str(path), "--output", "data/wikidata_ids.json"]) == 2


def test_case_collects_and_renders_qualifier_ids(tmp_path):
    path = tmp_path / "case.json"
    assert main(["init", str(path)]) == 0
    case = load_case(path)
    story = case.entities[1]
    story.identifiers = {"P212": "123"}
    story.resolution.candidates = [Candidate(qid="Q2", label="Other work")]
    story.claims.append(
        Claim(
            id="author",
            property="P50",
            datatype="item",
            value="Q724395",
            sources=["abebooks-listing"],
            qualifiers=[
                Qualifier(property="P31", datatype="item", value="Q3"),
                Qualifier(property="P50", datatype="item", value="keith-laumer"),
            ],
        )
    )
    assert {"P212", "Q2", "P50", "P31", "Q3"} <= case_ids(case)
    cache = IdCache(tmp_path / "ids.json")
    with httpx.Client(transport=httpx.MockTransport(transport)) as http:
        cache.update(case_ids(case), WikidataClient(http))
    report = render_plan(case, cache=cache)
    assert "Shared title (P50)=Shared title (Q724395)" in report
    assert "Shared title (P31)=Shared title (Q3)" in report


def test_later_batch_failure_does_not_save_partial_metadata(tmp_path):
    count = 0

    def response(request):
        nonlocal count
        count += 1
        return transport(request) if count == 1 else httpx.Response(503)

    cache = IdCache(tmp_path / "ids.json")
    with (
        httpx.Client(transport=httpx.MockTransport(response)) as http,
        pytest.raises(httpx.HTTPStatusError),
    ):
        cache.update([f"Q{i}" for i in range(1, 52)], WikidataClient(http))
    assert not cache.path.exists()
    assert not cache.entries

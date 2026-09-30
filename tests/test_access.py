"""Read-only API routes, pagination, and compact statement preservation."""

import json
from typing import Any

import httpx
import pytest

from wikidata_pilot import cli
from wikidata_pilot.cache import IdCache
from wikidata_pilot.inspection import summarize_entity
from wikidata_pilot.wikidata import WikidataClient


def snak(value: Any, datatype: str = "wikibase-item") -> dict[str, Any]:
    return {"snaktype": "value", "datatype": datatype, "datavalue": {"value": value}}


def payload() -> dict[str, Any]:
    return {
        "entities": {
            "Q1": {
                "id": "Q1",
                "lastrevid": 123,
                "labels": {"en": {"value": "Story"}, "fr": {"value": "Histoire"}},
                "aliases": {"en": [{"value": "Alternate"}]},
                "claims": {
                    "P50": [
                        {
                            "id": "Q1$author",
                            "rank": "deprecated",
                            "mainsnak": snak({"id": "Q2", "numeric-id": 2}),
                            "qualifiers": {"P1545": [snak("2", "string")]},
                            "references": [
                                {"snaks": {"P854": [snak("https://example.org", "url")]}}
                            ],
                        }
                    ],
                    "P577": [
                        {
                            "rank": "normal",
                            "mainsnak": snak(
                                {
                                    "time": "+1969-01-01T00:00:00Z",
                                    "precision": 9,
                                    "calendarmodel": "http://www.wikidata.org/entity/Q1985786",
                                },
                                "time",
                            ),
                        }
                    ],
                    "P123": [
                        {"mainsnak": {"snaktype": "somevalue"}},
                        {"mainsnak": {"snaktype": "novalue"}},
                    ],
                },
            }
        }
    }


def test_compact_inspection_keeps_meaning_and_selected_absence(tmp_path):
    cache_path = tmp_path / "ids.json"
    cache_path.write_text('{"Q2":{"label":"Writer","retrieved":"2026-09-29"}}')
    cache = IdCache(cache_path)
    full = payload()
    before = json.dumps(full)
    summary = summarize_entity(full, cache)
    author = summary["claims"]["P50"]["statements"][0]
    assert author["rank"] == "deprecated"
    assert author["id"] == "Q1$author"
    assert author["value"] == {"id": "Q2", "label": "Writer"}
    assert author["qualifiers"]["P1545"][0]["value"] == "2"
    assert author["references"][0]["P854"][0]["value"] == "https://example.org"
    date = summary["claims"]["P577"]["statements"][0]["value"]
    assert date["precision"] == 9 and date["calendarmodel"].endswith("Q1985786")
    assert summary["claims"]["P123"]["statements"] == [
        {"snaktype": "somevalue"},
        {"snaktype": "novalue"},
    ]
    assert summary["aliases"] == ["Alternate"]
    selected = summarize_entity(full, cache, ["P50", "P31"])
    assert set(selected["claims"]) == {"P50", "P31"}
    assert selected["claims"]["P31"]["statements"] == []
    assert json.dumps(full) == before


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {"entities": []},
        {"entities": {"Q1": {}, "Q2": {}}},
        {"entities": {"Q1": {"missing": ""}}},
        {"entities": {"Q1": {"claims": []}}},
        {"entities": {"Q1": {"claims": {"P31": {}}}}},
        {"entities": {"Q1": {"claims": {"P31": [{}]}}}},
        {"entities": {"Q1": {"claims": {"P31": [{"mainsnak": {}}]}}}},
    ],
)
def test_malformed_records_are_not_empty_claims(tmp_path, invalid):
    with pytest.raises(ValueError):
        summarize_entity(invalid, IdCache(tmp_path / "ids.json"))


def test_search_type_continuation_and_invalid_parameters():
    requests = []

    def response(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "search": [{"id": "P123", "label": "publisher", "url": "discard"}],
                "search-continue": 2,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        client = WikidataClient(http)
        page = client.search_page("publisher", entity_type="property", limit=2)
        assert page == {"results": [{"id": "P123", "label": "publisher"}], "next_offset": 2}
        assert requests[0].url.params["type"] == "property"
        invalid_options: list[dict[str, Any]] = [
            {"limit": 0},
            {"limit": 51},
            {"offset": -1},
            {"entity_type": "invalid"},
        ]
        for options in invalid_options:
            with pytest.raises(ValueError):
                client.search_page("name", **options)
        with pytest.raises(ValueError):
            client.search_page(" ")


def test_linked_uses_property_query_and_has_more():
    def response(request):
        query = request.url.params["query"]
        assert "wdt:P1433 wd:Q1" in query
        assert "ORDER BY ?item LIMIT 3 OFFSET 2" in query
        return httpx.Response(
            200,
            json={
                "results": {
                    "bindings": [
                        {
                            "item": {"value": f"http://www.wikidata.org/entity/Q{i}"},
                            "itemLabel": {"value": f"Story {i}"},
                        }
                        for i in range(3, 6)
                    ]
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        client = WikidataClient(http)
        page = client.linked("Q1", "P1433", limit=2, offset=2)
        assert [item["id"] for item in page["results"]] == ["Q3", "Q4"]
        assert page["next_offset"] == 4
        with pytest.raises(ValueError):
            client.linked("Q1 } LIMIT 0", "P50")
        with pytest.raises(ValueError):
            client.linked("Q1", "P50. ?s ?p ?o")


def test_backlink_cursor_and_complete_empty_page():
    requests = []

    def response(request):
        requests.append(request)
        if "blcontinue" in request.url.params:
            assert request.url.params["blcontinue"] == "0|123"
            return httpx.Response(200, json={"query": {"backlinks": []}})
        return httpx.Response(
            200,
            json={
                "query": {"backlinks": [{"title": "Q2", "ns": 0}]},
                "continue": {"continue": "-||", "blcontinue": "0|123"},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        client = WikidataClient(http)
        first = client.backlinks("Q1", limit=1)
        assert first == {"results": [{"id": "Q2"}], "next_cursor": "0|123"}
        assert requests[0].url.params["blnamespace"] == "0"
        second = client.backlinks("Q1", cursor=first["next_cursor"])
        assert second == {"results": [], "next_cursor": None}
        with pytest.raises(ValueError):
            client.backlinks("P50")


def test_guidance_sections_and_selected_wikitext():
    def response(request):
        assert request.url.params["action"] == "parse"
        if "section" in request.url.params:
            assert request.url.params["prop"] == "wikitext|revid"
            return httpx.Response(
                200,
                json={
                    "parse": {
                        "title": "Wikidata:Books",
                        "revid": 7,
                        "wikitext": "== Edition ==\nPublisher belongs here.",
                    }
                },
            )
        assert request.url.params["prop"] == "tocdata|revid"
        return httpx.Response(
            200,
            json={
                "parse": {
                    "title": "Wikidata:Books",
                    "tocdata": {
                        "sections": [
                            {"index": "3", "line": "Edition", "fromTitle": "Wikidata:Books"}
                        ]
                    },
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        client = WikidataClient(http)
        assert client.page("Wikidata:Books")["sections"][0]["index"] == "3"
        assert client.page("Wikidata:Books", section=3)["revision"] == 7
        for title in ["", "Q1", "P123", "Special:WhatLinksHere/Q1"]:
            with pytest.raises(ValueError):
                client.page(title)
        with pytest.raises(ValueError):
            client.page("Wikidata:Books", section=-1)


@pytest.mark.parametrize(
    "method,response",
    [
        ("search", {}),
        ("search", {"search": [None]}),
        ("search", {"search": [], "search-continue": 0}),
        ("linked", {"results": {"bindings": None}}),
        ("linked", {}),
        ("linked", {"results": {"bindings": [{}]}}),
        ("backlinks", {}),
        ("backlinks", {"query": {"backlinks": [None]}}),
        ("backlinks", {"query": {"backlinks": []}, "continue": []}),
        ("backlinks", {"query": {"backlinks": []}, "continue": {"blcontinue": 1}}),
        ("page", {}),
        ("page", {"parse": {"tocdata": {}}}),
        ("text", {"parse": {"wikitext": None}}),
    ],
)
def test_remote_malformed_payloads_fail(method, response):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))
    ) as http:
        client = WikidataClient(http)
        with pytest.raises(ValueError):
            if method == "search":
                client.search_page("name")
            elif method == "linked":
                client.linked("Q1", "P50")
            elif method == "backlinks":
                client.backlinks("Q1")
            else:
                client.page("Wikidata:Books", section=0 if method == "text" else None)


def test_api_cli_routes_and_compact_raw_views(tmp_path, monkeypatch, capsys):
    def response(request):
        params = request.url.params
        if params.get("action") == "wbgetentities":
            return httpx.Response(200, json=payload())
        if params.get("action") == "wbsearchentities":
            return httpx.Response(200, json={"search": []})
        if params.get("list") == "backlinks":
            return httpx.Response(200, json={"query": {"backlinks": []}})
        if params.get("action") == "parse":
            return httpx.Response(200, json={"parse": {"tocdata": {"sections": []}}})
        return httpx.Response(200, json={"results": {"bindings": []}})

    monkeypatch.chdir(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        monkeypatch.setattr(cli, "WikidataClient", lambda: WikidataClient(http))
        assert cli.main(["inspect", "Q1", "--property", "P50"]) == 0
        assert set(json.loads(capsys.readouterr().out)["claims"]) == {"P50"}
        assert cli.main(["inspect", "Q1", "--raw"]) == 0
        assert "entities" in json.loads(capsys.readouterr().out)
        assert cli.main(["inspect", "Q1", "--property", "Q2"]) == 2
        assert cli.main(["inspect", "Q1", "--raw", "--property", "P50"]) == 2
        assert cli.main(["search", "author"]) == 0
        assert cli.main(["linked", "Q1", "--property", "P50"]) == 0
        assert cli.main(["backlinks", "Q1"]) == 0
        assert cli.main(["page", "Wikidata:Books"]) == 0
    assert not list(tmp_path.iterdir())


def test_property_inspection_uses_english_and_retains_datatype(tmp_path):
    def response(request):
        assert request.url.params["ids"] == "P123"
        assert request.url.params["languages"] == "en"
        return httpx.Response(
            200, json={"entities": {"P123": {"id": "P123", "datatype": "wikibase-item"}}}
        )

    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        entity = WikidataClient(http).inspect("P123")
    assert summarize_entity(entity, IdCache(tmp_path / "ids.json"))["datatype"] == "wikibase-item"

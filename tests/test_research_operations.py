"""Research lookups, batch inspection, and revision continuation."""

import json

import httpx
import pytest

from wikidata_pilot import cli
from wikidata_pilot.wikidata import WikidataClient


def test_batch_inspection_fetches_once_and_rejects_missing_records():
    requests = []

    def response(request):
        requests.append(request)
        assert request.url.params["ids"] == "Q1|P50"
        return httpx.Response(200, json={"entities": {"Q1": {"id": "Q1"}, "P50": {"id": "P50"}}})

    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        client = WikidataClient(http)
        entities = client.inspect_many(["Q1", "P50", "Q1"])["entities"]
        assert isinstance(entities, dict) and len(entities) == 2
        assert len(requests) == 1
        for ids in [[], ["Q0"], ["Q1"] * 51]:
            with pytest.raises(ValueError):
                client.inspect_many(ids)
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"entities": {"Q1": {"id": "Q1"}}})
            )
        ) as http,
        pytest.raises(ValueError, match="missing"),
    ):
        WikidataClient(http).inspect_many(["Q1", "Q2"])


def test_identifier_escaping_and_hierarchy_pagination():
    queries = []

    def response(request):
        query = request.url.params["query"]
        queries.append(query)
        return httpx.Response(
            200,
            json={
                "results": {
                    "bindings": [
                        {"item": {"value": "http://www.wikidata.org/entity/Q2"}},
                        {"item": {"value": "http://www.wikidata.org/entity/Q3"}},
                    ]
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        client = WikidataClient(http)
        page = client.identifier("P212", 'value"\n\\', limit=1, offset=4)
        assert page["next_offset"] == 5
        assert 'wdt:P212 "value\\"\\n\\\\"' in queries[-1]
        assert "LIMIT 2 OFFSET 4" in queries[-1]
        client.ancestors("Q1")
        assert "wd:Q1 wdt:P279+ ?item" in queries[-1]
        assert "FILTER(?item != wd:Q1)" in queries[-1]
        client.ancestors("Q1", instance_of=True)
        assert "wd:Q1 wdt:P31/wdt:P279* ?item" in queries[-1]
        assert client.search_identifier("P212", "123")[0]["id"] == "Q2"
        for pid, value in [("P0", "123"), ("P212", " "), ("P212 }", "123")]:
            with pytest.raises(ValueError):
                client.identifier(pid, value)
        with pytest.raises(ValueError):
            client.ancestors("Q1 }")


def test_sitelink_resolution_preserves_canonical_title_and_absence():
    def response(request):
        params = request.url.params
        assert params["sites"] == "enwiki"
        assert params["redirects"] == "yes"
        if params["titles"] == "Missing":
            return httpx.Response(200, json={"entities": {"-1": {"missing": ""}}})
        return httpx.Response(
            200,
            json={
                "entities": {
                    "Q1": {
                        "id": "Q1",
                        "labels": {"en": {"value": "Name"}},
                        "sitelinks": {"enwiki": {"title": "Canonical title"}},
                    }
                },
                "redirects": [{"from": "Old title", "to": "Canonical title"}],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        client = WikidataClient(http)
        result = client.resolve("enwiki", "Old title")
        assert result["id"] == "Q1"
        assert result["title"] == "Canonical title"
        assert result["requested_title"] == "Old title"
        assert result["redirects"][0]["from"] == "Old title"
        assert client.resolve("enwiki", "Missing")["id"] is None
        for site, title in [("enwiki", ""), ("enwiki", "One|Two"), ("enwiki|frwiki", "One")]:
            with pytest.raises(ValueError):
                client.resolve(site, title)


def test_history_property_namespace_hidden_fields_and_continuation():
    def response(request):
        params = request.url.params
        assert params["titles"] == "Property:P50"
        assert "content" not in params["rvprop"]
        if "rvcontinue" in params:
            assert params["rvcontinue"] == "20260929000000|2"
            return httpx.Response(200, json={"query": {"pages": [{"revisions": []}]}})
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "revisions": [
                                {
                                    "revid": 3,
                                    "parentid": 2,
                                    "timestamp": "2026-09-29T00:00:00Z",
                                    "userhidden": True,
                                    "commenthidden": True,
                                }
                            ]
                        }
                    ]
                },
                "continue": {"rvcontinue": "20260929000000|2", "continue": "||"},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        client = WikidataClient(http)
        first = client.history("P50", limit=1)
        assert first["revisions"][0]["userhidden"] is True
        assert client.history("P50", cursor=first["next_cursor"])["next_cursor"] is None
        with pytest.raises(ValueError):
            client.history("Q0")


@pytest.mark.parametrize(
    "method,payload",
    [
        ("resolve", {}),
        ("resolve", {"entities": {}}),
        ("resolve", {"entities": {"Q1": None}}),
        ("resolve", {"entities": {"Q1": {}}}),
        ("history", {}),
        ("history", {"query": {"pages": []}}),
        ("history", {"query": {"pages": [{"missing": True}]}}),
        ("history", {"query": {"pages": [{"revisions": [None]}]}}),
        ("history", {"query": {"pages": [{"revisions": []}]}, "continue": {"rvcontinue": 1}}),
    ],
)
def test_malformed_responses_fail(method, payload):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        client = WikidataClient(http)
        with pytest.raises(ValueError):
            if method == "resolve":
                client.resolve("enwiki", "Title")
            else:
                client.history("Q1")


def test_cli_operations_and_help_references(tmp_path, monkeypatch, capsys):
    def response(request):
        params = request.url.params
        if params.get("action") == "wbgetentities":
            return httpx.Response(
                200,
                json={"entities": {key: {"id": key} for key in params.get("ids", "Q1").split("|")}},
            )
        if params.get("prop") == "revisions":
            return httpx.Response(200, json={"query": {"pages": [{"revisions": []}]}})
        return httpx.Response(200, json={"results": {"bindings": []}})

    monkeypatch.chdir(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(response)) as http:
        monkeypatch.setattr(cli, "WikidataClient", lambda: WikidataClient(http))
        assert cli.main(["inspect", "Q1", "P50", "--property", "P31"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert [entity["id"] for entity in result["entities"]] == ["Q1", "P50"]
        assert cli.main(["inspect", "Q1", "P50", "--raw"]) == 0
        assert set(json.loads(capsys.readouterr().out)["entities"]) == {"Q1", "P50"}
        for arguments in [
            ["identifier", "P212", "123"],
            ["ancestors", "Q1", "--instance-of"],
            ["resolve", "enwiki", "Title"],
            ["history", "Q1"],
        ]:
            assert cli.main(arguments) == 0
        assert not list(tmp_path.iterdir())
    root = cli.parser()
    assert "docs/commands.md" in root.format_help()
    for name in ["init", "inspect", "identifier", "ancestors", "resolve", "history", "prepare"]:
        with pytest.raises(SystemExit) as error:
            root.parse_args([name, "--help"])
        assert error.value.code == 0
        assert f"docs/commands.md#{name}" in capsys.readouterr().out

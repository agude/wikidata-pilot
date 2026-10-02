"""Exact identifier verification and Action API pagination edges."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from wikidata_pilot.wikidata import WikidataClient


def _statement(rank: str, snaktype: str, value: str | None = None) -> dict[str, Any]:
    mainsnak: dict[str, Any] = {"snaktype": snaktype}
    if value is not None:
        mainsnak["datavalue"] = {"value": value}
    return {"rank": rank, "mainsnak": mainsnak}


def test_identifier_matches_only_exact_values_at_selected_ranks(tmp_path):
    requested = "AbC-123"
    claims: dict[str, list[dict[str, Any]]] = {
        "Q1": [_statement("deprecated", "value", requested)],
        "Q2": [
            _statement("normal", "value", "other"),
            _statement("preferred", "value", requested),
        ],
        "Q3": [
            _statement("normal", "value", requested),
            _statement("deprecated", "value", "other"),
        ],
        "Q4": [_statement("normal", "somevalue")],
        "Q5": [_statement("normal", "novalue")],
        "Q6": [
            _statement("preferred", "value", "other"),
            _statement("normal", "value", requested),
        ],
        "Q7": [_statement("normal", "value", requested.lower())],
    }

    def respond(request):
        params = request.url.params
        if params.get("list") == "search":
            return httpx.Response(
                200,
                json={"query": {"search": [{"title": qid} for qid in claims]}},
            )
        assert params.get("action") == "wbgetentities"
        return httpx.Response(
            200,
            json={
                "entities": {
                    qid: {"id": qid, "claims": {"P213": statements}}
                    for qid, statements in claims.items()
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        result = WikidataClient(http, state_dir=tmp_path / "state").identifier("P213", requested)

    assert [row["id"] for row in result["results"]] == ["Q2", "Q3"]
    assert result["next_offset"] is None


def test_identifier_paginates_past_indexed_hits_that_fail_verification(tmp_path):
    requests = []

    def respond(request):
        params = request.url.params
        if params.get("list") == "search":
            requests.append((params["sroffset"], params["srlimit"]))
            if params["sroffset"] == "0":
                return httpx.Response(
                    200,
                    json={
                        "query": {"search": [{"title": "Q1"}]},
                        "continue": {"sroffset": 1, "continue": "-||"},
                    },
                )
            return httpx.Response(200, json={"query": {"search": [{"title": "Q2"}]}})
        qid = params["ids"]
        value = "wrong" if qid == "Q1" else "target"
        return httpx.Response(
            200,
            json={
                "entities": {
                    qid: {
                        "id": qid,
                        "claims": {"P213": [_statement("normal", "value", value)]},
                    }
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        client = WikidataClient(http, state_dir=tmp_path / "state")
        first = client.identifier("P213", "target", limit=1)
        assert first == {"results": [], "next_offset": 1}
        second = client.identifier("P213", "target", limit=1, offset=first["next_offset"])

    assert requests == [("0", "1"), ("1", "1")]
    assert [row["id"] for row in second["results"]] == ["Q2"]
    assert second["next_offset"] is None


def test_identifier_rejects_malformed_continuation_without_caching(tmp_path):
    calls = 0

    def respond(request):
        nonlocal calls
        calls += 1
        if request.url.params.get("list") == "search":
            continuation = {"sroffset": "bad", "continue": "-||"} if calls == 1 else {}
            return httpx.Response(
                200,
                json={
                    "query": {"search": [{"title": "Q1"}]},
                    "continue": continuation,
                },
            )
        return httpx.Response(
            200,
            json={
                "entities": {
                    "Q1": {
                        "id": "Q1",
                        "claims": {"P213": [_statement("normal", "value", "target")]},
                    }
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        client = WikidataClient(http, state_dir=tmp_path / "state")
        with pytest.raises(ValueError, match="offset is malformed"):
            client.identifier("P213", "target")
        assert [row["id"] for row in client.identifier("P213", "target")["results"]] == ["Q1"]

    assert calls == 4

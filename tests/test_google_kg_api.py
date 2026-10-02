"""Google API candidates keep evidence without exposing credentials."""

import json
from unittest.mock import MagicMock

import httpx
import pytest

from tests.test_google_kg import record
from wikidata_pilot import google_kg
from wikidata_pilot.google_kg import (
    Capture,
    ScrapeOptions,
    api_fetcher,
    collect_reports,
    extract_api_candidates,
    utc_now,
)


def payload():
    return {
        "itemListElement": [
            {
                "result": {
                    "@id": "kg:/g/123",
                    "name": "Book",
                    "description": "A novel",
                    "@type": ["Book"],
                    "url": "https://example.org",
                    "detailedDescription": {
                        "articleBody": "By Writer",
                        "url": "https://example.org/book",
                    },
                },
                "resultScore": 42,
            },
            {"result": {"@id": "kg:/m/456", "name": "Other"}},
            {"result": {"@id": "kg:/g/123", "name": "Book"}},
        ]
    }


def test_api_normalizes_and_deduplicates_without_accepting_matches():
    candidates = extract_api_candidates(payload())
    assert [c["id"] for c in candidates] == ["/g/123", "/m/456"]
    assert [c["property"] for c in candidates] == ["P2671", "P646"]
    first = candidates[0]
    assert first["result_score"] == 42
    assert first["types"] == ["Book"]
    assert first["detailed_description"]["articleBody"] == "By Writer"
    assert len(first["occurrences"]) == 2
    assert first["occurrences"][0]["locator"] == "$.itemListElement[0].result"
    assert extract_api_candidates({"itemListElement": []}) == []


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"itemListElement": {}},
        {"error": {}},
        {"itemListElement": [None]},
        {"itemListElement": [{"result": {}}]},
        {"itemListElement": [{"result": {"@id": "c-cloud"}}]},
    ],
)
def test_malformed_results_are_not_empty_results(data):
    with pytest.raises(ValueError):
        extract_api_candidates(data)


def test_api_sends_key_in_header_and_redacts_echoes(tmp_path, monkeypatch):
    key = "test-key-keep-private"
    monkeypatch.setenv("GOOGLE_KG_API_KEY", key)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["X-Goog-Api-Key"] == key
        assert key not in str(request.url)
        data = payload()
        data["itemListElement"][0]["result"]["description"] = key
        return httpx.Response(200, json=data)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    def make_client(**kwargs):
        client.headers.update(kwargs["headers"])
        return client

    monkeypatch.setattr(httpx, "Client", make_client)
    options = ScrapeOptions(tmp_path, backend="api")
    with api_fetcher(options, None) as fetch:
        capture = fetch(google_kg.GOOGLE_API + "?query=Book")
        assert key not in json.dumps(capture.payload)
        assert "[REDACTED]" in json.dumps(capture.payload)
    assert len(calls) == 1
    source = record()
    source["request_url"] = capture.url
    report = collect_reports([source], options, MagicMock(return_value=capture))
    evidence = report["items"][0]["evidence"]
    assert "json" in evidence and "html" not in evidence
    assert key not in (tmp_path / "report.json").read_text()
    assert all(key not in p.read_text() for p in (tmp_path / "raw").glob("*.json"))


def test_api_cache_is_separate_from_browser_and_reuses_results(tmp_path):
    source = record()
    source["request_url"] = google_kg.GOOGLE_API + "?query=Example&limit=5"
    captured = Capture(source["request_url"], utc_now(), "", 200, payload())
    options = ScrapeOptions(tmp_path, backend="api")
    collect_reports([source], options, MagicMock(return_value=captured))
    fetch = MagicMock()
    next_source = record()
    next_source["request_url"] = captured.url
    report = collect_reports([next_source], options, fetch)
    fetch.assert_not_called()
    assert report["items"][0]["status"] == "candidates"
    changed = record()
    changed["request_url"] = google_kg.GOOGLE_API + "?query=Example&limit=10"
    fetch.return_value = Capture(changed["request_url"], utc_now(), "", 200, payload())
    collect_reports([changed], options, fetch)
    fetch.assert_called_once()


def test_remote_errors_stop_batch_and_preserve_response(tmp_path):
    fetch = MagicMock(
        return_value=Capture(
            google_kg.GOOGLE_API, utc_now(), "", 403, {"error": {"status": "PERMISSION_DENIED"}}
        )
    )
    report = collect_reports(
        [record(), record("Q2")], ScrapeOptions(tmp_path, backend="api"), fetch
    )
    fetch.assert_called_once()
    assert [i["status"] for i in report["items"]] == ["blocked", "not_attempted"]
    assert "HTTP 403" in report["items"][0]["error"]


@pytest.mark.parametrize("response", ["bad json", "[]", "timeout"])
def test_transport_failures_do_not_expose_exception_details(tmp_path, monkeypatch, response):
    key = "private-test-key"
    monkeypatch.setenv("GOOGLE_KG_API_KEY", key)

    def handler(request):
        if response == "timeout":
            raise httpx.ReadTimeout(key, request=request)
        return httpx.Response(200, text=response)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
    with (
        api_fetcher(ScrapeOptions(tmp_path, backend="api"), None) as fetch,
        pytest.raises(ValueError) as error,
    ):
        fetch(google_kg.GOOGLE_API)
    assert key not in str(error.value)


def test_missing_key_and_incompatible_options_fail_before_wikidata(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_KG_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GOOGLE_KG_API_KEY"):
        google_kg.scrape_google_kg(["Q1"], {}, ScrapeOptions(tmp_path, backend="api"))
    with api_fetcher(ScrapeOptions(tmp_path), MagicMock()) as fetch:
        assert callable(fetch)
    for options in (
        ScrapeOptions(tmp_path, backend="api", headed=True),
        ScrapeOptions(tmp_path, backend="api", saved_pages=tmp_path),
        ScrapeOptions(tmp_path, limit=21),
    ):
        with pytest.raises(ValueError):
            google_kg.scrape_google_kg(["Q1"], {}, options)

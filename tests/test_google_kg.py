"""Scraping preserves evidence and stops when Google restricts access."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wikidata_pilot import cli, google_kg
from wikidata_pilot.google_kg import (
    Capture,
    ScrapeOptions,
    block_reason,
    browser_fetcher,
    collect_reports,
    extract_candidates,
    search_url,
    select_qids,
    utc_now,
)


def record(qid="Q1", label="Example"):
    return {
        "id": qid,
        "label": label,
        "description": "a book",
        "query": label,
        "search_url": search_url(label),
        "status": "not_attempted",
        "candidates": [],
        "claims": {pid: {"statements": []} for pid in google_kg.CONTEXT_PROPERTIES},
    }


def capture(html='<div data-kpid="vise:/g/123">Example</div>', status=200):
    return Capture(search_url("Example"), utc_now(), html, status)


def test_extracts_only_explicit_ids_with_context_and_deduplication():
    html = """<div data-kpid="vise:/g/123">Title</div>
<a href="/search?kgmid=%2Fg%2F123&amp;hl=en">Title again</a>
<a href="https://g.co/kg/m/456">Legacy</a>
<div data-entityid="/g/789">Other entity</div>
<a href="https://evil.example/search?kgmid=/g/bad">Ignore</a>
<script>let unrelated = "/g/unrelated";</script>
<div data-kpid="/g/bad trailing text">Ignore</div>"""
    candidates = extract_candidates(html)
    assert [c["id"] for c in candidates] == ["/g/123", "/m/456", "/g/789"]
    assert len(candidates[0]["occurrences"]) == 2
    assert "line 1, column 0" in candidates[0]["occurrences"][0]["locator"]
    assert "Title" in candidates[0]["occurrences"][0]["excerpt"]
    assert candidates[1]["property"] == "P646"
    assert extract_candidates("<div data-kpid></div>") == []


@pytest.mark.parametrize(
    "html,url,status,reason",
    [
        ("", search_url("x"), 429, "HTTP 429"),
        ("Before you continue to Google", search_url("x"), 200, "consent"),
        ("", "https://consent.google.com/m", 200, "consent"),
        ("Our systems have detected unusual traffic", search_url("x"), 200, "CAPTCHA"),
        ("", "https://www.google.com/sorry/index", 200, "CAPTCHA"),
        ("Please enable JavaScript", search_url("x"), 200, "JavaScript"),
    ],
)
def test_blocks_are_distinct_from_empty_results(html, url, status, reason):
    assert reason in (block_reason(Capture(url, utc_now(), html, status)) or "")
    assert block_reason(capture("<html>Ordinary search results</html>")) is None


def test_stops_after_block_and_saves_page_and_partial_report(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return capture("Our systems have detected unusual traffic")

    report = collect_reports([record(), record("Q2")], ScrapeOptions(tmp_path), fetch)
    assert len(calls) == 1
    assert [i["status"] for i in report["items"]] == ["blocked", "not_attempted"]
    evidence = report["items"][0]["evidence"]
    assert Path(evidence["html"]).read_text() == "Our systems have detected unusual traffic"
    assert json.loads((tmp_path / "report.json").read_text()) == report
    assert "blocked" in (tmp_path / "report.md").read_text()


def test_pacing_reuse_and_fresh_preserve_capture_history(tmp_path):
    fetch = MagicMock(return_value=capture())
    sleep = MagicMock()
    options = ScrapeOptions(tmp_path)
    first = collect_reports([record(), record("Q2")], options, fetch, sleep)
    assert fetch.call_count == 2
    sleep.assert_called_once_with(10)
    assert all(i["status"] == "candidates" for i in first["items"])
    fetch.reset_mock()
    reused = collect_reports([record()], options, fetch)
    fetch.assert_not_called()
    assert reused["items"][0]["evidence"]["retrieved"] == first["items"][0]["evidence"]["retrieved"]
    collect_reports([record()], ScrapeOptions(tmp_path, fresh=True), fetch)
    fetch.assert_called_once()
    assert len(list((tmp_path / "raw").glob("Q1-*.html"))) == 3


def test_empty_failure_and_existing_identifiers(tmp_path):
    existing = record("Q2")
    existing["claims"]["P2671"]["statements"] = [{"value": "/g/old", "rank": "normal"}]
    unusual = record("Q3")
    unusual["claims"]["P2671"]["statements"] = [{"snaktype": "novalue"}]
    legacy = record("Q4")
    legacy["claims"]["P646"]["statements"] = [{"value": "/m/456"}]
    fetch = MagicMock(
        side_effect=[capture("nothing here"), capture('<a href="/search?kgmid=/m/456">Legacy</a>')]
    )
    report = collect_reports(
        [record(), existing, unusual, legacy, record("Q5", "")],
        ScrapeOptions(tmp_path),
        fetch,
        lambda _: None,
    )
    assert [i["status"] for i in report["items"]] == [
        "no_candidates",
        "already_present",
        "identifier_review",
        "candidates",
        "missing_label",
    ]
    assert report["items"][3]["candidates"][0]["already_present"] is True
    assert "Existing P646" in (tmp_path / "report.md").read_text()
    failed = collect_reports(
        [record()], ScrapeOptions(tmp_path, fresh=True), MagicMock(side_effect=ValueError("failed"))
    )
    assert failed["items"][0]["status"] == "failed"


def test_saved_pages_require_provenance_and_never_fetch_google(tmp_path):
    saved = tmp_path / "saved"
    saved.mkdir()
    (saved / "Q1.html").write_text('<div data-kpid="/g/123">Title</div>')
    (saved / "Q1.json").write_text(
        json.dumps({"url": search_url("Example"), "retrieved": "2026-10-01"})
    )
    fetch = MagicMock()
    options = ScrapeOptions(tmp_path / "reports", saved_pages=saved)
    report = collect_reports([record(), record("Q2")], options, fetch)
    fetch.assert_not_called()
    assert report["items"][0]["status"] == "candidates"
    assert report["items"][1]["status"] == "failed"
    (saved / "Q1.json").write_text('{"url":"https://example.org","retrieved":"2026-10-01"}')
    report = collect_reports([record()], options, fetch)
    assert "Google source URL" in report["items"][0]["error"]


def test_cache_expiry_and_query_change(tmp_path):
    fetch = MagicMock(return_value=capture())
    collect_reports([record()], ScrapeOptions(tmp_path), fetch)
    metadata = next((tmp_path / "raw").glob("*.json"))
    data = json.loads(metadata.read_text())
    data["retrieved"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    metadata.write_text(json.dumps(data))
    fetch.reset_mock()
    collect_reports([record()], ScrapeOptions(tmp_path), fetch)
    fetch.assert_called_once()
    fetch.reset_mock()
    collect_reports([record(label="Different")], ScrapeOptions(tmp_path), fetch)
    fetch.assert_called_once()


def test_qid_inputs_are_validated_before_limiting(tmp_path):
    source = tmp_path / "qids.txt"
    source.write_text("Q1\nQ1\nQ2\n")
    assert select_qids(None, None, source, 1) == (["Q1"], {})
    assert select_qids(None, ["Q1", "Q2"], None, 2)[0] == ["Q1", "Q2"]
    source.write_text("Q1\nbad")
    with pytest.raises(ValueError):
        select_qids(None, None, source, 1)
    for args in [(None, None, None, 1), (None, ["Q1"], source, 1), (None, ["Q1"], None, 0)]:
        with pytest.raises(ValueError):
            select_qids(*args)


def test_damaged_cache_is_ignored_and_failure_stops_live_requests(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "Q1-9999.json").write_text("not JSON")
    (raw / "Q1-9998.json").write_text("[]")
    fetch = MagicMock(side_effect=ValueError("network failed"))
    report = collect_reports([record(), record("Q2")], ScrapeOptions(tmp_path), fetch)
    fetch.assert_called_once()
    assert [item["status"] for item in report["items"]] == ["failed", "not_attempted"]


def test_case_input_and_live_wikidata_context(tmp_path, monkeypatch):
    case = tmp_path / "case.json"
    case.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "title": "test",
                "sources": [],
                "entities": [
                    {
                        "key": "book",
                        "kind": "work",
                        "label": "Book",
                        "description": "a book",
                        "authors": ["Writer"],
                        "resolution": {"status": "existing", "qid": "Q1", "reason": "checked"},
                    }
                ],
            }
        )
    )
    qids, hints = select_qids(case, None, None, 10)
    assert hints == {"Q1": ["Writer"]}
    client = MagicMock()
    client.inspect_many.return_value = {
        "entities": {
            "Q1": {
                "id": "Q1",
                "labels": {"en": {"value": "Book"}},
                "claims": {
                    "P50": [
                        {
                            "mainsnak": {"datavalue": {"value": {"id": "Q2"}}},
                            "rank": "normal",
                        }
                    ]
                },
            }
        }
    }
    client.metadata.return_value = {"Q2": {"label": "Writer"}}
    manager = MagicMock()
    manager.__enter__.return_value = client
    monkeypatch.setattr(google_kg, "WikidataClient", lambda: manager)
    monkeypatch.setattr(google_kg, "collect_reports", lambda records, options: {"items": records})
    result = google_kg.scrape_google_kg(qids, hints, ScrapeOptions(tmp_path))
    assert result["items"][0]["query"] == "Book Writer"
    assert result["items"][0]["authors"] == ["Writer"]
    for delay in (0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            google_kg.scrape_google_kg(qids, hints, ScrapeOptions(tmp_path, delay=delay))


def test_browser_is_lazy_reused_and_closed(tmp_path, monkeypatch):
    from playwright import sync_api

    manager = MagicMock()
    browser = manager.__enter__.return_value.chromium.launch.return_value
    page = browser.new_page.return_value
    page.goto.return_value.status = 200
    page.url = search_url("x")
    page.content.return_value = "HTML"
    monkeypatch.setattr(sync_api, "sync_playwright", lambda: manager)
    with browser_fetcher(ScrapeOptions(tmp_path), None) as fetch:
        browser.new_page.assert_not_called()
        assert fetch(search_url("x")).html == "HTML"
        fetch(search_url("y"))
        browser.new_page.assert_called_once()
    browser.close.assert_called_once()
    page.goto.side_effect = sync_api.Error("failure")
    with (
        browser_fetcher(ScrapeOptions(tmp_path), None) as fetch,
        pytest.raises(ValueError, match="Browser search failed"),
    ):
        fetch(search_url("x"))


def test_cli_routes_and_exit_codes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "scrape_google_kg", lambda qids, hints, options: {"items": [{"status": "candidates"}]}
    )
    assert cli.main(["google-kg", "--qids", "Q1", "--output", str(tmp_path)]) == 0
    assert "report.md" in capsys.readouterr().out
    assert cli.main(["google-kg", "--qids", "Q1"]) == 2
    monkeypatch.setattr(
        cli, "scrape_google_kg", lambda qids, hints, options: {"items": [{"status": "blocked"}]}
    )
    assert cli.main(["google-kg", "--qids", "Q1", "--output", str(tmp_path)]) == 2
    source = tmp_path / "report.json"
    source.write_text("Q1")
    assert cli.main(["google-kg", "--qids-file", str(source), "--output", str(tmp_path)]) == 2

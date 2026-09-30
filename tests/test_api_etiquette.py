"""Wikidata transport, cooldown, and candidate-cache behavior."""

from __future__ import annotations

import email.utils
import fcntl
import json
import multiprocessing
import os
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from wikidata_pilot.api_transport import RetryBudgetExceeded, request_json
from wikidata_pilot.wikidata import API, WikidataClient


class MockClock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, duration: float) -> None:
        self.sleeps.append(duration)
        self.now += duration


def client_for(
    tmp_path: Path,
    transport: httpx.BaseTransport,
    clock: MockClock | None = None,
) -> WikidataClient:
    http = httpx.Client(transport=transport, timeout=20)
    values = {"client": http, "state_dir": tmp_path / "state"}
    if clock:
        values.update({"clock": clock.time, "sleep": clock.sleep, "jitter": lambda *_: 0.0})
    return WikidataClient(**values)  # type: ignore[arg-type]


def test_final_attempt_cooldown_persists_and_next_process_honors_it(tmp_path, capsys):
    clock = MockClock()
    calls = 0

    def throttled(_):
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "7"})

    http = httpx.Client(transport=httpx.MockTransport(throttled))
    with pytest.raises(RetryBudgetExceeded, match=r"retries exhausted\. Exiting"):
        request_json(
            http,
            API,
            params={"action": "query"},
            state_dir=tmp_path,
            clock=clock.time,
            sleep=clock.sleep,
            jitter=lambda *_: 0.0,
        )
    assert calls == 3
    assert clock.sleeps == [7.0, 7.0]
    assert capsys.readouterr().err.count("waiting 7s, then continuing automatically.") == 2
    saved = json.loads((tmp_path / "action.json").read_text())
    assert saved["cooldown_until"] == clock.now + 7

    success_http = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"ok": True}))
    )
    result = request_json(
        success_http,
        API,
        params={},
        state_dir=tmp_path,
        clock=clock.time,
        sleep=clock.sleep,
    )
    assert result == {"ok": True}
    assert clock.sleeps[-1] == 7.0


def test_retry_after_http_date_uses_injected_clock(tmp_path):
    clock = MockClock()
    retry_at = email.utils.formatdate(clock.now + 9, usegmt=True)
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": retry_at}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    http = httpx.Client(transport=httpx.MockTransport(lambda _: next(responses)))
    request_json(
        http,
        API,
        params={},
        state_dir=tmp_path,
        clock=clock.time,
        sleep=clock.sleep,
        jitter=lambda *_: 0.0,
    )
    assert clock.sleeps == [9.0]


def test_known_outage_has_minimum_sixty_second_wait(tmp_path):
    clock = MockClock()
    responses = iter(
        [
            httpx.Response(
                429,
                headers={"Retry-After": "1"},
                text="Aggressively rate-limiting to 1 req / min - active WDQS outage",
            ),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    http = httpx.Client(transport=httpx.MockTransport(lambda _: next(responses)))
    request_json(
        http,
        API,
        params={},
        state_dir=tmp_path,
        clock=clock.time,
        sleep=clock.sleep,
        jitter=lambda *_: 0.0,
    )
    assert clock.sleeps == [60.0]


def test_retry_budget_saves_long_cooldown_without_sleep(tmp_path):
    clock = MockClock()
    http = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(429, headers={"Retry-After": "180"}))
    )
    with pytest.raises(RetryBudgetExceeded, match="Exiting; cooldown saved until"):
        request_json(
            http,
            API,
            params={},
            state_dir=tmp_path,
            clock=clock.time,
            sleep=clock.sleep,
            jitter=lambda *_: 0.0,
        )
    assert clock.sleeps == []
    assert json.loads((tmp_path / "action.json").read_text())["cooldown_until"] == clock.now + 180


@pytest.mark.parametrize("payload", [{"error": {"code": "maxlag", "lag": 5}}])
def test_http_200_maxlag_is_retried(tmp_path, payload):
    clock = MockClock()
    responses = iter([httpx.Response(200, json=payload), httpx.Response(200, json={"ok": True})])
    http = httpx.Client(transport=httpx.MockTransport(lambda _: next(responses)))
    result = request_json(
        http,
        API,
        params={},
        state_dir=tmp_path,
        clock=clock.time,
        sleep=clock.sleep,
        jitter=lambda *_: 0.0,
    )
    assert result == {"ok": True}
    assert clock.sleeps == [5.0]


def test_unclassified_503_is_not_retried(tmp_path):
    calls = 0

    def respond(_):
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    http = httpx.Client(transport=httpx.MockTransport(respond))
    with pytest.raises(httpx.HTTPStatusError):
        request_json(http, API, params={}, state_dir=tmp_path, sleep=lambda _: None)
    assert calls == 1


def test_search_cache_expiry_and_explicit_bypass(tmp_path):
    clock = MockClock()
    calls = 0

    def respond(_):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"search": [{"id": "Q1", "label": "Name"}]})

    client = client_for(tmp_path, httpx.MockTransport(respond), clock)
    assert client.search_page("Name")["results"][0]["id"] == "Q1"
    client.search_page("Name")
    assert calls == 1
    client.search_page("Name", fresh=True)
    assert calls == 2
    clock.now += 301
    client.search_page("Name")
    assert calls == 3


def test_malformed_candidate_success_is_not_cached(tmp_path):
    calls = 0

    def respond(_):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={"search": [{"label": "Missing ID"}]})
        return httpx.Response(200, json={"search": [{"id": "Q1", "label": "Name"}]})

    client = client_for(tmp_path, httpx.MockTransport(respond))
    with pytest.raises(ValueError, match="result list"):
        client.search_page("Name")
    assert client.search_page("Name")["results"][0]["id"] == "Q1"
    assert calls == 2


def test_local_candidate_cache_hit_does_not_require_contact(tmp_path, monkeypatch):
    client = client_for(
        tmp_path,
        httpx.MockTransport(lambda _: httpx.Response(200, json={"search": []})),
    )
    assert client.search_page("Name")["results"] == []
    monkeypatch.delenv("WIKIDATA_PILOT_CONTACT")
    assert client.search_page("Name")["results"] == []
    with pytest.raises(ValueError, match="WIKIDATA_PILOT_CONTACT"):
        client.search_page("Name", fresh=True)


def test_fresh_candidate_bypass_still_obeys_saved_server_cooldown(tmp_path):
    clock = MockClock()
    calls = 0

    def respond(_):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"search": []})

    client = client_for(tmp_path, httpx.MockTransport(respond), clock)
    client.search_page("Name")
    with pytest.raises(RetryBudgetExceeded, match="Exiting; cooldown saved until"):
        request_json(
            httpx.Client(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(429, headers={"Retry-After": "180"})
                )
            ),
            API,
            params={},
            state_dir=tmp_path / "state",
            clock=clock.time,
            sleep=clock.sleep,
            jitter=lambda *_: 0.0,
        )
    with pytest.raises(RetryBudgetExceeded, match="cooldown exceeds the remaining wait budget"):
        client.search_page("Name", fresh=True)
    assert calls == 1


def test_inspection_is_fetched_on_every_call(tmp_path):
    calls = 0

    def respond(_):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"entities": {"Q1": {"id": "Q1"}}})

    client = client_for(tmp_path, httpx.MockTransport(respond))
    client.inspect("Q1")
    client.inspect("Q1")
    assert calls == 2


def test_relationship_candidate_results_are_cached_and_fresh_bypasses(tmp_path):
    clock = MockClock()
    calls = 0

    def respond(_):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"results": {"bindings": []}})

    client = client_for(tmp_path, httpx.MockTransport(respond), clock)
    assert client.linked("Q1", "P1433")["results"] == []
    client.linked("Q1", "P1433")
    client.ancestors("Q1")
    client.linked("Q1", "P1433", fresh=True)
    assert calls == 3


def test_action_api_sets_maxlag_and_identifying_user_agent(tmp_path):
    def respond(request):
        assert request.url.params["maxlag"] == "5"
        assert request.headers["user-agent"].startswith("wikidata-pilot/")
        assert "https://example.org/operator" in request.headers["user-agent"]
        return httpx.Response(200, json={"query": {"backlinks": []}})

    client = client_for(tmp_path, httpx.MockTransport(respond))
    payload = client.request({"action": "query"})
    query = payload.get("query")
    assert isinstance(query, dict)
    assert query["backlinks"] == []


def test_identifier_verifies_exact_value_and_preserves_continuation(tmp_path):
    exact_value = 'ab"\\ cd'
    requests = []

    def respond(request):
        requests.append(request)
        params = request.url.params
        if params.get("list") == "search":
            assert params["srsearch"] == 'haswbstatement:"P212=ab\\"\\\\ cd"'
            assert params["srprop"] == ""
            return httpx.Response(
                200,
                json={
                    "query": {"search": [{"title": "Q1"}, {"title": "Q2"}]},
                    "continue": {"sroffset": 12, "continue": "-||"},
                },
            )
        return httpx.Response(
            200,
            json={
                "entities": {
                    "Q1": {
                        "id": "Q1",
                        "labels": {"en": {"value": "Wrong case"}},
                        "claims": {
                            "P212": [
                                {
                                    "rank": "normal",
                                    "mainsnak": {
                                        "snaktype": "value",
                                        "datavalue": {"value": exact_value.upper()},
                                    },
                                }
                            ]
                        },
                    },
                    "Q2": {"missing": ""},
                }
            },
        )

    client = client_for(tmp_path, httpx.MockTransport(respond))
    result = client.identifier("P212", exact_value, limit=2, offset=10)
    assert result == {"results": [], "next_offset": 12}
    assert requests[1].url.params["ids"] == "Q1|Q2"


def test_preferred_statement_suppresses_matching_normal_statement(tmp_path):
    def respond(request):
        if request.url.params.get("list") == "search":
            return httpx.Response(200, json={"query": {"search": [{"title": "Q1"}]}})
        return httpx.Response(
            200,
            json={
                "entities": {
                    "Q1": {
                        "id": "Q1",
                        "labels": {"en": {"value": "Name"}},
                        "claims": {
                            "P212": [
                                {
                                    "rank": "normal",
                                    "mainsnak": {
                                        "snaktype": "value",
                                        "datavalue": {"value": "exact"},
                                    },
                                },
                                {
                                    "rank": "preferred",
                                    "mainsnak": {
                                        "snaktype": "value",
                                        "datavalue": {"value": "other"},
                                    },
                                },
                            ]
                        },
                    }
                }
            },
        )

    client = client_for(tmp_path, httpx.MockTransport(respond))
    assert client.identifier("P212", "exact")["results"] == []


def _serialized_request_worker(
    state_path: str, events: Any, worker_number: int, start: Any
) -> None:
    start.wait()

    def respond(_):
        events.put(("start", worker_number))
        time.sleep(0.08)
        events.put(("end", worker_number))
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        request_json(http, API, params={}, state_dir=Path(state_path))


def _crash_while_holding_lock(lock_path: str, ready: Any) -> None:
    with Path(lock_path).open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        ready.send(True)
        os._exit(0)


def test_cross_process_requests_serialize_and_crashed_lock_releases(tmp_path):
    context = multiprocessing.get_context("fork")
    events = context.Queue()
    start = context.Event()
    processes = [
        context.Process(
            target=_serialized_request_worker,
            args=(str(tmp_path), events, number, start),
        )
        for number in (1, 2)
    ]
    for process in processes:
        process.start()
    start.set()
    sequence = [events.get(timeout=5) for _ in range(4)]
    for process in processes:
        process.join(timeout=5)
        assert process.exitcode == 0
    assert sequence[0][0] == "start"
    assert sequence[1] == ("end", sequence[0][1])
    assert sequence[2][0] == "start"
    assert sequence[3] == ("end", sequence[2][1])

    ready, child_ready = context.Pipe(duplex=False)
    lock_path = tmp_path / "action.lock"
    crashed_process = context.Process(
        target=_crash_while_holding_lock, args=(str(lock_path), child_ready)
    )
    crashed_process.start()
    assert ready.poll(5) and ready.recv()
    crashed_process.join(timeout=5)
    assert crashed_process.exitcode == 0
    http = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"ok": True}))
    )
    assert request_json(http, API, params={}, state_dir=tmp_path) == {"ok": True}


def _save_cooldown_worker(state_path: str, now: float) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(429, headers={"Retry-After": "180"}))
    ) as http:
        try:
            request_json(http, API, params={}, state_dir=Path(state_path), clock=lambda: now)
        except RetryBudgetExceeded:
            return
    raise AssertionError("Long cooldown did not stop the request")


def test_cooldown_from_another_process_blocks_network(tmp_path):
    clock = MockClock()
    process = multiprocessing.get_context("fork").Process(
        target=_save_cooldown_worker, args=(str(tmp_path), clock.now)
    )
    process.start()
    process.join(timeout=5)
    assert process.exitcode == 0
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as http,
        pytest.raises(RetryBudgetExceeded, match="Exiting; cooldown saved until"),
    ):
        request_json(http, API, params={}, state_dir=tmp_path, clock=clock.time, sleep=clock.sleep)
    assert calls == []
    assert clock.sleeps == []


def test_malformed_identifier_hit_is_not_cached(tmp_path):
    client = client_for(
        tmp_path,
        httpx.MockTransport(lambda _: httpx.Response(200, json={"query": {"search": [{}]}})),
    )
    with pytest.raises(ValueError, match="title is malformed"):
        client.identifier("P212", "123")
    assert not (tmp_path / "state" / "candidates.json").exists()

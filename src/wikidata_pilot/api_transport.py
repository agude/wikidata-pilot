"""Serialized, bounded transport for Wikidata read requests."""

from __future__ import annotations

import email.utils
import fcntl
import json
import math
import os
import random
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

MAX_ATTEMPTS = 3
MAX_WAIT_SECONDS = 120.0
LOCK_TIMEOUT_SECONDS = 120.0
OUTAGE_COOLDOWN_SECONDS = 60.0


class RetryBudgetExceeded(ValueError):
    """The endpoint requested a cooldown longer than this operation can wait."""


def state_directory() -> Path:
    configured = os.environ.get("WIKIDATA_PILOT_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    cache_home = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache_home).expanduser() if cache_home else Path.home() / ".cache"
    return base / "wikidata-pilot"


def request_json(
    client: httpx.Client,
    endpoint: str,
    *,
    params: dict[str, str],
    headers: dict[str, str] | None = None,
    state_dir: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
    jitter: Callable[[float, float], float] = random.uniform,
) -> dict[str, Any]:
    """Request JSON while honoring shared endpoint locks and cooldowns."""
    directory = state_dir or state_directory()
    directory.mkdir(parents=True, exist_ok=True)
    endpoint_key = "action" if endpoint.endswith("/w/api.php") else "sparql"
    lock_path = directory / f"{endpoint_key}.lock"
    cooldown_path = directory / f"{endpoint_key}.json"
    lock_started = clock()
    with _locked(lock_path, started=lock_started, clock=clock, sleep=sleep):
        waited = max(0.0, clock() - lock_started)
        cooldown = _read_cooldown(cooldown_path)
        remaining = cooldown - clock()
        if remaining > 0:
            waited = _wait(
                remaining,
                waited,
                sleep,
                endpoint_key,
                cooldown_until=cooldown,
            )

        backoff = 5.0
        for attempt in range(1, MAX_ATTEMPTS + 1):
            response = client.get(endpoint, params=params, headers=headers)
            payload: Any = None
            if response.status_code == 200:
                try:
                    payload = response.json()
                except (ValueError, json.JSONDecodeError) as error:
                    response.raise_for_status()
                    raise ValueError("Wikidata returned malformed JSON") from error
                if isinstance(payload, dict) and _is_maxlag(payload):
                    delay = _retry_delay(
                        response,
                        fallback=backoff,
                        outage=False,
                        jitter=jitter,
                        clock=clock,
                    )
                else:
                    response.raise_for_status()
                    if not isinstance(payload, dict) or "error" in payload:
                        raise ValueError(f"Wikidata API returned an error: {payload}")
                    return payload
            elif response.status_code in {429, 503}:
                try:
                    payload = response.json()
                except (ValueError, json.JSONDecodeError):
                    payload = None
                if not _is_retryable_http(response, payload):
                    response.raise_for_status()
                    raise ValueError(f"Wikidata returned HTTP {response.status_code}")
                known_outage = _is_known_outage(response)
                delay = _retry_delay(
                    response,
                    fallback=backoff,
                    outage=known_outage,
                    jitter=jitter,
                    clock=clock,
                    minimum_delay=OUTAGE_COOLDOWN_SECONDS if known_outage else 0.0,
                )
            else:
                response.raise_for_status()
                raise ValueError(f"Wikidata returned HTTP {response.status_code}")

            cooldown_at = clock() + delay
            _write_cooldown(cooldown_path, cooldown_at)
            if attempt == MAX_ATTEMPTS:
                raise RetryBudgetExceeded(
                    f"{endpoint_key} is cooling down for {delay:.0f}s after the final attempt; "
                    f"retry after {_format_cooldown(cooldown_at)}"
                )
            waited = _wait(
                delay,
                waited,
                sleep,
                endpoint_key,
                cooldown_until=cooldown_at,
            )
            backoff *= 2
    raise AssertionError("request retry loop ended unexpectedly")


def _is_maxlag(payload: dict[str, Any]) -> bool:
    error = payload.get("error")
    return isinstance(error, dict) and error.get("code") == "maxlag"


def _is_retryable_http(response: httpx.Response, payload: Any) -> bool:
    if response.headers.get("Retry-After"):
        return True
    if isinstance(payload, dict) and _is_maxlag(payload):
        return True
    return response.status_code == 429


def _is_known_outage(response: httpx.Response) -> bool:
    message = f"{response.reason_phrase} {response.text}".lower()
    outage_signals = (
        "aggressively rate-limiting to 1 req / min",
        "active wdqs outage",
        "under maintenance",
        "database is locked",
        "database errors",
    )
    return any(signal in message for signal in outage_signals)


def _retry_delay(
    response: httpx.Response,
    *,
    fallback: float,
    outage: bool,
    jitter: Callable[[float, float], float],
    clock: Callable[[], float],
    minimum_delay: float = 0.0,
) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            delay = float(retry_after)
            if math.isfinite(delay):
                return max(minimum_delay, 0.0, delay)
        except ValueError:
            try:
                retry_at = email.utils.parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(minimum_delay, 0.0, retry_at.timestamp() - clock())
            except (TypeError, ValueError, OverflowError):
                pass
    delay = fallback + jitter(0.0, min(1.0, fallback * 0.2))
    return max(minimum_delay, OUTAGE_COOLDOWN_SECONDS, delay) if outage else delay


def _wait(
    delay: float,
    already_waited: float,
    sleep: Callable[[float], None],
    endpoint_key: str,
    *,
    cooldown_until: float,
) -> float:
    remaining_budget = MAX_WAIT_SECONDS - already_waited
    if delay > remaining_budget:
        retry_after = _format_cooldown(cooldown_until)
        raise RetryBudgetExceeded(
            f"{endpoint_key} requested a {delay:.0f}s cooldown; operation wait budget is "
            f"{MAX_WAIT_SECONDS:.0f}s. Cooldown was saved until {retry_after}; retry later."
        )
    print(f"Wikidata {endpoint_key} request paused for {delay:.0f}s.", file=sys.stderr)
    sleep(delay)
    return already_waited + delay


@contextmanager
def _locked(
    path: Path,
    *,
    started: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> Iterator[None]:
    with path.open("a+b") as lock_file:
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as error:
                if clock() - started >= LOCK_TIMEOUT_SECONDS:
                    raise RetryBudgetExceeded(
                        "Timed out waiting for another Wikidata request. Retry the command later."
                    ) from error
                sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_cooldown(path: Path) -> float:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        timestamp = float(value["cooldown_until"])
        return timestamp if math.isfinite(timestamp) else 0.0
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return 0.0


def _write_cooldown(path: Path, cooldown_at: float) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"cooldown_until": cooldown_at}), encoding="utf-8")
    temporary.replace(path)


def _format_cooldown(timestamp: float) -> str:
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return f"Unix timestamp {timestamp:.0f} (outside calendar range)"

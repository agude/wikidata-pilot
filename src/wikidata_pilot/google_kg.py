"""Slow Google searches and evidence files for human identifier review."""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

import httpx

from .api_transport import state_directory
from .cache import IdCache
from .inspection import summarize_entity
from .models import load_case
from .wikidata import WikidataClient

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

GOOGLE_SEARCH = "https://www.google.com/search"
GOOGLE_API = "https://kgsearch.googleapis.com/v1/entities:search"
ID_PATTERN = re.compile(r"/[gm]/[A-Za-z0-9_]+")
CONTEXT_PROPERTIES = ["P2671", "P646", "P31", "P50", "P577", "P629"]


@dataclass(frozen=True)
class ScrapeOptions:
    output: Path
    delay: float = 10
    headed: bool = False
    fresh: bool = False
    saved_pages: Path | None = None
    backend: str = "browser"
    limit: int = 5


@dataclass(frozen=True)
class Capture:
    url: str
    retrieved: str
    html: str
    status: int = 200
    payload: dict[str, Any] | None = None


def select_qids(
    case_path: Path | None, qids: list[str] | None, qids_file: Path | None, max_items: int
) -> tuple[list[str], dict[str, list[str]]]:
    """Validate all inputs before limiting a run; retain case search hints."""
    if sum(value is not None for value in (case_path, qids, qids_file)) != 1:
        raise ValueError("Supply exactly one case, --qids, or --qids-file")
    if max_items < 1:
        raise ValueError("--max-items must be positive")
    hints: dict[str, list[str]] = {}
    if case_path:
        case = load_case(case_path)
        qids = []
        for entity in case.entities:
            if entity.resolution.qid:
                qid = entity.resolution.qid
                qids.append(qid)
                hints.setdefault(qid, []).extend(entity.authors)
    elif qids_file:
        qids = qids_file.read_text(encoding="utf-8").split()
    qids = list(dict.fromkeys(qids or []))
    if not qids or any(not re.fullmatch(r"Q[1-9][0-9]*", qid) for qid in qids):
        raise ValueError("Supply valid Wikidata QIDs; a case needs resolved existing entities")
    return qids[:max_items], hints


def scrape_google_kg(
    qids: list[str], hints: dict[str, list[str]], options: ScrapeOptions
) -> dict[str, Any]:
    """Read current Wikidata context, then scrape without changing the case."""
    if not math.isfinite(options.delay) or options.delay < 10:
        raise ValueError("--delay must be at least 10 seconds")
    if options.backend not in {"api", "browser"} or not 1 <= options.limit <= 20:
        raise ValueError("Choose backend api or browser and --limit between 1 and 20")
    if options.backend == "api":
        if options.saved_pages or options.headed:
            raise ValueError("--saved-pages and --headed require the browser backend")
        if not os.environ.get("GOOGLE_KG_API_KEY", "").strip():
            raise ValueError("Set GOOGLE_KG_API_KEY in .env or the shell before API lookup")
    cache = IdCache()
    records: list[dict[str, Any]] = []
    with WikidataClient() as client:
        for start in range(0, len(qids), 50):
            payload = client.inspect_many(qids[start : start + 50])
            entities = payload["entities"]
            assert isinstance(entities, dict)
            if any(entities[qid].get("id") != qid for qid in qids[start : start + 50]):
                raise ValueError("Resolve redirected Wikidata QIDs before scraping")
            records.extend(
                summarize_entity({"entities": {qid: entities[qid]}}, cache, CONTEXT_PROPERTIES)
                for qid in qids[start : start + 50]
            )
        author_ids = {
            statement["value"]["id"]
            for record in records
            for statement in record["claims"]["P50"]["statements"]
            if isinstance(statement.get("value"), dict) and statement.get("rank") != "deprecated"
        }
        authors = client.metadata(sorted(author_ids)) if author_ids else {}
    for record in records:
        names = list(hints.get(record["id"], []))
        for statement in record["claims"]["P50"]["statements"]:
            value = statement.get("value")
            if (
                isinstance(value, dict)
                and value["id"] in authors
                and statement.get("rank") != "deprecated"
            ):
                names.append(authors[value["id"]]["label"])
        record["authors"] = list(dict.fromkeys(names))
        query = " ".join([record["label"], *record["authors"][:1]]).strip()
        record.update(
            query=query, search_url=search_url(query), status="not_attempted", candidates=[]
        )
        if options.backend == "api":
            params = {"query": query, "languages": "en", "limit": str(options.limit)}
            if any(
                s.get("value", {}).get("id") == "Q5"
                for s in record["claims"]["P31"]["statements"]
                if isinstance(s.get("value"), dict)
            ):
                params["types"] = "Person"
            record["request_url"] = GOOGLE_API + "?" + urlencode(params)
        else:
            record["request_url"] = record["search_url"]
    return collect_reports(records, options)


def collect_reports(
    records: list[dict[str, Any]],
    options: ScrapeOptions,
    fetch: Callable[[str], Capture] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Checkpoint progress and stop live searches after an access block."""
    options.output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema_version": 1,
        "created": utc_now(),
        "backend": options.backend,
        "items": records,
        "review": "Candidates require identity review; no claims are accepted or submitted.",
    }
    fetcher = api_fetcher if options.backend == "api" else browser_fetcher
    with fetcher(options, fetch) as fetch_page:
        blocked = False
        requested = False
        for record in records:
            qid = record["id"]
            identifiers = record["claims"]["P2671"]["statements"]
            if identifiers:
                record["status"] = (
                    "already_present"
                    if any(
                        isinstance(s.get("value"), str) and s.get("rank") != "deprecated"
                        for s in identifiers
                    )
                    else "identifier_review"
                )
            elif not record["label"]:
                record["status"] = "missing_label"
            else:
                print(f"Google KG: {qid} — {record['query']}", file=sys.stderr)
                try:
                    capture = load_capture(record, options)
                    if capture is None and blocked:
                        record["status"] = "not_attempted"
                    else:
                        if capture is None:
                            if requested:
                                sleep(options.delay)
                            requested = True
                            capture = fetch_page(record.get("request_url", record["search_url"]))
                        record["evidence"] = save_capture(record, capture, options.output)
                        reason = block_reason(capture)
                        if reason:
                            record.update(status="blocked", error=reason)
                            blocked = True
                        else:
                            candidates = (
                                extract_api_candidates(capture.payload)
                                if capture.payload is not None
                                else extract_candidates(capture.html)
                            )
                            for candidate in candidates:
                                statements = record["claims"][candidate["property"]]["statements"]
                                candidate["already_present"] = any(
                                    s.get("value") == candidate["id"] for s in statements
                                )
                            record.update(
                                candidates=candidates,
                                status="candidates" if candidates else "no_candidates",
                            )
                except (OSError, ValueError) as error:
                    record.update(status="failed", error=str(error))
                    if options.saved_pages is None:
                        blocked = True
            write_reports(report, options.output)
    return report


@contextmanager
def api_fetcher(
    options: ScrapeOptions, fetch: Callable[[str], Capture] | None
) -> Iterator[Callable[[str], Capture]]:
    """Use a header-only key; suppress remote exception details and redact echoes."""
    if fetch is not None:
        yield fetch
        return
    key = os.environ.get("GOOGLE_KG_API_KEY", "").strip()
    if not key:
        raise ValueError("Set GOOGLE_KG_API_KEY in .env or the shell before API lookup")
    with httpx.Client(timeout=20, headers={"X-Goog-Api-Key": key}) as client:

        def fetch_page(url: str) -> Capture:
            try:
                response = client.get(url)
                payload = json.loads(response.text.replace(key, "[REDACTED]"))
            except httpx.HTTPError:
                raise ValueError(
                    "Google API network request failed; credential details suppressed"
                ) from None
            except ValueError:
                raise ValueError("Google API returned malformed JSON") from None
            if not isinstance(payload, dict):
                raise ValueError("Google API returned a non-object response")
            return Capture(url, utc_now(), "", response.status_code, payload)

        yield fetch_page


def extract_api_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep all returned candidates and their JSON locators for identity review."""
    entries = payload.get("itemListElement")
    if "error" in payload or not isinstance(entries, list):
        raise ValueError("Google API returned an error or malformed candidate list")
    candidates: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(entries):
        result = entry.get("result") if isinstance(entry, dict) else None
        if not isinstance(result, dict) or not isinstance(result.get("@id"), str):
            raise ValueError("Google API returned a malformed candidate")
        identifier = result["@id"].removeprefix("kg:")
        if not ID_PATTERN.fullmatch(identifier):
            raise ValueError("Google API returned an unsupported identifier format")
        candidate = candidates.setdefault(
            identifier,
            {
                "id": identifier,
                "property": "P2671" if identifier.startswith("/g/") else "P646",
                "url": GOOGLE_SEARCH + "?" + urlencode({"kgmid": identifier}),
                "name": result.get("name", ""),
                "description": result.get("description", ""),
                "types": result.get("@type", []),
                "website": result.get("url"),
                "detailed_description": result.get("detailedDescription"),
                "result_score": entry.get("resultScore"),
                "occurrences": [],
            },
        )
        candidate["occurrences"].append(
            {
                "locator": f"$.itemListElement[{index}].result",
                "excerpt": json.dumps(result, ensure_ascii=False),
            }
        )
    return list(candidates.values())


@contextmanager
def browser_fetcher(
    options: ScrapeOptions, fetch: Callable[[str], Capture] | None
) -> Iterator[Callable[[str], Capture]]:
    """Start a separate browser lazily, only if a live search is needed."""
    if fetch is not None:
        yield fetch
        return
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(state_directory() / "browsers"))
    from playwright.sync_api import Error, sync_playwright

    with ExitStack() as resources:
        browser: Browser | None = None
        page: Page | None = None

        def fetch_page(url: str) -> Capture:
            nonlocal browser, page
            try:
                if page is None:
                    playwright = resources.enter_context(sync_playwright())
                    browser = playwright.chromium.launch(headless=not options.headed)
                    page = browser.new_page(locale="en-US")
                response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # Capture the rendered DOM after the initial search page settles.
                page.wait_for_timeout(2000)
                return Capture(
                    page.url, utc_now(), page.content(), response.status if response else 0
                )
            except Error as error:
                raise ValueError(
                    "Browser search failed; install Chromium with 'uv run playwright install chromium'. "
                    f"Details: {error}"
                ) from error

        try:
            yield fetch_page
        finally:
            if browser is not None:
                browser.close()


def search_url(query: str) -> str:
    return GOOGLE_SEARCH + "?" + urlencode({"q": query, "hl": "en"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def block_reason(capture: Capture) -> str | None:
    if capture.payload is not None:
        if capture.status != 200 or "error" in capture.payload:
            return (
                f"Google API returned HTTP {capture.status} or an API error; live requests stopped"
            )
        return None
    page = capture.html.lower()
    host = urlsplit(capture.url).hostname or ""
    if capture.status != 200:
        return f"Google returned HTTP {capture.status}; live searches stopped"
    if host == "consent.google.com" or "before you continue to google" in page:
        return "Google requires consent; live searches stopped"
    if "/sorry/" in capture.url or any(
        text in page for text in ("our systems have detected unusual traffic", 'id="captcha-form"')
    ):
        return "Google requires a CAPTCHA; live searches stopped"
    if "please enable javascript" in page or (
        "enablejs" in page
        and not any(marker in page for marker in ('id="search"', 'id="rso"', "data-kpid="))
    ):
        return "Google returned a JavaScript interstitial; live searches stopped"
    return None


def load_capture(record: dict[str, Any], options: ScrapeOptions) -> Capture | None:
    if options.saved_pages:
        base = options.saved_pages / record["id"]
        metadata = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
        return capture_from_metadata(metadata, base.with_suffix(".html"))
    if not options.fresh:
        for path in sorted((options.output / "raw").glob(f"{record['id']}-*.json"), reverse=True):
            try:
                metadata = json.loads(path.read_text(encoding="utf-8"))
                if (
                    not isinstance(metadata, dict)
                    or metadata.get("query") != record["query"]
                    or metadata.get("backend", "browser") != options.backend
                    or metadata.get("url") != record.get("request_url", record["search_url"])
                ):
                    continue
                capture = capture_from_metadata(metadata, path.with_suffix(".html"))
                retrieved = datetime.fromisoformat(capture.retrieved)
                if retrieved.tzinfo:
                    age = datetime.now(timezone.utc) - retrieved
                    if timedelta(0) <= age < timedelta(days=1) and block_reason(capture) is None:
                        return capture
            except (OSError, ValueError):
                # Incomplete or damaged cached captures are never treated as evidence.
                continue
    return None


def capture_from_metadata(metadata: dict[str, Any], path: Path) -> Capture:
    if not isinstance(metadata, dict):
        raise ValueError("Saved page metadata must be a JSON object")
    url = metadata.get("url", "")
    if not isinstance(url, str) or urlsplit(url).hostname not in {
        "www.google.com",
        "google.com",
        "consent.google.com",
        "kgsearch.googleapis.com",
    }:
        raise ValueError("Saved page metadata needs its Google source URL")
    retrieved = metadata.get("retrieved", "")
    if not isinstance(retrieved, str):
        raise ValueError("Saved page metadata needs an ISO retrieval date or timestamp")
    datetime.fromisoformat(retrieved)
    if metadata.get("backend") == "api":
        payload = json.loads(path.with_suffix(".response.json").read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Cached API response must be a JSON object")
        return Capture(url, retrieved, "", metadata.get("status", 200), payload)
    return Capture(url, retrieved, path.read_text(encoding="utf-8"), metadata.get("status", 200))


def save_capture(record: dict[str, Any], capture: Capture, output: Path) -> dict[str, str]:
    directory = output / "raw"
    directory.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    base = directory / f"{record['id']}-{stamp}"
    content_path = base.with_suffix(".response.json" if capture.payload is not None else ".html")
    contents = (
        json.dumps(capture.payload, indent=2, ensure_ascii=False) + "\n"
        if capture.payload is not None
        else capture.html
    )
    content_path.write_text(contents, encoding="utf-8")
    metadata = {
        "qid": record["id"],
        "query": record["query"],
        "url": capture.url,
        "retrieved": capture.retrieved,
        "status": capture.status,
        "backend": "api" if capture.payload is not None else "browser",
    }
    base.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return {
        "json" if capture.payload is not None else "html": str(content_path),
        "url": capture.url,
        "retrieved": capture.retrieved,
    }


class PanelParser(HTMLParser):
    """Collect IDs only from entity attributes and explicit Google entity links."""

    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.lines = html.splitlines()
        self.candidates: dict[str, dict[str, Any]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if value is None:
                continue
            ids: list[str] = []
            if name in {"data-kpid", "data-entityid"}:
                normalized = value.removeprefix("vise:")
                if ID_PATTERN.fullmatch(normalized):
                    ids = [normalized]
            elif name == "href":
                url = urlsplit(value)
                if url.hostname in {None, "www.google.com", "google.com"} and url.path == "/search":
                    ids = [
                        i for i in parse_qs(url.query).get("kgmid", []) if ID_PATTERN.fullmatch(i)
                    ]
                elif url.hostname == "g.co" and url.path.startswith("/kg/"):
                    normalized = unquote(url.path.removeprefix("/kg"))
                    if ID_PATTERN.fullmatch(normalized):
                        ids = [normalized]
            for identifier in ids:
                line, column = self.getpos()
                candidate = self.candidates.setdefault(
                    identifier,
                    {
                        "id": identifier,
                        "property": "P2671" if identifier.startswith("/g/") else "P646",
                        "url": GOOGLE_SEARCH + "?" + urlencode({"kgmid": identifier}),
                        "occurrences": [],
                    },
                )
                candidate["occurrences"].append(
                    {
                        "locator": f"line {line}, column {column}, {tag}[{name}]",
                        "attribute": value,
                        "excerpt": self.lines[line - 1][max(0, column - 200) : column + 1000],
                    }
                )


def extract_candidates(html: str) -> list[dict[str, Any]]:
    parser = PanelParser(html)
    parser.feed(html)
    return list(parser.candidates.values())


def write_reports(report: dict[str, Any], output: Path) -> None:
    (output / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = ["# Google Knowledge Graph candidate review", "", report["review"], ""]
    for record in report["items"]:
        lines.extend(
            [
                f"## {record['id']}: {record['label']}",
                "",
                record.get("description", ""),
                "",
                f"Status: **{record['status']}**",
                "",
                f"[Search Google]({record['search_url']})",
                "",
            ]
        )
        if record.get("error"):
            lines.extend([record["error"], ""])
        for property_id in ("P2671", "P646"):
            statements = record["claims"][property_id]["statements"]
            if statements:
                lines.extend(
                    [f"Existing {property_id}: `{json.dumps(statements, ensure_ascii=False)}`", ""]
                )
        if record.get("evidence"):
            evidence = record["evidence"]
            lines.extend(
                [
                    f"Retrieved: {evidence['retrieved']}",
                    "",
                    f"Saved evidence: `{evidence.get('json', evidence.get('html'))}`",
                    "",
                ]
            )
        for candidate in record["candidates"]:
            if candidate.get("name"):
                lines.extend([f"{candidate['name']} — {candidate.get('description', '')}", ""])
            lines.extend(
                [
                    f"- [{candidate['id']}]({candidate['url']}) → {candidate['property']}"
                    + (
                        " (already present)"
                        if candidate["already_present"]
                        else " (review required)"
                    ),
                ]
            )
        lines.append("")
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")

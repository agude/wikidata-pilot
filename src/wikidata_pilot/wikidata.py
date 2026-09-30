"""Read-only Wikidata API access and candidate searches."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from . import __version__
from .api_transport import request_json, state_directory

API = "https://www.wikidata.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
CANDIDATE_TTL_SECONDS = 300
MAX_CANDIDATE_CACHE_ENTRIES = 128


class WikidataClient:
    """Small read-only client for item inspection and entity search."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        state_dir: Path | None = None,
        clock: Any = time.time,
        sleep: Any = time.sleep,
        jitter: Any = None,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=20, headers={"Accept-Encoding": "gzip, deflate"}
        )
        self._owns_client = client is None
        self.state_dir = state_dir or state_directory()
        self._clock = clock
        self._sleep = sleep
        self._jitter = jitter

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> WikidataClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def request(self, params: dict[str, str]) -> dict[str, object]:
        request_params = {**params, "maxlag": "5"}
        return self._get_json(API, params=request_params)

    def _get_json(
        self, endpoint: str, *, params: dict[str, str], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        contact = os.environ.get("WIKIDATA_PILOT_CONTACT", "").strip()
        if not contact:
            raise ValueError(
                "Set WIKIDATA_PILOT_CONTACT to an operator email or project URL before "
                "making Wikidata API requests; see docs/commands.md#api-access"
            )
        user_agent = f"wikidata-pilot/{__version__} ({contact})"
        request_headers = {"User-Agent": user_agent, **(headers or {})}
        if self._jitter is None:
            return request_json(
                self.client,
                endpoint,
                params=params,
                headers=request_headers,
                state_dir=self.state_dir,
                sleep=self._sleep,
                clock=self._clock,
            )
        return request_json(
            self.client,
            endpoint,
            params=params,
            headers=request_headers,
            state_dir=self.state_dir,
            sleep=self._sleep,
            clock=self._clock,
            jitter=self._jitter,
        )

    def inspect(self, qid: str) -> dict[str, object]:
        return self.inspect_many([qid])

    def inspect_many(self, ids: list[str]) -> dict[str, object]:
        """Fetch a bounded set of records together without updating local files."""
        if (
            not ids
            or len(ids) > 50
            or any(not re.fullmatch(r"[QP][1-9][0-9]*", identifier) for identifier in ids)
        ):
            raise ValueError("Supply 1-50 Wikidata QIDs or PIDs")
        payload = self.request(
            {
                "action": "wbgetentities",
                "ids": "|".join(dict.fromkeys(ids)),
                "format": "json",
                "props": "info|labels|descriptions|aliases|datatype|claims|sitelinks",
                "languages": "en",
            }
        )
        entities = payload.get("entities")
        if not isinstance(entities, dict) or not entities:
            raise ValueError("Wikidata did not return entities")
        for identifier in ids:
            item = entities.get(identifier)
            if not isinstance(item, dict) or "missing" in item:
                raise ValueError(f"Wikidata item {identifier} is missing")
        return payload

    def metadata(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch English metadata in API batches of at most 50 IDs."""
        if any(not re.fullmatch(r"[QP][1-9][0-9]*", identifier) for identifier in ids):
            raise ValueError("Expected Wikidata QIDs or PIDs")
        result: dict[str, dict[str, Any]] = {}
        for offset in range(0, len(ids), 50):
            batch = ids[offset : offset + 50]
            payload = self.request(
                {
                    "action": "wbgetentities",
                    "ids": "|".join(batch),
                    "format": "json",
                    "props": "labels|descriptions|aliases|datatype",
                    "languages": "en",
                }
            )
            entities = payload.get("entities")
            if not isinstance(entities, dict):
                raise ValueError("Wikidata metadata response has no entities")
            for identifier in batch:
                item = entities.get(identifier)
                if not isinstance(item, dict) or "missing" in item:
                    raise ValueError(f"Wikidata entity {identifier} is missing")
                # Redirects need an identity decision, not an implicit cache alias.
                if item.get("id") != identifier:
                    raise ValueError(f"Wikidata redirected {identifier}; inspect its identity")
                result[identifier] = {
                    "label": item.get("labels", {}).get("en", {}).get("value", ""),
                    "description": item.get("descriptions", {}).get("en", {}).get("value", ""),
                    "aliases": [alias["value"] for alias in item.get("aliases", {}).get("en", [])],
                    "datatype": item.get("datatype"),
                    "retrieved": date.today().isoformat(),
                }
        return result

    def search(self, query: str) -> list[dict[str, str]]:
        """Search item names for case matching, using the first ten results."""
        page = self.search_page(query)
        results: list[dict[str, str]] = page["results"]
        return results

    def search_page(
        self,
        query: str,
        *,
        entity_type: str = "item",
        limit: int = 10,
        offset: int = 0,
        fresh: bool = False,
    ) -> dict[str, Any]:
        """Search names and aliases with an explicit continuation offset."""
        _validate_page(limit, offset)
        if entity_type not in {"item", "property"} or not query.strip():
            raise ValueError("Supply a nonempty query and type item or property")
        params = {
            "action": "wbsearchentities",
            "search": query,
            "type": entity_type,
            "language": "en",
            "format": "json",
            "limit": str(limit),
            "continue": str(offset),
        }
        cached = None if fresh else self._candidate_cache_read(API, params)
        if cached is not None:
            return cached
        payload = self.request(params)
        results = payload.get("search")
        if not isinstance(results, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in results
        ):
            raise ValueError("Wikidata search response has no result list")
        continuation = payload.get("search-continue")
        if continuation is not None and (
            not isinstance(continuation, int) or continuation <= offset
        ):
            raise ValueError("Wikidata search continuation is malformed")
        result = {
            "results": [
                {
                    key: str(value)
                    for key, value in item.items()
                    if key in {"id", "label", "description"}
                }
                for item in results
            ],
            "next_offset": continuation,
        }
        self._candidate_cache_write(API, params, result)
        return result

    def linked(
        self,
        qid: str,
        property_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        fresh: bool = False,
    ) -> dict[str, Any]:
        """Find incoming best-ranked item statements through the query API."""
        _validate_page(limit, offset)
        if not re.fullmatch(r"Q[1-9][0-9]*", qid) or not re.fullmatch(r"P[1-9][0-9]*", property_id):
            raise ValueError("Expected a target QID and relationship PID")
        query = (
            "SELECT DISTINCT ?item ?itemLabel ?itemDescription WHERE { "
            f"?item wdt:{property_id} wd:{qid}. "
            "SERVICE wikibase:label { bd:serviceParam wikibase:language 'en'. } "
            f"}} ORDER BY ?item LIMIT {limit + 1} OFFSET {offset}"
        )
        return self._item_query(query, limit, offset, fresh=fresh)

    def identifier(
        self,
        property_id: str,
        value: str,
        *,
        limit: int = 10,
        offset: int = 0,
        fresh: bool = False,
    ) -> dict[str, Any]:
        """Find exact identifier matches using the Action API search index."""
        _validate_page(limit, offset)
        if not re.fullmatch(r"P[1-9][0-9]*", property_id) or not value.strip():
            raise ValueError("Supply a Wikidata property ID and nonempty identifier value")
        if property_id in {"P1433", "P2860"}:
            if not re.fullmatch(r"Q[1-9][0-9]*", value):
                raise ValueError(
                    f"{property_id} requires an item QID for exact relationship lookup"
                )
            query = (
                "SELECT DISTINCT ?item ?itemLabel ?itemDescription WHERE { "
                f"?item wdt:{property_id} wd:{value}. "
                "SERVICE wikibase:label { bd:serviceParam wikibase:language 'en'. } "
                f"}} ORDER BY ?item LIMIT {limit + 1} OFFSET {offset}"
            )
            return self._item_query(query, limit, offset, fresh=fresh)
        search_value = value.replace("\\", "\\\\").replace('"', '\\"')
        params = {
            "action": "query",
            "list": "search",
            "srsearch": f'haswbstatement:"{property_id}={search_value}"',
            "srnamespace": "0",
            "srlimit": str(limit),
            "sroffset": str(offset),
            "srprop": "",
            "format": "json",
        }
        cached = None if fresh else self._candidate_cache_read(API, params)
        if cached is not None:
            return cached
        payload = self.request(params)
        query_response = payload.get("query")
        search_results = query_response.get("search") if isinstance(query_response, dict) else None
        if not isinstance(search_results, list) or any(
            not isinstance(row, dict) for row in search_results
        ):
            raise ValueError("Wikidata identifier search response is malformed")
        ids: list[str] = []
        for row in search_results:
            title = row.get("title")
            if not isinstance(title, str) or not re.fullmatch(r"Q[1-9][0-9]*", title):
                raise ValueError("Wikidata identifier search title is malformed")
            ids.append(title)
        verified = self._verify_identifier_candidates(ids, property_id, value)
        continuation = payload.get("continue", {})
        if not isinstance(continuation, dict):
            raise ValueError("Wikidata identifier search continuation is malformed")
        next_offset = continuation.get("sroffset")
        if next_offset is not None and (not isinstance(next_offset, int) or next_offset <= offset):
            raise ValueError("Wikidata identifier search offset is malformed")
        result = {
            "results": verified,
            # Preserve the API offset even when every indexed hit fails exact verification.
            "next_offset": next_offset,
        }
        self._candidate_cache_write(API, params, result)
        return result

    def _verify_identifier_candidates(
        self, ids: list[str], property_id: str, value: str
    ) -> list[dict[str, str]]:
        if not ids:
            return []
        payload = self.request(
            {
                "action": "wbgetentities",
                "ids": "|".join(dict.fromkeys(ids)),
                "format": "json",
                "props": "labels|descriptions|claims",
                "languages": "en",
            }
        )
        entities = payload.get("entities")
        if not isinstance(entities, dict):
            raise ValueError("Wikidata identifier inspection has no entities")
        matched: list[dict[str, str]] = []
        for identifier in ids:
            entity = entities.get(identifier)
            if not isinstance(entity, dict) or entity.get("id") != identifier:
                continue
            claims = entity.get("claims")
            if not isinstance(claims, dict):
                raise ValueError("Wikidata identifier entity has malformed claims")
            statements = claims.get(property_id, [])
            if not isinstance(statements, list) or any(
                not isinstance(statement, dict) for statement in statements
            ):
                raise ValueError("Wikidata identifier statements are malformed")
            live = [statement for statement in statements if statement.get("rank") != "deprecated"]
            preferred = [statement for statement in live if statement.get("rank") == "preferred"]
            selected = preferred or [
                statement for statement in live if statement.get("rank") == "normal"
            ]
            if not any(_statement_string(statement) == value for statement in selected):
                continue
            labels = entity.get("labels", {})
            descriptions = entity.get("descriptions", {})
            if not isinstance(labels, dict) or not isinstance(descriptions, dict):
                raise ValueError("Wikidata identifier entity metadata is malformed")
            english_label = labels.get("en", {})
            english_description = descriptions.get("en", {})
            if not isinstance(english_label, dict) or not isinstance(english_description, dict):
                raise ValueError("Wikidata identifier English metadata is malformed")
            matched.append(
                {
                    "id": identifier,
                    "label": str(english_label.get("value", "")),
                    "description": str(english_description.get("value", "")),
                }
            )
        return matched

    def _candidate_cache_read(self, endpoint: str, params: dict[str, str]) -> dict[str, Any] | None:
        key = _candidate_cache_key(endpoint, params)
        path = self.state_dir / "candidates.json"
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
            entry = records.get(key)
            if not isinstance(entry, dict):
                return None
            expires = float(entry["expires"])
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None
        if not math.isfinite(expires) or expires <= self._clock():
            return None
        value = entry.get("result")
        return value if isinstance(value, dict) else None

    def _candidate_cache_write(
        self, endpoint: str, params: dict[str, str], result: dict[str, Any]
    ) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        path = self.state_dir / "candidates.json"
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(records, dict):
                records = {}
        except (OSError, ValueError):
            records = {}
        now = self._clock()
        live_records: dict[str, Any] = {}
        for key, entry in records.items():
            if not isinstance(entry, dict):
                continue
            try:
                expires = float(entry.get("expires", 0))
            except (TypeError, ValueError):
                continue
            if math.isfinite(expires) and expires > now:
                live_records[key] = entry
        records = live_records
        records[_candidate_cache_key(endpoint, params)] = {
            "expires": now + CANDIDATE_TTL_SECONDS,
            "result": result,
        }
        if len(records) > MAX_CANDIDATE_CACHE_ENTRIES:
            records = dict(list(records.items())[-MAX_CANDIDATE_CACHE_ENTRIES:])
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=self.state_dir, delete=False
        ) as temporary:
            json.dump(records, temporary, separators=(",", ":"))
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)

    def ancestors(
        self,
        qid: str,
        *,
        instance_of: bool = False,
        limit: int = 50,
        offset: int = 0,
        fresh: bool = False,
    ) -> dict[str, Any]:
        """Find superclasses, or the classes of an instance and their superclasses."""
        _validate_page(limit, offset)
        if not re.fullmatch(r"Q[1-9][0-9]*", qid):
            raise ValueError("Expected a class or instance QID")
        path = "wdt:P31/wdt:P279*" if instance_of else "wdt:P279+"
        query = (
            "SELECT DISTINCT ?item ?itemLabel ?itemDescription WHERE { "
            f"wd:{qid} {path} ?item. FILTER(?item != wd:{qid}) "
            "SERVICE wikibase:label { bd:serviceParam wikibase:language 'en'. } "
            f"}} ORDER BY ?item LIMIT {limit + 1} OFFSET {offset}"
        )
        return self._item_query(query, limit, offset, fresh=fresh)

    def _item_query(
        self, query: str, limit: int, offset: int, *, fresh: bool = False
    ) -> dict[str, Any]:
        params = {"query": query, "format": "json"}
        cached = None if fresh else self._candidate_cache_read(SPARQL, params)
        if cached is not None:
            return cached
        payload = self._get_json(
            SPARQL,
            params=params,
            headers={"Accept": "application/sparql-results+json"},
        )
        try:
            bindings = payload["results"]["bindings"]
            if not isinstance(bindings, list):
                raise ValueError("Wikidata query bindings are malformed")
            results = []
            for row in bindings[:limit]:
                uri = row["item"]["value"]
                if not isinstance(uri, str):
                    raise ValueError("Wikidata query entity URI is malformed")
                label = row.get("itemLabel", {}).get("value", "")
                description = row.get("itemDescription", {}).get("value", "")
                if not isinstance(label, str) or not isinstance(description, str):
                    raise ValueError("Wikidata query labels are malformed")
                results.append(
                    {
                        "id": uri.rsplit("/", 1)[-1],
                        "label": label,
                        "description": description,
                    }
                )
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError("Wikidata query response is malformed") from error
        result = {
            "results": results,
            "next_offset": offset + limit if len(bindings) > limit else None,
        }
        self._candidate_cache_write(SPARQL, params, result)
        return result

    def backlinks(self, qid: str, *, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        """List incoming item-page links; these do not identify a property."""
        _validate_page(limit, 0)
        if not re.fullmatch(r"Q[1-9][0-9]*", qid):
            raise ValueError("Expected a target QID")
        params = {
            "action": "query",
            "list": "backlinks",
            "bltitle": qid,
            "blnamespace": "0",
            "bllimit": str(limit),
            "format": "json",
        }
        if cursor is not None:
            params.update({"blcontinue": cursor, "continue": "-||"})
        payload = self.request(params)
        query = payload.get("query")
        if not isinstance(query, dict) or not isinstance(query.get("backlinks"), list):
            raise ValueError("Wikidata backlinks response is malformed")
        results = []
        for item in query["backlinks"]:
            if not isinstance(item, dict) or not isinstance(item.get("title"), str):
                raise ValueError("Wikidata backlink is malformed")
            results.append({"id": item["title"]})
        continuation = payload.get("continue", {})
        if not isinstance(continuation, dict):
            raise ValueError("Wikidata backlinks continuation is malformed")
        next_cursor = continuation.get("blcontinue")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise ValueError("Wikidata backlinks cursor is malformed")
        return {"results": results, "next_cursor": next_cursor}

    def page(self, title: str, *, section: int | None = None) -> dict[str, Any]:
        """Read guidance-page sections or selected wikitext through the API."""
        if not title.strip() or title.startswith("Special:") or re.fullmatch(r"[QP][0-9]+", title):
            raise ValueError("Supply a guidance-page title; use inspect for entity IDs")
        if section is not None and section < 0:
            raise ValueError("Section must be nonnegative")
        params = {
            "action": "parse",
            "page": title,
            "format": "json",
            "formatversion": "2",
            "prop": "tocdata|revid" if section is None else "wikitext|revid",
        }
        if section is not None:
            params["section"] = str(section)
        payload = self.request(params)
        parsed = payload.get("parse")
        if not isinstance(parsed, dict):
            raise ValueError("Wikidata page response is malformed")
        result: dict[str, Any] = {"title": parsed.get("title", title)}
        if section is None:
            toc = parsed.get("tocdata")
            if not isinstance(toc, dict) or not isinstance(toc.get("sections"), list):
                raise ValueError("Wikidata page sections are malformed")
            result["sections"] = [
                {
                    "index": item.get("index", ""),
                    "heading": item.get("line", ""),
                    "page": item.get("fromTitle", title),
                }
                for item in toc["sections"]
            ]
        else:
            if not isinstance(parsed.get("wikitext"), str):
                raise ValueError("Wikidata page text is malformed")
            result["wikitext"] = parsed["wikitext"]
        if "revid" in parsed:
            result["revision"] = parsed["revid"]
        return result

    def resolve(self, site: str, title: str) -> dict[str, Any]:
        """Resolve one wiki sitelink; an absent result has a null ID."""
        if not re.fullmatch(r"[a-z][a-z0-9_\-]*", site) or not title.strip() or "|" in title:
            raise ValueError("Supply a site ID and one nonempty page title")
        payload = self.request(
            {
                "action": "wbgetentities",
                "sites": site,
                "titles": title,
                "props": "labels|descriptions|sitelinks",
                "languages": "en",
                "redirects": "yes",
                "format": "json",
            }
        )
        entities = payload.get("entities")
        if not isinstance(entities, dict) or len(entities) != 1:
            raise ValueError("Wikidata sitelink response is malformed")
        entity = next(iter(entities.values()))
        if not isinstance(entity, dict):
            raise ValueError("Wikidata sitelink entity is malformed")
        result: dict[str, Any] = {"site": site, "requested_title": title, "id": None}
        if "missing" not in entity:
            if not isinstance(entity.get("id"), str):
                raise ValueError("Wikidata sitelink response has no ID")
            result.update(
                {
                    "id": entity["id"],
                    "label": entity.get("labels", {}).get("en", {}).get("value", ""),
                    "description": entity.get("descriptions", {}).get("en", {}).get("value", ""),
                    "title": entity.get("sitelinks", {}).get(site, {}).get("title", title),
                }
            )
        if "redirects" in payload:
            result["redirects"] = payload["redirects"]
        return result

    def history(
        self, identifier: str, *, limit: int = 10, cursor: str | None = None
    ) -> dict[str, Any]:
        """Read revision metadata without downloading historical entity content."""
        _validate_page(limit, 0)
        if not re.fullmatch(r"[QP][1-9][0-9]*", identifier):
            raise ValueError("Expected a Wikidata QID or PID")
        title = f"Property:{identifier}" if identifier.startswith("P") else identifier
        params = {
            "action": "query",
            "prop": "revisions",
            "titles": title,
            "rvprop": "ids|timestamp|user|comment",
            "rvlimit": str(limit),
            "format": "json",
            "formatversion": "2",
        }
        if cursor is not None:
            params.update({"rvcontinue": cursor, "continue": "||"})
        payload: dict[str, Any] = self.request(params)
        try:
            pages = payload["query"]["pages"]
            if not isinstance(pages, list) or len(pages) != 1:
                raise ValueError("Wikidata history page list is malformed")
            page = pages[0]
            revisions = page["revisions"]
            if (
                "missing" in page
                or not isinstance(revisions, list)
                or any(
                    not isinstance(revision, dict) or "revid" not in revision
                    for revision in revisions
                )
            ):
                raise ValueError("Wikidata revisions are unavailable or malformed")
            continuation = payload.get("continue", {}).get("rvcontinue")
            if continuation is not None and not isinstance(continuation, str):
                raise ValueError("Wikidata revision cursor is malformed")
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError("Wikidata history response is malformed") from error
        return {"id": identifier, "revisions": revisions, "next_cursor": continuation}

    def search_identifier(self, property_id: str, identifier: str) -> list[dict[str, str]]:
        """Return identifier candidates for the existing case-matching workflow."""
        results: list[dict[str, str]] = self.identifier(property_id, identifier, limit=20)[
            "results"
        ]
        return results


def _candidate_cache_key(endpoint: str, params: dict[str, str]) -> str:
    identity = json.dumps([endpoint, sorted(params.items())], separators=(",", ":"))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _statement_string(statement: Any) -> str | None:
    if not isinstance(statement, dict):
        return None
    mainsnak = statement.get("mainsnak")
    if not isinstance(mainsnak, dict) or mainsnak.get("snaktype") != "value":
        return None
    datavalue = mainsnak.get("datavalue")
    if not isinstance(datavalue, dict):
        return None
    value = datavalue.get("value")
    if isinstance(value, str):
        return value
    return None


def _validate_page(limit: int, offset: int) -> None:
    if not 1 <= limit <= 50 or offset < 0:
        raise ValueError("Limit must be 1-50 and offset must be nonnegative")

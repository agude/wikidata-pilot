"""Read-only Wikidata API access and candidate searches."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import httpx

API = "https://www.wikidata.org/w/api.php"


class WikidataClient:
    """Small read-only client for item inspection and entity search."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            timeout=20, headers={"User-Agent": "wikidata-pilot/0.1"}
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> WikidataClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def request(self, params: dict[str, str]) -> dict[str, object]:
        response = self.client.get(API, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or "error" in payload:
            raise ValueError(f"Wikidata API returned an error: {payload}")
        return payload

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
        self, query: str, *, entity_type: str = "item", limit: int = 10, offset: int = 0
    ) -> dict[str, Any]:
        """Search names and aliases with an explicit continuation offset."""
        _validate_page(limit, offset)
        if entity_type not in {"item", "property"} or not query.strip():
            raise ValueError("Supply a nonempty query and type item or property")
        payload = self.request(
            {
                "action": "wbsearchentities",
                "search": query,
                "type": entity_type,
                "language": "en",
                "format": "json",
                "limit": str(limit),
                "continue": str(offset),
            }
        )
        results = payload.get("search")
        if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
            raise ValueError("Wikidata search response has no result list")
        continuation = payload.get("search-continue")
        if continuation is not None and (
            not isinstance(continuation, int) or continuation <= offset
        ):
            raise ValueError("Wikidata search continuation is malformed")
        return {
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

    def linked(
        self, qid: str, property_id: str, *, limit: int = 50, offset: int = 0
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
        return self._item_query(query, limit, offset)

    def identifier(
        self, property_id: str, value: str, *, limit: int = 10, offset: int = 0
    ) -> dict[str, Any]:
        """Find exact string or external-identifier statements."""
        _validate_page(limit, offset)
        if not re.fullmatch(r"P[1-9][0-9]*", property_id) or not value.strip():
            raise ValueError("Supply a Wikidata property ID and nonempty identifier value")
        query = (
            "SELECT DISTINCT ?item ?itemLabel ?itemDescription WHERE { "
            f"?item wdt:{property_id} {json_literal(value)}. "
            "SERVICE wikibase:label { bd:serviceParam wikibase:language 'en'. } "
            f"}} ORDER BY ?item LIMIT {limit + 1} OFFSET {offset}"
        )
        return self._item_query(query, limit, offset)

    def ancestors(
        self, qid: str, *, instance_of: bool = False, limit: int = 50, offset: int = 0
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
        return self._item_query(query, limit, offset)

    def _item_query(self, query: str, limit: int, offset: int) -> dict[str, Any]:
        response = self.client.get(
            "https://query.wikidata.org/sparql",
            params={"query": query, "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
        )
        response.raise_for_status()
        payload = response.json()
        try:
            bindings = payload["results"]["bindings"]
            if not isinstance(bindings, list):
                raise ValueError("Wikidata query bindings are malformed")
            results = [
                {
                    "id": row["item"]["value"].rsplit("/", 1)[-1],
                    "label": row.get("itemLabel", {}).get("value", ""),
                    "description": row.get("itemDescription", {}).get("value", ""),
                }
                for row in bindings[:limit]
            ]
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError("Wikidata query response is malformed") from error
        return {
            "results": results,
            "next_offset": offset + limit if len(bindings) > limit else None,
        }

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


def json_literal(value: str) -> str:
    """Quote a safe SPARQL string literal."""
    import json

    return json.dumps(value)


def _validate_page(limit: int, offset: int) -> None:
    if not 1 <= limit <= 50 or offset < 0:
        raise ValueError("Limit must be 1-50 and offset must be nonnegative")

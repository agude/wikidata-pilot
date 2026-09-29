"""Read-only Wikidata API access and candidate searches."""

from __future__ import annotations

import re

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
        if not re.fullmatch(r"Q[1-9][0-9]*", qid):
            raise ValueError("Expected a Wikidata QID")
        payload = self.request(
            {
                "action": "wbgetentities",
                "ids": qid,
                "format": "json",
                "props": "labels|descriptions|claims|sitelinks",
            }
        )
        entities = payload.get("entities")
        if not isinstance(entities, dict) or not entities:
            raise ValueError(f"Wikidata did not return item {qid}")
        if any(not isinstance(item, dict) or "missing" in item for item in entities.values()):
            raise ValueError(f"Wikidata item {qid} is missing")
        return payload

    def search(self, query: str) -> list[dict[str, str]]:
        payload = self.request(
            {
                "action": "wbsearchentities",
                "search": query,
                "language": "en",
                "format": "json",
                "limit": "10",
            }
        )
        results = payload.get("search", [])
        if not isinstance(results, list):
            raise ValueError("Wikidata search response has no result list")
        return [
            {
                key: str(value)
                for key, value in item.items()
                if key in {"id", "label", "description"}
            }
            for item in results
            if isinstance(item, dict)
        ]

    def search_identifier(self, property_id: str, identifier: str) -> list[dict[str, str]]:
        """Find exact property values with Wikidata Query Service."""
        if not re.fullmatch(r"P[1-9][0-9]*", property_id):
            raise ValueError("Expected a Wikidata property ID")
        query = (
            "SELECT ?item ?itemLabel WHERE { ?item wdt:"
            f"{property_id} {json_literal(identifier)}. "
            "SERVICE wikibase:label { bd:serviceParam wikibase:language 'en'. } } LIMIT 20"
        )
        response = self.client.get(
            "https://query.wikidata.org/sparql",
            params={"query": query, "format": "json"},
            headers={"Accept": "application/sparql+json"},
        )
        response.raise_for_status()
        results = response.json()["results"]["bindings"]
        return [
            {
                "id": row["item"]["value"].rsplit("/", 1)[-1],
                "label": row.get("itemLabel", {}).get("value", ""),
            }
            for row in results
        ]


def json_literal(value: str) -> str:
    """Quote a safe SPARQL string literal."""
    import json

    return json.dumps(value)

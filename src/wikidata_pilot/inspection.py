"""Compact API records that retain statement meaning and evidence."""

from __future__ import annotations

from typing import Any

from .cache import IdCache


def summarize_entity(
    payload: dict[str, object], cache: IdCache, properties: list[str] | None = None
) -> dict[str, Any]:
    """Remove API scaffolding, preserving ranks, qualifiers, and references."""
    entities = payload.get("entities")
    if not isinstance(entities, dict) or not entities:
        raise ValueError("Wikidata response has no entity")
    if len(entities) != 1:
        raise ValueError("Expected exactly one entity for inspection")
    identifier, entity = next(iter(entities.items()))
    if not isinstance(entity, dict) or "missing" in entity:
        raise ValueError("Wikidata entity is unavailable")
    result: dict[str, Any] = {
        "id": entity.get("id", identifier),
        "label": entity.get("labels", {}).get("en", {}).get("value", ""),
        "description": entity.get("descriptions", {}).get("en", {}).get("value", ""),
        "claims": {},
    }
    for key in ("datatype", "lastrevid", "modified"):
        if key in entity:
            result[key] = entity[key]
    aliases = entity.get("aliases", {}).get("en", [])
    if aliases:
        result["aliases"] = [alias["value"] for alias in aliases]
    claims = entity.get("claims", {})
    if not isinstance(claims, dict):
        raise ValueError("Wikidata claims are malformed")
    selected = properties if properties is not None else claims
    for property_id in selected:
        statements = claims.get(property_id, [])
        if not isinstance(statements, list):
            raise ValueError("Wikidata statement list is malformed")
        entry = cache.entries.get(property_id)
        result["claims"][property_id] = {
            "label": entry.label if entry else property_id,
            "statements": [_statement(statement, cache) for statement in statements],
        }
    return result


def _statement(statement: dict[str, Any], cache: IdCache) -> dict[str, Any]:
    if not isinstance(statement, dict) or not isinstance(statement.get("mainsnak"), dict):
        raise ValueError("Wikidata statement is malformed")
    result = _snak(statement["mainsnak"], cache)
    for key in ("id", "rank"):
        if key in statement:
            result[key] = statement[key]
    if statement.get("qualifiers"):
        result["qualifiers"] = _snaks(statement["qualifiers"], cache)
    if statement.get("references"):
        result["references"] = [
            _snaks(reference["snaks"], cache) for reference in statement["references"]
        ]
    return result


def _snaks(snaks: dict[str, list[dict[str, Any]]], cache: IdCache) -> dict[str, Any]:
    return {key: [_snak(snak, cache) for snak in values] for key, values in snaks.items()}


def _snak(snak: dict[str, Any], cache: IdCache) -> dict[str, Any]:
    kind = snak.get("snaktype", "value")
    if kind != "value":
        return {"snaktype": kind}
    try:
        value = snak["datavalue"]["value"]
    except (KeyError, TypeError) as error:
        raise ValueError("Wikidata statement value is malformed") from error
    if isinstance(value, dict) and "id" in value:
        identifier = value["id"]
        entry = cache.entries.get(identifier)
        value = {"id": identifier}
        if entry and entry.label:
            value["label"] = entry.label
    result = {"value": value}
    if "datatype" in snak:
        result["datatype"] = snak["datatype"]
    return result

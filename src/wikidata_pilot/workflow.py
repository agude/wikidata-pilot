"""Validation, deterministic plans, and staged QuickStatements export."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from .models import Candidate, Case, parse_time

SAFE_QS_TEXT = re.compile(r'^[^\x00-\x1f\x7f|"<>]*$')


def validate_case(case: Case, *, allow_staged_dependencies: bool = True) -> list[str]:
    """Return actionable evidence, dependency, and resolution errors."""
    errors: list[str] = []
    entities = {entity.key: entity for entity in case.entities}
    source_ids = {source.id for source in case.sources}
    for source in case.sources:
        if source.verification != "verified":
            errors.append(f"Source {source.id} is illustrative_unverified; verify it before export")
        if not SAFE_QS_TEXT.fullmatch(str(source.url)):
            errors.append(f"Source {source.id} URL contains unsafe QuickStatements text")
    for entity in case.entities:
        if entity.resolution.status == "unresolved":
            errors.append(
                f"Entity {entity.key} is unresolved; choose existing QID or explicitly create"
            )
        if entity.resolution.status == "existing" and not entity.resolution.qid:
            errors.append(f"Entity {entity.key} is marked existing without a QID")
        for text in (entity.label, entity.description):
            if not SAFE_QS_TEXT.fullmatch(text):
                errors.append(
                    f"Entity {entity.key} label or description contains unsafe QuickStatements text"
                )
        for claim in entity.claims:
            if not claim.sources or any(source_id not in source_ids for source_id in claim.sources):
                errors.append(f"Claim {entity.key}.{claim.id} refers to missing or no source")
            item_values = [claim.value] if claim.datatype == "item" else []
            item_values.extend(q.value for q in claim.qualifiers if q.datatype == "item")
            for value in item_values:
                if re.fullmatch(r"Q[1-9][0-9]*", value):
                    continue
                target = entities.get(value)
                if target is None:
                    errors.append(
                        f"Claim {entity.key}.{claim.id} refers to unknown local entity {value}"
                    )
                elif target.resolution.status != "existing" and not (
                    allow_staged_dependencies and target.resolution.status == "create"
                ):
                    errors.append(
                        f"Claim {entity.key}.{claim.id} depends on {value}; stage creation, record its QID, then export again"
                    )
            for text in (claim.value, *(qualifier.value for qualifier in claim.qualifiers)):
                if not SAFE_QS_TEXT.fullmatch(text):
                    errors.append(
                        f"Claim {entity.key}.{claim.id} contains text unsafe for QuickStatements"
                    )
    return errors


def match_case(case: Case, client: Any) -> tuple[Case, list[dict[str, object]]]:
    """Search external identifier owners first, then title and author candidates."""
    report: list[dict[str, object]] = []
    for entity in case.entities:
        if entity.resolution.status != "unresolved":
            continue
        candidate_info: dict[str, tuple[str, str | None, list[str]]] = {}
        for prop, identifier in entity.identifiers.items():
            results = client.search_identifier(prop, identifier)
            for result in results:
                _record_candidate(candidate_info, result, prop)
        titles = list(dict.fromkeys([entity.title or entity.label, *entity.alternate_titles]))
        queries = titles.copy()
        queries.extend(f"{title} {author}" for title in titles for author in entity.authors)
        for query in queries:
            for result in client.search(query):
                _record_candidate(candidate_info, result, query)
        entity.resolution.candidates = [
            Candidate(qid=qid, label=label, description=description, matched_by=queries)
            for qid, (label, description, queries) in candidate_info.items()
        ]
        report.append(
            {
                "entity": entity.key,
                "candidates": [c.model_dump() for c in entity.resolution.candidates],
                "no_result_means_no_item": False,
            }
        )
    return case, report


def _record_candidate(
    candidates: dict[str, tuple[str, str | None, list[str]]],
    result: dict[str, str],
    query: str,
) -> None:
    qid = result["id"]
    if qid not in candidates:
        candidates[qid] = (result.get("label", ""), result.get("description"), [])
    candidates[qid][2].append(query)


def render_plan(case: Case, snapshot: dict[str, object] | None = None) -> str:
    """Render before/after review with proposals and unresolved entities."""
    rows = [
        f"# Review plan: {case.title}",
        "",
        "This plan proposes edits only. Verify every source and item before export.",
        "",
        "## Entities",
        "",
    ]
    for entity in case.entities:
        current = (
            entity.resolution.qid
            if entity.resolution.status == "existing"
            else "new / not yet created"
        )
        rows.extend(
            [
                f"### {entity.key}: {entity.label}",
                "",
                f"Current item: {current}",
                f"Decision: {entity.resolution.status}; {entity.resolution.reason or 'no decision recorded'}",
                "",
                "| Property | Current claim snapshot | Proposed claim | Evidence |",
                "|---|---|---|---|",
            ]
        )
        for claim in entity.claims:
            evidence = ", ".join(claim.sources)
            before = "(live snapshot not captured)"
            if snapshot and entity.key in snapshot:
                before = _snapshot_claims(snapshot[entity.key], claim.property)
            proposed = claim.value
            if claim.datatype == "item":
                local_target = next(
                    (item for item in case.entities if item.key == claim.value), None
                )
                if local_target:
                    proposed = local_target.resolution.qid or (
                        f"{claim.value} (deferred until created)"
                        if local_target.resolution.status == "create"
                        else f"{claim.value} (unresolved)"
                    )
            if claim.qualifiers:
                qualifier_text = "; ".join(
                    f"{item.property}={item.value}" for item in claim.qualifiers
                )
                proposed += f" (qualifiers: {qualifier_text})"
            if claim.language:
                proposed = f"{claim.language}: {proposed}"
            if claim.precision:
                proposed += f" ({claim.precision} precision)"
            rows.append(
                f"| {claim.property} | {_table_text(before)} | {_table_text(proposed)} | {evidence} |"
            )
        if not entity.claims:
            rows.append("| — | — | no claims proposed | — |")
        if entity.resolution.candidates:
            rows.extend(["", "Candidates requiring human decision:"])
            rows.extend(
                f"- {c.qid}: {c.label} ({', '.join(c.matched_by)})"
                for c in entity.resolution.candidates
            )
        rows.append("")
    rows.extend(["## Sources", ""])
    for source in case.sources:
        rows.append(
            f"- {source.id}: {source.url} (retrieved {source.retrieved}; "
            f"{source.verification}; locator: {source.locator or 'not specified'}). "
            f"Excerpt: {source.excerpt}"
        )
    return "\n".join(rows)


def _table_text(value: str) -> str:
    return value.replace("|", "&#124;").replace("\n", "<br>").replace("\r", "")


def _snapshot_claims(payload: object, property_id: str) -> str:
    """Summarize one property's current values from the item API response."""
    if not isinstance(payload, dict):
        return "item unavailable"
    entities = payload.get("entities", {})
    if not isinstance(entities, dict) or not entities:
        return "item unavailable"
    item = next(iter(entities.values()))
    if not isinstance(item, dict):
        return "item unavailable"
    claims = item.get("claims", {})
    if not isinstance(claims, dict):
        return "no current value"
    values: list[str] = []
    statements = claims.get(property_id, [])
    if isinstance(statements, list):
        for statement in statements:
            try:
                values.append(str(statement["mainsnak"]["datavalue"]["value"]))
            except (KeyError, TypeError):
                continue
    return "; ".join(values) if values else "no current value"


def live_snapshot(case: Case, client: Any) -> dict[str, object]:
    """Fetch current data for resolved items for before/after review."""
    return {
        entity.key: client.inspect(entity.resolution.qid)
        for entity in case.entities
        if entity.resolution.qid
    }


def export_case(case: Case) -> str:
    """Build staged QuickStatements through quickstatements-client models."""
    errors = validate_case(case, allow_staged_dependencies=True)
    if errors:
        raise ValueError("Cannot export:\n- " + "\n- ".join(errors))
    from quickstatements_client import (
        CreateLine,
        DateLine,
        DateQualifier,
        EntityLine,
        EntityQualifier,
        TextLine,
        TextQualifier,
    )

    lines: list[str] = []
    entities = {entity.key: entity for entity in case.entities}
    for entity in case.entities:
        resolution = entity.resolution
        if resolution.status == "unresolved":
            raise ValueError(f"Cannot export unresolved entity {entity.key}")
        if resolution.status == "create":
            # Create shell entities first. Relationships to another new entity wait
            # until the user records the returned QID and exports again.
            lines.append(CreateLine().get_line())
            target = "LAST"
            lines.append(TextLine(subject=target, predicate="Len", target=entity.label).get_line())
            lines.append(
                TextLine(subject=target, predicate="Den", target=entity.description).get_line()
            )
        else:
            target = resolution.qid or ""
        for claim in entity.claims:
            referenced_keys = [claim.value] if claim.datatype == "item" else []
            referenced_keys.extend(q.value for q in claim.qualifiers if q.datatype == "item")
            if any(
                key in entities and entities[key].resolution.status == "create"
                for key in referenced_keys
            ):
                continue
            if claim.datatype not in {"item", "string", "external-id", "time", "monolingualtext"}:
                raise ValueError(
                    f"{entity.key}.{claim.id}: export does not support {claim.datatype}"
                )
            target_value: str | date = claim.value
            claim_value = ""
            if claim.datatype == "item":
                if claim.value in {item.key for item in case.entities}:
                    target_entity = next(item for item in case.entities if item.key == claim.value)
                    if target_entity.resolution.status != "existing":
                        continue
                    claim_value = target_entity.resolution.qid or ""
                else:
                    claim_value = claim.value
                statement_type = "item"
            else:
                if not SAFE_QS_TEXT.fullmatch(claim.value):
                    raise ValueError(f"Unsafe value in {entity.key}.{claim.id}")
                if claim.datatype == "time":
                    claim_date = _date_value(claim.value, claim.precision or "day")
                    precisions = {"year": 9, "month": 10, "day": 11}
                    statement_type = "time"
                    target_value = claim_date
                else:
                    statement_type = "text"
                    target_value = claim.value
            for source_id in claim.sources:
                source = next(src for src in case.sources if src.id == source_id)
                if source.verification != "verified":
                    raise ValueError(f"Source {source_id} is not verified")
                qualifiers: list[EntityQualifier | DateQualifier | TextQualifier] = []
                for qualifier in claim.qualifiers:
                    if qualifier.datatype == "item":
                        qualifier_value = qualifier.value
                        if qualifier_value in entities:
                            qualifier_value = entities[qualifier_value].resolution.qid or ""
                        qualifiers.append(
                            EntityQualifier(predicate=qualifier.property, target=qualifier_value)
                        )
                    elif qualifier.datatype == "time":
                        qualifiers.append(
                            DateQualifier(
                                predicate=qualifier.property,
                                target=_quickstatements_date(
                                    qualifier.value, qualifier.precision or "day"
                                ),
                            )
                        )
                    else:
                        qualifiers.append(
                            TextQualifier(predicate=qualifier.property, target=qualifier.value)
                        )
                qualifiers.extend(
                    [
                        TextQualifier(predicate="S854", target=str(source.url)),
                        DateQualifier(
                            predicate="S813", target=f"+{source.retrieved.isoformat()}T00:00:00Z/11"
                        ),
                    ]
                )
                if statement_type == "item":
                    statement: EntityLine | DateLine | TextLine = EntityLine(
                        subject=target,
                        predicate=claim.property,
                        target=claim_value,
                        qualifiers=qualifiers,
                    )
                elif statement_type == "time":
                    if not isinstance(target_value, date):
                        raise ValueError(f"Invalid time value for {entity.key}.{claim.id}")
                    statement = DateLine(
                        subject=target,
                        predicate=claim.property,
                        target=target_value,
                        precision=precisions[claim.precision or "day"],
                        qualifiers=qualifiers,
                    )
                else:
                    if not isinstance(target_value, str):
                        raise ValueError(f"Invalid text value for {entity.key}.{claim.id}")
                    statement = TextLine(
                        subject=target,
                        predicate=claim.property,
                        target=target_value,
                        qualifiers=qualifiers,
                    )
                rendered = statement.get_line()
                if claim.datatype == "monolingualtext":
                    rendered = rendered.replace(
                        f'"{claim.value}"', f'{claim.language}:"{claim.value}"', 1
                    )
                lines.append(rendered)
    return "\n".join(lines) + ("\n" if lines else "")


def deferred_claims(case: Case) -> list[str]:
    """List relationship claims held until their new targets have QIDs."""
    created_keys = {entity.key for entity in case.entities if entity.resolution.status == "create"}
    return [
        f"{entity.key}.{claim.id} -> {claim.value}"
        for entity in case.entities
        for claim in entity.claims
        if (claim.datatype == "item" and claim.value in created_keys)
        or any(q.datatype == "item" and q.value in created_keys for q in claim.qualifiers)
    ]


def write_plan(path: Path, case: Case) -> None:
    path.write_text(render_plan(case), encoding="utf-8")


def write_proposal_json(path: Path, case: Case, snapshot: dict[str, object] | None = None) -> None:
    payload = {
        "case": case.model_dump(mode="json"),
        "snapshot": snapshot or {},
        "generated": date.today().isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _date_value(value: str, precision: str) -> date:
    """Parse supported ISO date precision without inventing a value."""
    return parse_time(value, precision)


def _quickstatements_date(value: str, precision: str) -> str:
    date_value = _date_value(value, precision)
    precision_number = {"year": 9, "month": 10, "day": 11}[precision]
    return f"+{date_value.year:04}-{date_value.month:02}-{date_value.day:02}T00:00:00Z/{precision_number}"

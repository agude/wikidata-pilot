"""Reconcile QuickStatements creation results with a research case."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Case, Entity, Resolution

REPORT_CREATION = re.compile(
    r"\bN\s+(?P<label>.+?)\s+\((?P<qid>Q[1-9][0-9]*)\).*?"
    r"Created a new Item:\s*QuickStatements 3\.0 batch #(?P<batch>[0-9]+)\b"
)
QS_CREATION_LABEL = re.compile(r'LAST\|Len\|"([^"\r\n]*)"')


@dataclass(frozen=True)
class ReturnedItem:
    label: str
    qid: str
    batch_id: str
    line_number: int


@dataclass(frozen=True)
class QidAssignment:
    key: str
    label: str
    qid: str
    already_recorded: bool


@dataclass(frozen=True)
class QidImportPlan:
    batch_id: str
    assignments: tuple[QidAssignment, ...]
    pending_keys: tuple[str, ...]
    unrepresented_items: tuple[ReturnedItem, ...]


def plan_qid_import(
    case: Case,
    report: str,
    quickstatements: str,
    *,
    allow_unrepresented: bool = False,
) -> QidImportPlan:
    """Match creation report rows to unique case entities in the submitted QS batch."""
    returned_items = _parse_report(report)
    batch_ids = {item.batch_id for item in returned_items}
    if len(batch_ids) != 1:
        raise ValueError("The report must contain creation results from exactly one batch")
    batch_id = next(iter(batch_ids))

    creation_labels = _parse_quickstatements_creations(quickstatements)
    labels_in_batch = set(creation_labels)
    if len(labels_in_batch) != len(creation_labels):
        raise ValueError("The submitted QS batch contains duplicate created-item labels")

    entities_by_label: dict[str, list[Entity]] = {}
    for entity in case.entities:
        entities_by_label.setdefault(entity.label, []).append(entity)

    _validate_batch_entities(
        creation_labels, entities_by_label, allow_unrepresented=allow_unrepresented
    )
    assignments: list[QidAssignment] = []
    unrepresented_items: list[ReturnedItem] = []
    report_labels: set[str] = set()
    report_qids: dict[str, str] = {}
    for item in returned_items:
        if item.label in report_labels:
            raise ValueError(f"The report repeats a creation result for {item.label!r}")
        report_labels.add(item.label)
        if item.qid in report_qids and report_qids[item.qid] != item.label:
            raise ValueError(f"The report assigns {item.qid} to more than one label")
        report_qids[item.qid] = item.label

        if item.label not in labels_in_batch:
            raise ValueError(
                f"Report line {item.line_number} names {item.label!r}, which is not created "
                "by the supplied QS batch"
            )
        matches = entities_by_label.get(item.label, [])
        if not matches and allow_unrepresented:
            unrepresented_items.append(item)
            continue
        if len(matches) != 1:
            raise ValueError(f"Case label {item.label!r} does not identify exactly one entity")
        entity = matches[0]
        resolution = entity.resolution
        if resolution.status == "create":
            already_recorded = False
        elif resolution.status == "existing" and resolution.qid == item.qid:
            already_recorded = True
        elif resolution.status == "existing":
            raise ValueError(
                f"{entity.key} already has QID {resolution.qid}, but the report returns {item.qid}"
            )
        else:
            raise ValueError(
                f"{entity.key} is {resolution.status}, not marked create or already recorded"
            )
        assignments.append(
            QidAssignment(
                key=entity.key,
                label=entity.label,
                qid=item.qid,
                already_recorded=already_recorded,
            )
        )

    assigned_qids = {assignment.qid: assignment.key for assignment in assignments}
    for entity in case.entities:
        existing_qid = entity.resolution.qid
        if existing_qid in assigned_qids and assigned_qids[existing_qid] != entity.key:
            raise ValueError(
                f"{existing_qid} is already assigned to case entity {assigned_qids[existing_qid]}"
            )

    pending_keys = tuple(
        entity.key
        for label in creation_labels
        if label not in report_labels
        for entity in entities_by_label[label]
        if entity.resolution.status == "create"
    )
    return QidImportPlan(
        batch_id=batch_id,
        assignments=tuple(assignments),
        pending_keys=pending_keys,
        unrepresented_items=tuple(unrepresented_items),
    )


def apply_qid_import(case: Case, plan: QidImportPlan, report_name: str) -> int:
    """Record the matched QIDs while preserving each create rationale."""
    entities = {entity.key: entity for entity in case.entities}
    updated_count = 0
    for assignment in plan.assignments:
        if assignment.already_recorded:
            continue
        entity = entities[assignment.key]
        previous_reason = entity.resolution.reason or ""
        reason = (
            f"Created in QuickStatements 3.0 batch #{plan.batch_id}; "
            f"recorded from {report_name}. Previous create decision: {previous_reason}"
        )
        entity.resolution = Resolution(
            status="existing",
            qid=assignment.qid,
            reason=reason,
            candidates=entity.resolution.candidates,
        )
        updated_count += 1
    return updated_count


def render_qid_import_plan(case: Case, plan: QidImportPlan) -> str:
    """Format a human-readable preview of returned and missing QIDs."""
    lines = [f"QuickStatements batch #{plan.batch_id}: {len(plan.assignments)} result(s) matched."]
    for assignment in plan.assignments:
        status = "already recorded" if assignment.already_recorded else "will record"
        lines.append(f"{assignment.key}: {assignment.label} → {assignment.qid} ({status})")
    if plan.pending_keys:
        entities = {entity.key: entity for entity in case.entities}
        lines.append("Not returned; remain marked create:")
        lines.extend(f"{key}: {entities[key].label}" for key in plan.pending_keys)
    if plan.unrepresented_items:
        lines.append("In the submitted batch but not represented in this case; skipped:")
        lines.extend(f"{item.label} → {item.qid}" for item in plan.unrepresented_items)
    return "\n".join(lines)


def _parse_report(report: str) -> list[ReturnedItem]:
    returned_items: list[ReturnedItem] = []
    for line_number, line in enumerate(report.splitlines(), start=1):
        if "Created a new Item" not in line:
            continue
        match = REPORT_CREATION.search(line)
        if match is None:
            raise ValueError(
                f"Could not parse created-item result on report line {line_number}; "
                "expected a Wikidata history line with an item label, QID, and "
                "QuickStatements 3.0 batch number"
            )
        returned_items.append(
            ReturnedItem(
                label=match.group("label"),
                qid=match.group("qid"),
                batch_id=match.group("batch"),
                line_number=line_number,
            )
        )
    if not returned_items:
        raise ValueError("No created-item results found in the report")
    return returned_items


def _parse_quickstatements_creations(quickstatements: str) -> list[str]:
    lines = quickstatements.splitlines()
    labels: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() != "CREATE":
            index += 1
            continue
        index += 1
        if index >= len(lines):
            raise ValueError("The submitted QS batch ends after a CREATE command")
        match = QS_CREATION_LABEL.fullmatch(lines[index])
        if match is None:
            raise ValueError('Each CREATE command must be followed by LAST|Len|"label"')
        labels.append(match.group(1))
        index += 1
    if not labels:
        raise ValueError("The submitted QS batch contains no CREATE commands")
    return labels


def _validate_batch_entities(
    creation_labels: list[str],
    entities_by_label: dict[str, list[Entity]],
    *,
    allow_unrepresented: bool,
) -> None:
    for label in creation_labels:
        matches = entities_by_label.get(label, [])
        if not matches and allow_unrepresented:
            continue
        if len(matches) != 1:
            raise ValueError(f"QS label {label!r} does not identify exactly one case entity")
        status = matches[0].resolution.status
        if status not in {"create", "existing"}:
            raise ValueError(f"QS label {label!r} maps to entity marked {status}")

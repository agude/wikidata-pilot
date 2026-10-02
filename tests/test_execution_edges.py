"""Regression coverage for partial creation-result imports."""

from wikidata_pilot.execution import plan_qid_import
from wikidata_pilot.models import Case, Entity, Resolution


def _entity(key: str, label: str) -> Entity:
    return Entity(
        key=key,
        kind="work",
        label=label,
        description="test work",
        resolution=Resolution(status="create", reason="reviewed"),
    )


def test_partial_import_skips_unrepresented_pending_label() -> None:
    case = Case(
        title="Partial import",
        sources=[],
        entities=[_entity("returned", "Returned"), _entity("pending", "Pending")],
    )
    report = (
        "N Returned (Q10) https://www.wikidata.org/wiki/Special:NewItem "
        "Created a new Item: QuickStatements 3.0 batch #42\n"
        "N Outside case (Q11) https://www.wikidata.org/wiki/Special:NewItem "
        "Created a new Item: QuickStatements 3.0 batch #42"
    )
    quickstatements = "\n".join(
        f'CREATE\nLAST|Len|"{label}"'
        for label in ("Returned", "Pending", "Outside case", "Outside pending")
    )

    plan = plan_qid_import(
        case,
        report,
        quickstatements,
        allow_unrepresented=True,
    )

    assert [(item.key, item.qid) for item in plan.assignments] == [("returned", "Q10")]
    assert plan.pending_keys == ("pending",)
    assert [(item.label, item.qid) for item in plan.unrepresented_items] == [
        ("Outside case", "Q11")
    ]

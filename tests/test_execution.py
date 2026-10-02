"""Tests for recording returned QuickStatements item IDs."""

from pathlib import Path
from typing import Literal

import pytest

from wikidata_pilot import cli
from wikidata_pilot.execution import (
    apply_qid_import,
    plan_qid_import,
    render_qid_import_plan,
)
from wikidata_pilot.models import Candidate, Case, Entity, Resolution


def entity(
    key: str,
    label: str,
    *,
    status: Literal["create", "existing", "unresolved"] = "create",
    qid: str | None = None,
) -> Entity:
    return Entity(
        key=key,
        kind="work",
        label=label,
        description="test work",
        resolution=Resolution(
            status=status,
            qid=qid,
            reason="reviewed identity decision" if status != "unresolved" else None,
        ),
    )


def case_with(*entities: Entity) -> Case:
    return Case(title="QID import", sources=[], entities=list(entities))


def result(label: str, qid: str, batch: str = "42") -> str:
    return (
        f"N {label} ({qid}) https://www.wikidata.org/wiki/Special:NewItem "
        f"Created a new Item: QuickStatements 3.0 batch #{batch}"
    )


def creation(*labels: str) -> str:
    return "\n".join(f'CREATE\nLAST|Len|"{label}"' for label in labels)


def test_plan_apply_and_render_qid_import() -> None:
    story = entity("story", "Story")
    story.resolution.candidates = [Candidate(qid="Q9", label="Possible story")]
    anthology = entity("anthology", "Anthology")
    author = entity("author", "Author", status="existing", qid="Q20")
    example = case_with(story, anthology, author)
    report = "\n".join([result("Story", "Q10"), result("Author", "Q20")])

    plan = plan_qid_import(
        example,
        report,
        creation("Story", "Anthology", "Author"),
    )

    assert plan.batch_id == "42"
    assert [(item.key, item.qid, item.already_recorded) for item in plan.assignments] == [
        ("story", "Q10", False),
        ("author", "Q20", True),
    ]
    assert plan.pending_keys == ("anthology",)
    assert plan.unrepresented_items == ()
    preview = render_qid_import_plan(example, plan)
    assert "QuickStatements batch #42: 2 result(s) matched." in preview
    assert "story: Story → Q10 (will record)" in preview
    assert "author: Author → Q20 (already recorded)" in preview
    assert "anthology: Anthology" in preview

    assert apply_qid_import(example, plan, "results.txt") == 1
    assert story.resolution.status == "existing"
    assert story.resolution.qid == "Q10"
    assert story.resolution.candidates == [Candidate(qid="Q9", label="Possible story")]
    assert story.resolution.reason is not None
    assert "Previous create decision: reviewed identity decision" in story.resolution.reason
    assert author.resolution.qid == "Q20"
    recorded_plan = plan_qid_import(
        example,
        report,
        creation("Story", "Anthology", "Author"),
    )
    assert apply_qid_import(example, recorded_plan, "results.txt") == 0


def test_partial_import_reports_unrepresented_and_pending_items() -> None:
    example = case_with(entity("story", "Story"), entity("collection", "Collection"))
    report = "\n".join([result("Story", "Q10"), result("Outside case", "Q11")])
    plan = plan_qid_import(
        example,
        report,
        creation("Story", "Outside case", "Collection"),
        allow_unrepresented=True,
    )

    assert plan.pending_keys == ("collection",)
    assert [(item.label, item.qid) for item in plan.unrepresented_items] == [
        ("Outside case", "Q11")
    ]
    preview = render_qid_import_plan(example, plan)
    assert "In the submitted batch but not represented in this case; skipped:" in preview
    assert "Outside case → Q11" in preview


@pytest.mark.parametrize(
    ("report", "message"),
    [
        ("No creation rows here", "No created-item results"),
        ("Created a new Item but malformed", "Could not parse created-item result"),
    ],
)
def test_invalid_creation_report_rows_fail(report: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        plan_qid_import(case_with(entity("story", "Story")), report, creation("Story"))


def test_report_must_contain_exactly_one_batch() -> None:
    report = "\n".join([result("Story", "Q10", "42"), result("Book", "Q11", "43")])
    example = case_with(entity("story", "Story"), entity("book", "Book"))
    with pytest.raises(ValueError, match="exactly one batch"):
        plan_qid_import(example, report, creation("Story", "Book"))


@pytest.mark.parametrize(
    ("report", "message"),
    [
        (
            "\n".join([result("Story", "Q10"), result("Story", "Q11")]),
            "repeats a creation result",
        ),
        (
            "\n".join([result("Story", "Q10"), result("Book", "Q10")]),
            "assigns Q10 to more than one label",
        ),
    ],
)
def test_duplicate_report_results_fail(report: str, message: str) -> None:
    example = case_with(entity("story", "Story"), entity("book", "Book"))
    with pytest.raises(ValueError, match=message):
        plan_qid_import(example, report, creation("Story", "Book"))


def test_report_label_must_be_created_by_submitted_batch() -> None:
    with pytest.raises(ValueError, match="is not created by the supplied QS batch"):
        plan_qid_import(
            case_with(entity("story", "Story")),
            result("Other", "Q10"),
            creation("Story"),
            allow_unrepresented=True,
        )


@pytest.mark.parametrize(
    ("quickstatements", "message"),
    [
        (creation("Story", "Story"), "duplicate created-item labels"),
        ("Q1|P50|Q2", "contains no CREATE commands"),
        ("CREATE", "ends after a CREATE command"),
        ("CREATE\nQ1|P50|Q2", "must be followed by LAST\\|Len\\|"),
    ],
)
def test_invalid_submitted_quickstatements_fail(quickstatements: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        plan_qid_import(
            case_with(entity("story", "Story")),
            result("Story", "Q10"),
            quickstatements,
        )


@pytest.mark.parametrize(
    ("entities", "allow_unrepresented", "message"),
    [
        ((), False, "does not identify exactly one case entity"),
        (
            (entity("story", "Story"), entity("story-copy", "Story")),
            False,
            "does not identify exactly one case entity",
        ),
        (
            (entity("story", "Story", status="unresolved"),),
            False,
            "maps to entity marked unresolved",
        ),
    ],
)
def test_batch_labels_must_map_to_valid_case_entities(
    entities: tuple[Entity, ...], allow_unrepresented: bool, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        plan_qid_import(
            case_with(*entities),
            result("Story", "Q10"),
            creation("Story"),
            allow_unrepresented=allow_unrepresented,
        )


def test_existing_qid_mismatch_fails() -> None:
    example = case_with(entity("story", "Story", status="existing", qid="Q8"))
    with pytest.raises(ValueError, match="already has QID Q8, but the report returns Q10"):
        plan_qid_import(example, result("Story", "Q10"), creation("Story"))


def test_returned_qid_cannot_already_belong_to_another_entity() -> None:
    example = case_with(
        entity("story", "Story"),
        entity("another-story", "Another story", status="existing", qid="Q10"),
    )
    with pytest.raises(ValueError, match="Q10 is already assigned to case entity story"):
        plan_qid_import(example, result("Story", "Q10"), creation("Story"))


def test_record_qids_cli_previews_applies_and_handles_noop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case_path = tmp_path / "case.json"
    report_path = tmp_path / "result.txt"
    batch_path = tmp_path / "submitted.qs"
    case_path.write_text(case_with(entity("story", "Story")).model_dump_json(), encoding="utf-8")
    report_path.write_text(result("Story", "Q10"), encoding="utf-8")
    batch_path.write_text(creation("Story"), encoding="utf-8")
    arguments = ["record-qids", str(case_path), str(report_path), "--batch", str(batch_path)]

    assert cli.main(arguments) == 0
    assert "Preview only" in capsys.readouterr().out
    assert Case.model_validate_json(case_path.read_text()).entities[0].resolution.status == "create"

    assert cli.main([*arguments, "--apply"]) == 0
    output = capsys.readouterr().out
    assert "Recorded 1 QID(s)" in output
    assert Case.model_validate_json(case_path.read_text()).entities[0].resolution.qid == "Q10"

    assert cli.main([*arguments, "--apply"]) == 0
    assert "No case changes needed" in capsys.readouterr().out


def test_record_qids_cli_rejects_path_collisions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case_path = tmp_path / "case.json"
    report_path = tmp_path / "result.txt"
    case_path.write_text(case_with(entity("story", "Story")).model_dump_json(), encoding="utf-8")
    report_path.write_text(result("Story", "Q10"), encoding="utf-8")

    assert (
        cli.main(
            [
                "record-qids",
                str(case_path),
                str(report_path),
                "--batch",
                str(case_path),
            ]
        )
        == 2
    )
    assert "must all be distinct" in capsys.readouterr().err

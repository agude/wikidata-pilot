"""Regression cases for invalid evidence, dependency resolution, and API failures."""

from pathlib import Path

import httpx
import pytest
from pydantic import HttpUrl, ValidationError

from tests.test_workflow import case, source
from wikidata_pilot import cli
from wikidata_pilot.models import Case, Claim, Entity, Qualifier, Resolution
from wikidata_pilot.wikidata import WikidataClient
from wikidata_pilot.workflow import (
    deferred_claims,
    export_case,
    match_case,
    render_plan,
    validate_case,
)


@pytest.mark.parametrize(
    "value,precision",
    [("2025-02-29", "day"), ("2025-13", "month"), ("0000", "year"), ("2025-01-extra", "month")],
)
def test_invalid_calendar_values_are_rejected(value: str, precision: str) -> None:
    with pytest.raises(ValidationError):
        Claim.model_validate(
            {
                "id": "date",
                "property": "P577",
                "datatype": "time",
                "value": value,
                "precision": precision,
                "sources": ["book"],
            }
        )
    with pytest.raises(ValidationError):
        Qualifier.model_validate(
            {"property": "P580", "datatype": "time", "value": value, "precision": precision}
        )


def test_invalid_decisions_and_identifier_properties_are_rejected() -> None:
    for data in [
        {"status": "existing", "qid": "Q0", "reason": "checked"},
        {"status": "create", "reason": " "},
        {"status": "existing", "reason": "checked"},
    ]:
        with pytest.raises(ValidationError):
            Resolution.model_validate(data)
    with pytest.raises(ValidationError, match="identifier keys"):
        Entity.model_validate(
            {
                "key": "work",
                "kind": "work",
                "label": "Work",
                "description": "work",
                "identifiers": {"bad property": "42"},
            }
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"datatype": "time", "value": "2025", "precision": None},
        {"datatype": "string", "value": "text", "language": "en"},
        {"datatype": "string", "value": "text", "precision": "year"},
        {"datatype": "monolingualtext", "value": "text", "language": None},
        {"datatype": "monolingualtext", "value": "text", "language": "bad_tag!"},
        {"datatype": "item", "value": "Q0"},
        {"datatype": "url", "value": "not a URL"},
    ],
)
def test_claim_rejects_invalid_datatype_fields(overrides: dict[str, object]) -> None:
    claim_data: dict[str, object] = {
        "id": "claim",
        "property": "P1476",
        "datatype": "string",
        "value": "text",
        "sources": ["book"],
    }
    claim_data.update(overrides)
    with pytest.raises(ValidationError):
        Claim.model_validate(claim_data)


def test_unknown_local_targets_block_export() -> None:
    example = case()
    example.entities[0].claims[0].value = "missing-target"
    assert "unknown local entity" in validate_case(example)[0]
    with pytest.raises(ValueError, match="unknown local entity"):
        export_case(example)


def test_qualifier_dependencies_are_deferred_and_resolved_without_recreation() -> None:
    example = case()
    example.entities.append(
        Entity(
            key="edition",
            kind="edition",
            label="Edition",
            description="book edition",
            resolution=Resolution(status="create", reason="checked bibliography"),
        )
    )
    example.entities[0].claims[0].qualifiers = [
        Qualifier(property="P805", datatype="item", value="edition")
    ]
    first = export_case(example)
    assert first.count("CREATE") == 1
    assert "P1433" not in first
    assert deferred_claims(example)
    assert "stage creation" in validate_case(example, allow_staged_dependencies=False)[0]
    example.entities[1].resolution = Resolution(
        status="existing", qid="Q99", reason="returned by creation batch"
    )
    second = export_case(example)
    assert "CREATE" not in second
    assert "P1433|Q2|P805|Q99" in second
    assert deferred_claims(example) == []


def test_multiple_sources_keep_distinct_references_and_qualifier_precision() -> None:
    example = case()
    second_source = source()
    second_source.id = "second"
    second_source.url = HttpUrl("https://example.org/second")
    example.sources.append(second_source)
    claim = example.entities[0].claims[0]
    claim.sources = ["book", "second"]
    claim.qualifiers = [
        Qualifier(property="P1545", datatype="string", value="2"),
        Qualifier(property="P580", datatype="time", value="1982-03", precision="month"),
    ]
    output = export_case(example)
    assert output.count('P1545|"2"|P580|+1982-03-01T00:00:00Z/10') == 2
    assert 'S854|"https://example.org/book"|S813|+2026-09-29T00:00:00Z/11' in output
    assert 'S854|"https://example.org/second"|S813|+2026-09-29T00:00:00Z/11' in output


@pytest.mark.parametrize("property_id,value", [("P2671", "/g/11test"), ("P646", "/m/test")])
def test_google_ids_omit_references_but_require_all_evidence(property_id: str, value: str) -> None:
    example = case()
    second_source = source()
    second_source.id = "second"
    example.sources.append(second_source)
    example.entities[0].claims = [
        Claim(
            id="google-id",
            property=property_id,
            datatype="external-id",
            value=value,
            sources=["book", "second"],
            qualifiers=[Qualifier(property="P1545", datatype="string", value="2")],
        )
    ]
    assert export_case(example) == f'Q1|{property_id}|"{value}"|P1545|"2"\n'
    second_source.verification = "illustrative_unverified"
    with pytest.raises(ValueError, match="illustrative_unverified"):
        export_case(example)


def test_other_external_ids_keep_references() -> None:
    example = case()
    example.entities[0].claims = [
        Claim(
            id="isbn",
            property="P212",
            datatype="external-id",
            value="9781234567890",
            sources=["book"],
        )
    ]
    assert 'S854|"https://example.org/book"|S813|+2026-09-29T00:00:00Z/11' in export_case(example)


@pytest.mark.parametrize("field", ["label", "description", "claim", "qualifier"])
@pytest.mark.parametrize("value", ['Quote "', "Pipe |", "newline\nCREATE", "tab\tCREATE"])
def test_unsafe_text_cannot_inject_commands(field: str, value: str) -> None:
    example = case()
    if field in {"label", "description"}:
        setattr(example.entities[0], field, value)
    else:
        claim = example.entities[0].claims[0]
        claim.datatype = "string"
        claim.property = "P1476"
        claim.value = "safe"
        if field == "claim":
            claim.value = value
        else:
            claim.qualifiers = [Qualifier(property="P1545", datatype="string", value=value)]
    with pytest.raises(ValueError, match="unsafe"):
        export_case(example)


def test_duplicate_case_keys_and_ids_are_rejected() -> None:
    example = case().model_dump(mode="json")
    example["sources"] *= 2
    with pytest.raises(ValidationError, match="source IDs"):
        Case.model_validate(example)
    example = case().model_dump(mode="json")
    example["entities"][0]["claims"] *= 2
    with pytest.raises(ValidationError, match="claim IDs"):
        Case.model_validate(example)
    example = case().model_dump(mode="json")
    example["entities"].append(example["entities"][0])
    with pytest.raises(ValidationError, match="entity keys"):
        Case.model_validate(example)


def test_missing_items_and_api_errors_are_not_empty_searches() -> None:
    def missing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"entities": {"Q1": {"missing": ""}}})

    with (
        httpx.Client(transport=httpx.MockTransport(missing)) as transport,
        WikidataClient(transport) as client,
    ):
        with pytest.raises(ValueError, match="missing"):
            client.inspect("Q1")
        with pytest.raises(ValueError, match="QID"):
            client.inspect("bad")
        with pytest.raises(ValueError, match="property ID"):
            client.search_identifier("bad", "42")

    def api_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": {"code": "badvalue"}})

    with (
        httpx.Client(transport=httpx.MockTransport(api_error)) as transport,
        WikidataClient(transport) as client,
        pytest.raises(ValueError, match="API returned an error"),
    ):
        client.search("story")


def test_cli_refuses_to_overwrite_research(tmp_path: Path) -> None:
    path = tmp_path / "case.json"
    assert cli.main(["init", str(path)]) == 0
    initial = path.read_bytes()
    assert cli.main(["init", str(path)]) == 2
    assert path.read_bytes() == initial
    assert cli.main(["plan", str(path), "--output", str(path)]) == 2
    assert cli.main(["export", str(path), "--output", str(path)]) == 2
    assert path.read_bytes() == initial


def test_plan_preserves_language_precision_and_table_boundaries() -> None:
    example = case()
    example.entities[0].claims = [
        Claim(
            id="title",
            property="P1476",
            datatype="monolingualtext",
            value="A|B",
            language="en",
            sources=["book"],
        ),
        Claim(
            id="date",
            property="P577",
            datatype="time",
            value="1982",
            precision="year",
            sources=["book"],
        ),
    ]
    output = render_plan(example)
    assert "en: A&#124;B" in output
    assert "1982 (year precision)" in output
    assert "checked" in output


def test_matching_searches_alternate_titles_and_label_fallback() -> None:
    example = case()
    example.entities[0].resolution = Resolution()
    example.entities[0].title = None
    example.entities[0].alternate_titles = ["Earlier Title"]

    class Search:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def search(self, query: str) -> list[dict[str, str]]:
            self.queries.append(query)
            return []

    client = Search()
    match_case(example, client)
    assert client.queries == ["Story", "Earlier Title"]
    assert example.entities[0].resolution.status == "unresolved"

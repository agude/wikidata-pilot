"""Offline tests for evidence validation, matching, plans, and export."""

import json
import os
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest
from pydantic import HttpUrl

from wikidata_pilot import cli
from wikidata_pilot.models import Case, Claim, Entity, Resolution, Source
from wikidata_pilot.wikidata import WikidataClient
from wikidata_pilot.workflow import (
    _quickstatements_date,
    deferred_claims,
    export_case,
    live_snapshot,
    match_case,
    render_plan,
    validate_case,
)


def source(
    verification: Literal["verified", "illustrative_unverified"] = "verified",
) -> Source:
    return Source(
        id="book",
        url=HttpUrl("https://example.org/book"),
        retrieved=date(2026, 9, 29),
        excerpt="page 2",
        verification=verification,
    )


def case() -> Case:
    return Case(
        title="Test",
        sources=[source()],
        entities=[
            Entity(
                key="story",
                kind="work",
                label="Story",
                description="short story",
                title="Story",
                resolution=Resolution(status="existing", qid="Q1", reason="checked"),
                claims=[
                    Claim(
                        id="collection",
                        property="P1433",
                        datatype="item",
                        value="Q2",
                        sources=["book"],
                    )
                ],
            ),
        ],
    )


def test_case_checks_evidence_and_unresolved_state() -> None:
    example = case()
    example.sources[0].verification = "illustrative_unverified"
    example.entities[0].resolution = Resolution()
    messages = validate_case(example)
    assert any("illustrative_unverified" in message for message in messages)
    assert any("unresolved" in message for message in messages)


def test_missing_source_fails_and_unsafe_text_is_rejected() -> None:
    example = case()
    example.entities[0].claims[0].sources = ["missing"]
    assert any("missing or no source" in message for message in validate_case(example))
    example.entities[0].claims[0] = Claim(
        id="unsafe",
        property="P1476",
        datatype="string",
        value='A "title"',
        sources=["book"],
    )
    assert any("unsafe" in message for message in validate_case(example))


def test_local_dependency_blocks_relationship_until_target_is_resolved() -> None:
    example = case()
    example.entities.append(
        Entity(
            key="collection",
            kind="collection",
            label="Collection",
            description="anthology",
            resolution=Resolution(status="create", reason="searched ISBN and title"),
        )
    )
    example.entities[0].claims[0].value = "collection"
    assert validate_case(example) == []
    output = export_case(example)
    assert "CREATE" in output
    assert deferred_claims(example) == ["story.collection -> collection"]


def test_matching_preserves_ambiguity_and_identifier_search_first() -> None:
    example = Case(
        title="Test",
        sources=[source()],
        entities=[
            Entity(
                key="story",
                kind="work",
                label="Story",
                description="work",
                title="Story",
                identifiers={"P212": "9780000000000"},
            )
        ],
    )

    class Search:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def search(self, query: str) -> list[dict[str, str]]:
            self.queries.append(query)
            return [{"id": "Q1", "label": "Story"}]

        def search_identifier(self, property_id: str, identifier: str) -> list[dict[str, str]]:
            self.queries.append(f"{property_id}:{identifier}")
            return [{"id": "Q1", "label": "Story"}]

    client = Search()
    matched, report = match_case(example, client)
    assert client.queries == ["P212:9780000000000", "Story"]
    assert matched.entities[0].resolution.status == "unresolved"
    candidates = report[0]["candidates"]
    assert isinstance(candidates, list)
    assert len(candidates) == 1


def test_plan_includes_current_and_proposed_labels() -> None:
    output = render_plan(case())
    assert "live snapshot not captured" in output
    assert "Proposed claim" in output
    assert "Q1" in output


def test_export_blocks_unverified_source() -> None:
    example = case()
    example.sources[0].verification = "illustrative_unverified"
    with pytest.raises(ValueError, match="unverified"):
        export_case(example)


def test_export_renders_creation_claims_dates_text_and_references() -> None:
    example = Case(
        title="Export",
        sources=[source()],
        entities=[
            Entity(
                key="book",
                kind="work",
                label="Book",
                description="written work",
                resolution=Resolution(status="create", reason="checked source and searches"),
                claims=[
                    Claim(
                        id="title",
                        property="P1476",
                        datatype="monolingualtext",
                        value="Title",
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
                    Claim(
                        id="id",
                        property="P212",
                        datatype="external-id",
                        value="9780000000000",
                        sources=["book"],
                    ),
                ],
            )
        ],
    )
    output = export_case(example)
    assert output.startswith('CREATE\nLAST|Len|"Book"')
    assert 'P1476|en:"Title"' in output
    assert "/9|S854|" in output
    assert 'P212|"9780000000000"' in output


def test_time_dates_and_snapshot_rendering() -> None:
    assert _quickstatements_date("1982", "year").endswith("/9")
    assert _quickstatements_date("1982-03", "month").endswith("/10")
    with pytest.raises(ValueError, match="Invalid time"):
        _quickstatements_date("1982-03-01-extra", "day")
    snapshot: dict[str, object] = {
        "story": {
            "entities": {
                "Q1": {"claims": {"P1433": [{"mainsnak": {"datavalue": {"value": {"id": "Q2"}}}}]}}
            }
        }
    }
    assert "{'id': 'Q2'}" in render_plan(case(), snapshot)


def test_live_snapshot_calls_only_resolved_items() -> None:
    class Reader:
        def __init__(self) -> None:
            self.qids: list[str] = []

        def inspect(self, qid: str) -> dict[str, object]:
            self.qids.append(qid)
            return {"qid": qid}

    reader = Reader()
    assert live_snapshot(case(), reader) == {"story": {"qid": "Q1"}}
    assert reader.qids == ["Q1"]


def test_prepare_is_offline_by_default_and_writes_consistent_outputs(tmp_path, monkeypatch, capsys):
    case_path = tmp_path / "research case.json"
    output_path = tmp_path / "review" / "batch.qs"
    original = case().model_dump(mode="json")
    case_path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    def unexpected_client():
        raise AssertionError("offline prepare must not create a Wikidata client")

    monkeypatch.setattr(cli, "WikidataClient", unexpected_client)
    assert cli.main(["prepare", str(case_path), "--output", str(output_path)]) == 0
    assert capsys.readouterr().out.startswith("Wrote ")
    assert case_path.read_text(encoding="utf-8") == json.dumps(original)
    proposal = json.loads(case_path.with_suffix(".plan.json").read_text(encoding="utf-8"))
    assert proposal["snapshot"] == {}
    assert "live snapshot not captured" in case_path.with_suffix(".plan.md").read_text()
    assert output_path.read_text().startswith("Q1|P1433|Q2")


def test_prepare_snapshot_is_opt_in_and_validation_failure_preserves_outputs(
    tmp_path, monkeypatch, capsys
):
    case_path = tmp_path / "case.json"
    valid = case().model_dump(mode="json")
    case_path.write_text(json.dumps(valid), encoding="utf-8")
    output_path = tmp_path / "batch.qs"
    outputs = [case_path.with_suffix(".plan.md"), case_path.with_suffix(".plan.json"), output_path]

    class SnapshotClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def inspect(self, qid):
            inspected_qids.append(qid)
            return {"snapshot": qid}

    inspected_qids: list[str] = []
    valid["entities"].append(
        {
            "key": "new-collection",
            "kind": "collection",
            "label": "New collection",
            "description": "anthology",
            "resolution": {"status": "create", "reason": "searched title and ISBN"},
            "claims": [],
        }
    )
    case_path.write_text(json.dumps(valid), encoding="utf-8")
    monkeypatch.setattr(cli, "WikidataClient", SnapshotClient)
    assert cli.main(["prepare", str(case_path), "--output", str(output_path), "--snapshot"]) == 0
    assert inspected_qids == ["Q1"]
    proposal = json.loads(outputs[1].read_text(encoding="utf-8"))
    assert proposal["snapshot"] == {"story": {"snapshot": "Q1"}}

    invalid = case().model_dump(mode="json")
    invalid["sources"][0]["verification"] = "illustrative_unverified"
    case_path.write_text(json.dumps(invalid), encoding="utf-8")
    for path in outputs:
        path.write_text("keep this\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in [case_path, *outputs]}
    assert cli.main(["prepare", str(case_path), "--output", str(output_path)]) == 1
    assert "illustrative_unverified" in capsys.readouterr().err
    assert {path: path.read_bytes() for path in before} == before


def test_prepare_remote_failure_preserves_existing_outputs(tmp_path, monkeypatch, capsys):
    case_path = tmp_path / "case.json"
    case_path.write_text(case().model_dump_json(), encoding="utf-8")
    output_paths = [
        case_path.with_suffix(".plan.md"),
        case_path.with_suffix(".plan.json"),
        tmp_path / "batch.qs",
    ]
    for path in output_paths:
        path.write_text("keep this\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in [case_path, *output_paths]}

    class FailedSnapshotClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def inspect(self, qid):
            raise httpx.ConnectError("remote failure")

    monkeypatch.setattr(cli, "WikidataClient", FailedSnapshotClient)
    assert (
        cli.main(["prepare", str(case_path), "--output", str(output_paths[2]), "--snapshot"]) == 2
    )
    assert "remote failure" in capsys.readouterr().err
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("collision", ["case", "cache", "plan", "json", "symlink"])
def test_prepare_rejects_path_collisions_before_writing(tmp_path, collision):
    case_path = tmp_path / "case.json"
    case_path.write_text(case().model_dump_json(), encoding="utf-8")
    before = case_path.read_bytes()
    output_path = tmp_path / "batch.qs"
    arguments = ["prepare", str(case_path), "--output", str(output_path)]
    if collision == "case":
        arguments[3] = str(case_path)
    elif collision == "cache":
        arguments.extend(["--cache", str(case_path)])
    elif collision == "plan":
        arguments[3] = str(case_path.with_suffix(".plan.md"))
    elif collision == "json":
        arguments[3] = str(case_path.with_suffix(".plan.json"))
    else:
        alias = tmp_path / "alias.json"
        alias.symlink_to(case_path)
        arguments[3] = str(alias)
    assert cli.main(arguments) == 2
    assert case_path.read_bytes() == before


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "UV_CACHE_DIR": "uv cache override",
            "UV_PYTHON_INSTALL_DIR": "python override",
            "PYSTOW_HOME": "pystow override",
            "WIKIDATA_PILOT_STATE_DIR": "state override",
        },
        {},
    ],
)
def test_pilot_forwards_arguments_and_environment_overrides(tmp_path, overrides):
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    argument_log = tmp_path / "arguments.txt"
    working_directory = tmp_path / "cwd.txt"
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "$ARGUMENT_LOG"\nprintf \'%s\\n\' "$PWD" > "$WORKING_DIRECTORY"\nprintf \'%s\\n\' "$UV_CACHE_DIR" "$UV_PYTHON_INSTALL_DIR" "$PYSTOW_HOME" "$WIKIDATA_PILOT_STATE_DIR" > "$CACHE_LOG"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    cache_log = tmp_path / "cache.txt"
    environment = dict(os.environ)
    environment.update({key: str(tmp_path / value) for key, value in overrides.items()})
    for key in (
        "UV_CACHE_DIR",
        "UV_PYTHON_INSTALL_DIR",
        "PYSTOW_HOME",
        "WIKIDATA_PILOT_STATE_DIR",
    ):
        if not overrides:
            environment.pop(key, None)
    environment.update(
        {
            "ARGUMENT_LOG": str(argument_log),
            "WORKING_DIRECTORY": str(working_directory),
            "CACHE_LOG": str(cache_log),
        }
    )
    environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
    subprocess.run(
        [
            str(Path(__file__).parents[1] / "bin" / "pilot"),
            "prepare",
            "case folder/case file.json",
            "--output",
            "review file.qs",
        ],
        cwd=tmp_path,
        env=environment,
        check=True,
    )
    arguments = argument_log.read_text(encoding="utf-8").splitlines()
    assert arguments[-4:] == ["prepare", "case folder/case file.json", "--output", "review file.qs"]
    assert arguments[0] == "--project"
    assert working_directory.read_text(encoding="utf-8").strip() == str(tmp_path)
    cache_values = cache_log.read_text(encoding="utf-8").splitlines()
    expected_defaults = [
        str(Path(__file__).parents[1] / ".uv-cache"),
        str(Path(__file__).parents[1] / ".uv-python"),
        str(Path(__file__).parents[1] / ".pystow"),
        str(Path(__file__).parents[1] / ".wikidata-pilot-state"),
    ]
    expected = (
        [str(tmp_path / overrides[key]) for key in overrides] if overrides else expected_defaults
    )
    assert cache_values == expected


def test_wikidata_client_handles_search_and_errors() -> None:
    class Response:
        def __init__(self, payload: object) -> None:
            self.payload = payload
            self.status_code = 200
            self.headers: dict[str, str] = {}
            self.text = ""
            self.reason_phrase = "OK"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return self.payload

    class Transport:
        def get(self, url: str, **kwargs: object) -> Response:
            if "sparql" in url:
                return Response(
                    {
                        "results": {
                            "bindings": [
                                {
                                    "item": {"value": "http://www.wikidata.org/entity/Q9"},
                                    "itemLabel": {"value": "Nine"},
                                }
                            ]
                        }
                    }
                )
            params = kwargs.get("params", {})
            if isinstance(params, dict) and params.get("list") == "search":
                return Response({"query": {"search": [{"title": "Q9"}]}})
            if isinstance(params, dict) and params.get("action") == "wbgetentities":
                return Response(
                    {
                        "entities": {
                            "Q9": {
                                "id": "Q9",
                                "claims": {
                                    "P212": [
                                        {
                                            "rank": "normal",
                                            "mainsnak": {
                                                "snaktype": "value",
                                                "datavalue": {"value": "9780000000000"},
                                            },
                                        }
                                    ]
                                },
                            }
                        }
                    }
                )
            return Response({"search": [{"id": "Q3", "label": "Three"}]})

        def close(self) -> None:
            return None

    client = WikidataClient(Transport())  # type: ignore[arg-type]
    assert client.search("Three")[0]["id"] == "Q3"
    assert client.search_identifier("P212", "9780000000000")[0]["id"] == "Q9"
    client.close()


def test_cli_commands_with_offline_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    case_path = tmp_path / "case.json"
    assert cli.main(["init", str(case_path)]) == 0
    assert cli.main(["validate", str(case_path)]) == 1

    ready = case()
    case_path.write_text(ready.model_dump_json(), encoding="utf-8")

    class OfflineClient:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def inspect(self, qid: str) -> dict[str, object]:
            return {"entities": {qid: {"claims": {}}}}

        def search_identifier(self, property_id: str, identifier: str) -> list[dict[str, str]]:
            return []

        def search(self, query: str) -> list[dict[str, str]]:
            return []

    monkeypatch.setattr(cli, "WikidataClient", OfflineClient)
    assert cli.main(["inspect", "Q1"]) == 0
    assert cli.main(["match", str(case_path)]) == 0
    assert cli.main(["plan", str(case_path), "--snapshot"]) == 0
    assert case_path.with_suffix(".plan.md").exists()
    output = tmp_path / "out.qs"
    assert cli.main(["export", str(case_path), "--output", str(output)]) == 0
    assert output.read_text(encoding="utf-8")
    assert cli.main(["validate", str(tmp_path / "missing.json")]) == 2
    assert "error:" in capsys.readouterr().err

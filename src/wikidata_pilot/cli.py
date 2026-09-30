"""Command-line interface for reviewing and exporting Wikidata proposals."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import httpx
from pydantic import ValidationError

from .cache import DEFAULT_CACHE, IdCache, case_ids
from .models import load_case, save_case
from .wikidata import WikidataClient
from .workflow import (
    deferred_claims,
    export_case,
    live_snapshot,
    match_case,
    render_plan,
    render_proposal_json,
    validate_case,
    write_proposal_json,
)

SAMPLE = {
    "schema_version": 1,
    "title": "Bolo anthology and story research",
    "sources": [
        {
            "id": "abebooks-listing",
            "url": "https://www.abebooks.com/9780441069972/Bolo-Laumer-Keith-0441069975/plp",
            "retrieved": "2026-09-29",
            "excerpt": "Illustrative placeholder only; verify title, contributors, and publication details against a reliable source.",
            "locator": "listing page",
            "verification": "illustrative_unverified",
        }
    ],
    "entities": [
        {
            "key": "bolo-collection",
            "kind": "collection",
            "label": "Bolo",
            "description": "science fiction anthology",
            "title": "Bolo",
            "resolution": {
                "status": "existing",
                "qid": "Q48997316",
                "reason": "Supplied collection candidate; confirm scope and edition relationship.",
            },
            "claims": [],
        },
        {
            "key": "field-test",
            "kind": "work",
            "label": "Field Test",
            "description": "science fiction short story",
            "title": "Field Test",
            "authors": ["Keith Laumer"],
            "resolution": {
                "status": "existing",
                "qid": "Q135012308",
                "reason": "Supplied story candidate; verify it is the same work.",
            },
            "claims": [
                {
                    "id": "in-collection",
                    "property": "P1433",
                    "datatype": "item",
                    "value": "bolo-collection",
                    "sources": ["abebooks-listing"],
                }
            ],
        },
        {
            "key": "keith-laumer",
            "kind": "person",
            "label": "Keith Laumer",
            "description": "American science fiction writer",
            "resolution": {
                "status": "existing",
                "qid": "Q724395",
                "reason": "Supplied author candidate; verify identity.",
            },
            "claims": [],
        },
    ],
}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="wikidata-pilot", description="Prepare reviewed, evidence-backed Wikidata edits"
    )
    sub = root.add_subparsers(dest="command", required=True)
    initialize = sub.add_parser("init", help="create an illustrative case template")
    initialize.add_argument("path", type=Path)
    inspect = sub.add_parser("inspect", help="read one Wikidata item as JSON")
    inspect.add_argument("qid")
    match = sub.add_parser("match", help="search unresolved entities and save candidates")
    match.add_argument("case", type=Path)
    validate = sub.add_parser("validate", help="validate evidence and resolution decisions")
    validate.add_argument("case", type=Path)
    plan = sub.add_parser("plan", help="write before/after proposal review files")
    plan.add_argument("case", type=Path)
    plan.add_argument(
        "--snapshot", action="store_true", help="fetch current claims for resolved QIDs"
    )
    plan.add_argument("--output", type=Path, help="Markdown path; defaults beside case")
    plan.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    cache = sub.add_parser("cache", help="read or update checked-in ID metadata")
    cache.add_argument("ids", nargs="*", help="QIDs and PIDs to fetch if missing")
    cache.add_argument("--case", type=Path, help="also collect IDs from a case")
    cache.add_argument("--find", help="find all exact label or alias matches locally")
    cache.add_argument("--refresh", action="store_true", help="refetch requested IDs")
    cache.add_argument("--file", type=Path, default=DEFAULT_CACHE)
    export = sub.add_parser("export", help="write staged QuickStatements file")
    export.add_argument("case", type=Path)
    export.add_argument("--output", type=Path, required=True)
    prepare = sub.add_parser("prepare", help="validate and render all review outputs")
    prepare.add_argument("case", type=Path)
    prepare.add_argument("--output", type=Path, required=True, help="staged QuickStatements path")
    prepare.add_argument("--snapshot", action="store_true", help="fetch current claims")
    prepare.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            args.path.parent.mkdir(parents=True, exist_ok=True)
            with args.path.open("x", encoding="utf-8") as output:
                output.write(json.dumps(SAMPLE, indent=2) + "\n")
            print(f"Created illustrative case: {args.path}")
        elif args.command == "cache":
            cache = IdCache(args.file)
            if args.find is not None:
                if args.ids or args.case or args.refresh:
                    raise ValueError("--find cannot be combined with update arguments")
                print(
                    json.dumps(
                        {
                            key: entry.model_dump(mode="json")
                            for key, entry in cache.find(args.find).items()
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            else:
                ids = set(args.ids)
                if args.case:
                    if args.case.resolve() == args.file.resolve():
                        raise ValueError("Cache must be distinct from the input case")
                    ids.update(case_ids(load_case(args.case)))
                if not ids:
                    raise ValueError("Supply IDs, --case, or --find")
                with WikidataClient() as client:
                    count = cache.update(ids, client, refresh=args.refresh)
                print(f"Updated {count} entries in {args.file}")
                if args.ids:
                    print(
                        json.dumps(
                            {
                                key: cache.entries[key].model_dump(mode="json")
                                for key in sorted(set(args.ids))
                            },
                            indent=2,
                            ensure_ascii=False,
                        )
                    )
        elif args.command == "inspect":
            with WikidataClient() as client:
                print(json.dumps(client.inspect(args.qid), indent=2, ensure_ascii=False))
        elif args.command == "match":
            case = load_case(args.case)
            with WikidataClient() as client:
                case, report = match_case(case, client)
            save_case(args.case, case)
            print(json.dumps(report, indent=2, ensure_ascii=False))
        elif args.command == "validate":
            errors = validate_case(load_case(args.case))
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 1
            print("Case structure and evidence references are valid.")
        elif args.command == "plan":
            case = load_case(args.case)
            snapshot = None
            if args.snapshot:
                with WikidataClient() as client:
                    snapshot = live_snapshot(case, client)
            plan_path = args.output or args.case.with_suffix(".plan.md")
            json_path = plan_path.with_suffix(".json")
            if (
                args.case.resolve() in {plan_path.resolve(), json_path.resolve()}
                or plan_path == json_path
                or args.cache.resolve() in {plan_path.resolve(), json_path.resolve()}
            ):
                raise ValueError(
                    "Plan outputs must be distinct from the input case, cache, and each other"
                )
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(render_plan(case, snapshot, IdCache(args.cache)), encoding="utf-8")
            write_proposal_json(json_path, case, snapshot)
            print(f"Wrote {plan_path} and {json_path}")
        elif args.command == "export":
            if args.output.resolve() == args.case.resolve():
                raise ValueError("Export output must be distinct from the input case")
            case = load_case(args.case)
            contents = export_case(case)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(contents, encoding="utf-8")
            print(f"Wrote staged export: {args.output}")
            for item in deferred_claims(case):
                print(f"Deferred relationship pending returned QID: {item}")
        elif args.command == "prepare":
            case_path = args.case.resolve()
            cache_path = args.cache.resolve()
            qs_path = args.output.resolve()
            plan_path = args.case.with_suffix(".plan.md").resolve()
            json_path = plan_path.with_suffix(".json").resolve()
            paths = [case_path, cache_path, qs_path, plan_path, json_path]
            if len(set(paths)) != len(paths):
                raise ValueError("Prepare input, cache, and output paths must all be distinct")

            case = load_case(args.case)
            errors = validate_case(case)
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 1

            cache = IdCache(args.cache)
            qs_contents = export_case(case)
            snapshot = None
            if args.snapshot:
                with WikidataClient() as client:
                    snapshot = live_snapshot(case, client)
            plan_contents = render_plan(case, snapshot, cache)
            json_contents = render_proposal_json(case, snapshot)

            for path in (plan_path, json_path, qs_path):
                path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(plan_contents, encoding="utf-8")
            json_path.write_text(json_contents, encoding="utf-8")
            qs_path.write_text(qs_contents, encoding="utf-8")
            print(f"Wrote {plan_path}, {json_path}, and {qs_path}")
            for item in deferred_claims(case):
                print(f"Deferred relationship pending returned QID: {item}")
        return 0
    except (OSError, ValueError, ValidationError, httpx.HTTPError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

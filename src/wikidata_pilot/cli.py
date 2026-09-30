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
from .inspection import summarize_entity
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
        prog="wikidata-pilot",
        description="Prepare reviewed, evidence-backed Wikidata edits",
        epilog="Reference: docs/commands.md (in the repository)",
    )
    sub = root.add_subparsers(dest="command", required=True)

    def command(name: str, help: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help, epilog=f"Reference: docs/commands.md#{name}")

    initialize = command("init", help="create an illustrative case template")
    initialize.add_argument("path", type=Path)
    inspect = command("inspect", help="read compact item or property statements")
    inspect.add_argument("qids", nargs="+", help="QIDs or PIDs")
    inspect.add_argument(
        "--property", dest="properties", action="extend", nargs="+", help="only these PIDs"
    )
    inspect.add_argument("--raw", action="store_true", help="full API response")
    inspect.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    search = command("search", help="search entity names and aliases")
    search.add_argument("query")
    search.add_argument("--type", choices=["item", "property"], default="item")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--offset", type=int, default=0)
    search.add_argument("--fresh", action="store_true", help="bypass cached candidates")
    linked = command("linked", help="find incoming statements for one property")
    linked.add_argument("qid")
    linked.add_argument("--property", required=True)
    linked.add_argument("--limit", type=int, default=50)
    linked.add_argument("--offset", type=int, default=0)
    linked.add_argument("--fresh", action="store_true", help="bypass cached candidates")
    backlinks = command("backlinks", help="list incoming item-page links")
    backlinks.add_argument("qid")
    backlinks.add_argument("--limit", type=int, default=50)
    backlinks.add_argument("--cursor")
    page = command("page", help="list guidance sections or read selected wikitext")
    page.add_argument("title")
    page.add_argument("--section", type=int)
    identifier = command("identifier", help="find an exact identifier value")
    identifier.add_argument("property")
    identifier.add_argument("value")
    identifier.add_argument("--limit", type=int, default=10)
    identifier.add_argument("--offset", type=int, default=0)
    identifier.add_argument("--fresh", action="store_true", help="bypass cached candidates")
    ancestors = command("ancestors", help="trace class hierarchies")
    ancestors.add_argument("qid")
    ancestors.add_argument("--instance-of", action="store_true")
    ancestors.add_argument("--limit", type=int, default=50)
    ancestors.add_argument("--offset", type=int, default=0)
    ancestors.add_argument("--fresh", action="store_true", help="bypass cached candidates")
    resolve = command("resolve", help="find an item from a wiki page title")
    resolve.add_argument("site")
    resolve.add_argument("title")
    history = command("history", help="read item or property revision metadata")
    history.add_argument("id")
    history.add_argument("--limit", type=int, default=10)
    history.add_argument("--cursor")
    match = command("match", help="search unresolved entities and save candidates")
    match.add_argument("case", type=Path)
    validate = command("validate", help="validate evidence and resolution decisions")
    validate.add_argument("case", type=Path)
    plan = command("plan", help="write before/after proposal review files")
    plan.add_argument("case", type=Path)
    plan.add_argument(
        "--snapshot", action="store_true", help="fetch current claims for resolved QIDs"
    )
    plan.add_argument("--output", type=Path, help="Markdown path; defaults beside case")
    plan.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    cache = command("cache", help="read or update checked-in ID metadata")
    cache.add_argument("ids", nargs="*", help="QIDs and PIDs to fetch if missing")
    cache.add_argument("--case", type=Path, help="also collect IDs from a case")
    cache.add_argument("--find", help="find all exact label or alias matches locally")
    cache.add_argument("--refresh", action="store_true", help="refetch requested IDs")
    cache.add_argument("--file", type=Path, default=DEFAULT_CACHE)
    export = command("export", help="write staged QuickStatements file")
    export.add_argument("case", type=Path)
    export.add_argument("--output", type=Path, required=True)
    prepare = command("prepare", help="validate and render all review outputs")
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
            if args.raw and args.properties:
                raise ValueError("Use --property for compact output or --raw for the full response")
            if args.properties:
                IdCache._validate_ids(args.properties)
                if any(not identifier.startswith("P") for identifier in args.properties):
                    raise ValueError("Expected property IDs for --property")
            inspection_cache = IdCache(args.cache) if not args.raw else None
            with WikidataClient() as client:
                payload = (
                    client.inspect(args.qids[0])
                    if len(args.qids) == 1
                    else client.inspect_many(args.qids)
                )
            if inspection_cache:
                entities = payload["entities"]
                assert isinstance(entities, dict)
                records = [
                    summarize_entity({"entities": {key: entity}}, inspection_cache, args.properties)
                    for key, entity in entities.items()
                ]
                result = records[0] if len(args.qids) == 1 else {"entities": records}
            else:
                result = payload
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        elif args.command in {
            "search",
            "linked",
            "backlinks",
            "page",
            "identifier",
            "ancestors",
            "resolve",
            "history",
        }:
            with WikidataClient() as client:
                if args.command == "search":
                    result = client.search_page(
                        args.query,
                        entity_type=args.type,
                        limit=args.limit,
                        offset=args.offset,
                        fresh=args.fresh,
                    )
                elif args.command == "linked":
                    result = client.linked(
                        args.qid,
                        args.property,
                        limit=args.limit,
                        offset=args.offset,
                        fresh=args.fresh,
                    )
                elif args.command == "backlinks":
                    result = client.backlinks(args.qid, limit=args.limit, cursor=args.cursor)
                elif args.command == "identifier":
                    result = client.identifier(
                        args.property,
                        args.value,
                        limit=args.limit,
                        offset=args.offset,
                        fresh=args.fresh,
                    )
                elif args.command == "ancestors":
                    result = client.ancestors(
                        args.qid,
                        instance_of=args.instance_of,
                        limit=args.limit,
                        offset=args.offset,
                        fresh=args.fresh,
                    )
                elif args.command == "resolve":
                    result = client.resolve(args.site, args.title)
                elif args.command == "history":
                    result = client.history(args.id, limit=args.limit, cursor=args.cursor)
                else:
                    result = client.page(args.title, section=args.section)
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
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

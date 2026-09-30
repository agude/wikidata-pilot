# wikidata-pilot

`wikidata-pilot` prepares evidence-backed Wikidata proposals for a person to review and submit. It searches and reads the Wikidata API, but never writes to Wikidata and contains no embedded language model. Each fact must link to a source record containing its URL, retrieval date, excerpt, and optional page locator.

## Install and start

From a clone of this repository, install uv, just, and ShellCheck, then install the package and development tools:

```sh
cd /home/agude/Projects/wikidata-pilot
just sync
just hooks-install
just pilot --help
```

## Quick start

```sh
just pilot init bolo.json
just pilot inspect Q48997316 > collection.json
just pilot plan bolo.json --snapshot
```

`init` creates an illustrative Bolo case. Its AbeBooks excerpt is explicitly unverified; replace or verify it before marking that source `verified`. The supplied QIDs are candidates to confirm, not assertions that the listed entities or relationships have been independently verified.

An agent researches the book using its browsing tools, records source passages in `bolo.json`, and adds each story as an entity. Set entities needing candidate searches to `unresolved`. The supplied example entities already have QIDs, so `match` skips them. Then run:

```sh
just pilot match bolo.json
# Inspect candidates, record resolution decisions, and verify sources in bolo.json.
just pilot validate bolo.json
just pilot prepare bolo.json --output staged.qs
```

`validate` and `prepare` fail on the original template until its source is verified. `prepare` writes `bolo.plan.md`, `bolo.plan.json`, and `staged.qs` from the same case. It plans offline by default; add `--snapshot` when current item statements matter or before submission. Review all three files, paste `staged.qs` into QuickStatements 3 using V1 syntax, preview the commands, and run the batch manually. Store the downloaded execution report beside the case. Do not rerun a creation batch after a timeout without checking whether items were created.

The top-level case object contains `schema_version`, `title`, `sources`, and `entities`. It is UTF-8 JSON validated with Pydantic. Each entity has a local key and a resolution of `unresolved`, `existing` with a QID, or `create`. A `create` decision must include a reason. A no-result search is never proof that an item does not exist; inspect candidates and record the search context in the resolution reason before choosing `create`. Matching checks exact external identifier values before title candidates and title-plus-author candidates. Ambiguous results remain unresolved until a person records a decision.

## Case format

| Record | Required fields | Optional fields |
|---|---|---|
| Case | `schema_version: 1`, `title`, `sources`, `entities` | — |
| Source | unique `id`, HTTP(S) `url`, ISO `retrieved` date, supporting `excerpt` | `locator`, `verification` (defaults to unverified) |
| Entity | unique lowercase `key`, `kind`, `label`, `description` | `title`, `alternate_titles`, `authors` search hints, `identifiers` property/value map, `claims`, `resolution` |
| Resolution | `status` | `qid` required for `existing`; `reason` required for `existing` and `create`; `candidates` populated by matching |
| Claim | unique `id` within its entity, `property`, `datatype`, `value`, `sources` IDs | `language` required for monolingual text; `precision` required for dates; `qualifiers` |
| Qualifier | `property`, `datatype`, `value` | `precision` required for dates |

Entity kinds are `work`, `collection`, `edition`, and `person`. Item values can be QIDs or local entity keys, including in qualifiers. Dates use exact `YYYY`, `YYYY-MM`, or `YYYY-MM-DD` shapes with `year`, `month`, or `day` precision. Qualifiers support `item`, `string`, and `time`. Labels and descriptions on new items are English. Existing labels and descriptions are left untouched.

## Review and modeling

`plan` writes Markdown and structured JSON. The Markdown shows current claims as “live snapshot not captured” unless used with `--snapshot`; the JSON carries the fetched item payloads for resolved QIDs. Read the before/after report and verify each proposal against its source before export. Wikidata represents both creative works and editions: distinguish a work from a particular edition. Use P1433 (“published in”) to relate a story work to an anthology when the source supports that relationship. Record a story’s first publication date separately from its appearance date in a later anthology.

Claims and qualifiers use explicit datatype sets. Claims require one or more source IDs. Sources default to `illustrative_unverified`; change them to `verified` only after checking the cited material. Export supports item, string, external identifier, date with year/month/day precision, and monolingual text claims. It preserves qualifiers and attaches source URL and retrieval date reference snaks. It blocks unverified sources, unresolved entities, missing evidence, and unsafe values containing newlines, pipes, quotes, or angle brackets. See [docs/modeling.md](docs/modeling.md) for sourced work, edition, collection, and publication-date guidance.

## ID metadata cache

`data/wikidata_ids.json` is a checked-in dictionary keyed by QID or PID. Each entry contains an English label, description, aliases, property datatype (when applicable), and retrieval date. The Python wrapper is `IdCache` in `wikidata_pilot.cache`.

```sh
# Read every local label or alias match; no network request.
just pilot cache --find "Keith Laumer"
# Fetch only missing IDs, in batches of up to 50.
just pilot cache P50 Q724395
just pilot cache --case bolo.json
# Explicitly refresh the requested IDs.
just pilot cache --case bolo.json --refresh
just pilot plan bolo.json --snapshot
```

Plans load cached labels automatically and retain the IDs, for example `author (P50)` and `Keith Laumer (Q724395)`. Missing metadata falls back to the ID. Planning does not update the cache; run `cache --case` after adding IDs to a case. Current claim snapshots are always fetched separately with `--snapshot`.

Name lookup returns all exact, case-insensitive label and alias matches. A cached name is a search aid, not an identity decision or evidence for a claim. Cache updates stop on missing or redirected IDs and leave the file unchanged on failure. Inspect redirected IDs before updating the case. Review and commit JSON diffs to share metadata between agent sessions.

The CLI defaults to `data/wikidata_ids.json`. The runner uses writable repository-local uv and QS library caches while preserving `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR`, and `PYSTOW_HOME` overrides. Run `just pilot` from the repository root so relative case and output paths have predictable locations. The recipe uses the repository's absolute uv project path and runs in the repository root. From another directory, invoke `/path/to/wikidata-pilot/bin/pilot` directly to keep case and output paths relative to that directory. The metadata cache also remains relative to that directory. `cache --file PATH` and `plan`/`prepare --cache PATH` override the metadata cache input.

## Staged creation

When a case contains several new entities that refer to one another, export creates each new entity’s label, description, and claims whose targets already resolve. Relationship claims to another new entity are listed as deferred. Submit the first `.qs` batch manually, copy each returned QID into that entity’s resolution as `existing` with a reason, then run validation, planning, and export again. The resolved QID is reused; the tool does not create that entity again. Review each generated batch before submitting it.

`quickstatements-client` builds QuickStatements lines locally. The tool does not call its submission API. Keep backups of case files and review generated files as proposals, not completed edits.

## Limits and checks

Source verification records a source-check decision. The CLI checks evidence links and value syntax; it does not establish that an excerpt supports a claim or validate every Wikidata property constraint. Identifier searches use the Wikidata Query Service, whose results may lag recent edits. Title and author searches supply candidates rather than verified identity matches. Search failures stop the command and leave the case file unchanged.

Plans are additive proposals and snapshots for review. The exporter does not compute an execution history or remove statements. Multiple source records emit separate commands for the same claim, each with its own URL/date reference group. QuickStatements determines how those commands merge with existing statements. Relationships with a new item as a value or qualifier are deferred together until its QID is recorded.

Run `just check` for lint, strict type checks, offline tests with a 90% coverage gate, and isolated wheel installation. Exit codes are 0 for success, 1 for validation findings, and 2 for malformed input, file errors, or remote failures. QuickStatements command separators, embedded quotes, angle brackets, and control characters are rejected rather than escaped. In restricted environments, set `PYSTOW_HOME` to a writable directory: the QS library's dependency initializes that directory during import.

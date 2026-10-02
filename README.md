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

For agent-led research, use the repo-local
[`wikidata-research` skill](.agents/skills/wikidata-research/SKILL.md). Its
references cover [books and editions](.agents/skills/wikidata-research/references/books.md)
and [authors](.agents/skills/wikidata-research/references/authors.md), including
fields to consider and the evidence each field needs. Invoke it in a Codex
session opened in this repo:

```text
$wikidata-research Check whether the Rogue Bolo story is a novella.
```

The skill lives under `.agents/skills/`, the
[repo-local discovery path](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills).

```sh
just pilot init requests/bolo/case.json
just pilot inspect Q48997316 > requests/bolo/collection.json
just pilot plan requests/bolo/case.json --snapshot
```

`init` creates an illustrative Bolo case. Its AbeBooks excerpt is explicitly unverified; replace or verify it before marking that source `verified`. The supplied QIDs are candidates to confirm, not assertions that the listed entities or relationships have been independently verified.

An agent reads Wikidata through the API commands below, uses browsing tools for external book sources, records source passages in `requests/bolo/case.json`, and adds each story as an entity. Set entities needing candidate searches to `unresolved`. The supplied example entities already have QIDs, so `match` skips them. Then run:

```sh
just pilot match requests/bolo/case.json
# Inspect candidates, record resolution decisions, and verify sources in requests/bolo/case.json.
just pilot validate requests/bolo/case.json
just pilot prepare requests/bolo/case.json --output requests/bolo/batches/001-create.qs
```

`validate` and `prepare` fail on the original template until its source is verified. `prepare` writes `requests/bolo/case.plan.md`, `requests/bolo/case.plan.json`, and `requests/bolo/batches/001-create.qs` from the same case. It plans offline by default; add `--snapshot` when current item statements matter or before submission. Review all three files, paste `001-create.qs` into QuickStatements 3 using V1 syntax, preview the commands, and run the batch manually. Store the downloaded execution report beside its batch. Do not rerun a creation batch after a timeout without checking whether items were created.

The top-level case object contains `schema_version`, `title`, `sources`, and `entities`. It is UTF-8 JSON validated with Pydantic. Each entity has a local key and a resolution of `unresolved`, `existing` with a QID, or `create`. A `create` decision must include a reason. A no-result search is never proof that an item does not exist; inspect candidates and record the search context in the resolution reason before choosing `create`. Matching checks exact external identifier values before title candidates and title-plus-author candidates. Ambiguous results remain unresolved until a person records a decision.

## Request files

Keep each request in its own local directory:

```text
requests/
  bolo/
    case.json
    case.plan.md
    case.plan.json
    batches/
      001-create.qs
      001-results.csv
```

`/requests/` is ignored by Git. Store source downloads and batch-specific
case snapshots within the same request directory. Number new batches;
retain submitted files and execution reports without overwriting them.
Regenerate draft plans as needed. Keep shared metadata in
`data/wikidata_ids.json` and reusable guidance in `docs/` tracked.

## Case format

For Google Knowledge Graph ID discovery, use
[`google-kg`](docs/commands.md#google-kg). It uses the API key from `.env` by
default, supports browser scraping and saved-page imports, and saves evidence
and candidate review reports under the request directory.

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

Claims and qualifiers use explicit datatype sets. Claims require one or more source IDs. Sources default to `illustrative_unverified`; change them to `verified` only after checking the cited material. Export supports item, string, external identifier, date with year/month/day precision, monolingual text, and HTTP(S) URL claims. It preserves qualifiers and attaches source URL and retrieval date reference snaks, except for P2671 and P646 external-ID claims. Those identifiers link to the entity; their verified evidence remains in the local case. It blocks unverified sources, unresolved entities, missing evidence, and unsafe values containing newlines, pipes, quotes, or angle brackets. See [docs/modeling.md](docs/modeling.md) for sourced work, edition, collection, and publication-date guidance.

## Wikidata API access

Use API commands for Wikidata reads and browse external sources for evidence.
The [command reference](docs/commands.md) covers identifier lookup, batch
inspection, relationships, class hierarchies, sitelink resolution, history,
backlinks, and guidance sections, including pagination and failure behavior.
Every command's `--help` points to its reference section. Before a network
request, set `WIKIDATA_PILOT_CONTACT` to an operator email or project URL. The
command reference documents shared cooldowns, retry limits, and the five
minute candidate cache.

```sh
just pilot identifier P212 "9780441069972"
just pilot inspect Q48997316 Q724395 --property P31 P50
just pilot linked Q724395 --property P50
```

## ID metadata cache

`data/wikidata_ids.json` is a checked-in dictionary keyed by QID or PID. Each entry contains an English label, description, aliases, property datatype (when applicable), and retrieval date. The Python wrapper is `IdCache` in `wikidata_pilot.cache`.

```sh
# Read every local label or alias match; no network request.
just pilot cache --find "Keith Laumer"
# Fetch only missing IDs, in batches of up to 50.
just pilot cache P50 Q724395
just pilot cache --case requests/bolo/case.json
# Explicitly refresh the requested IDs.
just pilot cache --case requests/bolo/case.json --refresh
just pilot plan requests/bolo/case.json --snapshot
```

Plans load cached labels automatically and retain the IDs, for example `author (P50)` and `Keith Laumer (Q724395)`. Missing metadata falls back to the ID. Planning does not update the cache; run `cache --case` after adding IDs to a case. Current claim snapshots are always fetched separately with `--snapshot`.

Name lookup returns all exact, case-insensitive label and alias matches. A cached name is a search aid, not an identity decision or evidence for a claim. Cache updates stop on missing or redirected IDs and leave the file unchanged on failure. Inspect redirected IDs before updating the case. Review and commit JSON diffs to share metadata between agent sessions.

The CLI defaults to `data/wikidata_ids.json`. The runner uses writable repository-local uv and QS library caches while preserving `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR`, and `PYSTOW_HOME` overrides. Run `just pilot` from the repository root so relative case and output paths have predictable locations. The recipe uses the repository's absolute uv project path and runs in the repository root. From another directory, invoke `/path/to/wikidata-pilot/bin/pilot` directly to keep case and output paths relative to that directory. The metadata cache also remains relative to that directory. `cache --file PATH` and `plan`/`prepare --cache PATH` override the metadata cache input.

## Staged creation

When a case contains several new entities that refer to one another, export creates each new entity’s label, description, and claims whose targets already resolve. Relationship claims to another new entity are listed as deferred. Submit the first `.qs` batch manually and save the Wikidata creation result lines. Preview the returned-QID mapping, then apply it to the case:

```sh
just pilot record-qids requests/REQUEST/case.json \
  requests/REQUEST/batches/001-execution-report.txt \
  --batch requests/REQUEST/batches/001-create.qs
just pilot record-qids requests/REQUEST/case.json \
  requests/REQUEST/batches/001-execution-report.txt \
  --batch requests/REQUEST/batches/001-create.qs --apply
```

The report must contain Wikidata item-creation history lines from one
QuickStatements 3.0 batch. The importer matches labels exactly against `CREATE`
commands in the submitted QS file and the case. It refuses ambiguous, unknown,
or conflicting matches. Preview is the default; `--apply` updates only matched
entities, and unreturned items remain marked `create`. Then run validation,
planning, and export again. The resolved QID is reused; the tool does not
create that entity again. Review each generated batch before submitting it.

Use `--partial` when applying a full batch report to a case that intentionally
contains only some of that batch's entities. The importer still verifies every
reported label against the submitted QS file, shows out-of-case results as
skipped, and refuses ambiguous labels.

`quickstatements-client` builds QuickStatements lines locally. The tool does not call its submission API. Keep backups of case files and review generated files as proposals, not completed edits.

## Limits and checks

Source verification records a source-check decision. The CLI checks evidence links and value syntax; it does not establish that an excerpt supports a claim or validate every Wikidata property constraint. Identifier searches use the Wikidata Query Service, whose results may lag recent edits. Title and author searches supply candidates rather than verified identity matches. Search failures stop the command and leave the case file unchanged.

Plans are additive proposals and snapshots for review. The exporter does not compute an execution history or remove statements. Multiple source records emit separate commands for the same claim, each with its own URL/date reference group. QuickStatements determines how those commands merge with existing statements. Relationships with a new item as a value or qualifier are deferred together until its QID is recorded.

Run `just check` for lint, strict type checks, offline tests with a 90% coverage gate, and isolated wheel installation. Exit codes are 0 for success, 1 for validation findings, and 2 for malformed input, file errors, or remote failures. QuickStatements command separators, embedded quotes, angle brackets, and control characters are rejected rather than escaped. In restricted environments, set `PYSTOW_HOME` to a writable directory: the QS library's dependency initializes that directory during import.

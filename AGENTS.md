# AGENTS.md

Instructions for AI coding assistants working in this repository.

## Project

`wikidata-pilot` prepares human-reviewed, evidence-backed Wikidata research and edit proposals. It does not write to Wikidata or perform autonomous LLM research. Preserve source URLs, retrieval dates, excerpts, locators, and claim-to-source links. Treat absence of search results as inconclusive. Keep creation staged: after submitting a creation batch, record returned QIDs as existing before exporting relationships.

Model creative works separately from editions. Prefer P1433 (`published in`) for story-to-collection relations when evidence supports it. Keep a work's first publication date distinct from a later anthology appearance date. The sample Bolo record and AbeBooks source are illustrative and unverified.

## Archetype and tooling

Python package using uv, just, Ruff, strict mypy, pytest, and GitHub Actions.

| Verb | Does |
|---|---|
| `just sync` | install locked dependencies |
| `just lint` | Ruff checks and formatting check |
| `just format` | apply Ruff formatting and safe fixes |
| `just type-check` | strict mypy on package and tests |
| `just test` | pytest with coverage gate |
| `just smoke-test` | build-install and invoke `wikidata-pilot --help` |
| `just check` | run all local quality checks, shellcheck, and smoke test |
| `just hooks-install` | install the pre-commit hook once per clone |
| `just pilot ARGS...` | run the CLI through uv with writable local caches |

Use only explicit, supported claim datatypes. Never submit QuickStatements automatically. Review the plan and the generated batch first.

## Request artifacts

Store each request under `requests/<request-name>/`. Keep its case, generated
plans, source downloads, QS batches, and execution reports together. Use
`case.json` for the working case and `batches/` for batch files and their case
snapshots. Number new batches and keep each execution report with its batch.
Do not overwrite submitted batches or their results. Draft plans may be
regenerated. Do not commit request files or force-add files from `requests/`.
The shared `data/wikidata_ids.json` cache and modeling guide remain tracked.

## Incremental case workflow

Use the `wikidata-research` skill in `.agents/skills/wikidata-research/` for
source research, identity decisions, and book or author field checklists.

From the repository root, inspect only the affected entities and their linked
sources. Read `docs/modeling.md` and check the local metadata cache before
external research. Verify support for every new claim, keep the requested
scope, then regenerate affected outputs once:

```sh
just pilot prepare requests/REQUEST/case.json --output requests/REQUEST/batches/001-create.qs
```

Preparation is offline by default. Add `--snapshot` when current item
statements matter or before submission; an offline plan is not a live check.
Review the plan, proposal JSON, and QS batch before manual submission.

## Wikidata access

Use Wikidata APIs for every Wikidata read through `just pilot`. Select the
operation and follow pagination in [docs/commands.md](docs/commands.md);
command help points to the relevant section. Do not browse item or property
HTML or `Special:WhatLinksHere`. Use browsing tools for external evidence.
Check local metadata and modeling guidance first. Inspect candidate identities
before proposing edits; query results can lag changes.
Set `WIKIDATA_PILOT_CONTACT` to an operator email or project URL before network
access, honor shared endpoint cooldowns, and use `--fresh` only to bypass the
short-lived candidate cache. See the API settings in `docs/commands.md`.

## Pilot a research case

1. Read the README case format and initialize a case with the CLI:

   ```sh
   just pilot init requests/REQUEST/case.json
   ```
2. Use browsing tools to inspect source pages. Record actual retrieval dates, supporting excerpts, locators, and claim-to-source links. Mark a source verified only after checking the material and each linked claim. Model memory and search snippets are insufficient evidence.
3. Search unresolved entities with `match`. Inspect candidate items, alternate titles, authors, and external identifiers before recording an identity decision. Keep uncertain matches unresolved and explain conflicts in the case.
4. Use `cache --find` for local QID/PID metadata lookup and `cache --case CASE` to fetch missing metadata. Keep `data/wikidata_ids.json` checked in. Names can match multiple IDs; metadata is not evidence or an identity decision. Use `--refresh` explicitly when metadata needs updating. Generate a plan with live snapshots. Review all additions, date precision, qualifiers, work/edition scope, and source support before exporting.
5. Export the reviewed case. The user submits the batch in QuickStatements. Record returned QIDs and retain the execution report before generating a subsequent batch.

Use `just pilot` for every CLI invocation. The top-level case object contains
`schema_version`, `title`, `sources`, and `entities`; see the README table for
each record's fields. Edit the structured case; do not hand-edit generated
commands to bypass validation.

## Git conventions

Do not use `git -C`. Use imperative commit headlines of at most 50 characters and a body explaining what changed and why. Include a `Changes:` list for substantial commits. An amend request means squash current changes into the previous commit and rewrite its message.

## Repository-specific exception

This repository intentionally has no `CLAUDE.md` compatibility symlink, at the owner's direction.

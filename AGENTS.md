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
| `just check` | run all local quality checks and smoke test |
| `just hooks-install` | install the pre-commit hook once per clone |

Use only explicit, supported claim datatypes. Never submit QuickStatements automatically. Review the plan and the generated batch first.

## Pilot a research case

1. Read the README case format and initialize a case with the CLI.
2. Use browsing tools to inspect source pages. Record actual retrieval dates, supporting excerpts, locators, and claim-to-source links. Mark a source verified only after checking the material and each linked claim. Model memory and search snippets are insufficient evidence.
3. Search unresolved entities with `match`. Inspect candidate items, alternate titles, authors, and external identifiers before recording an identity decision. Keep uncertain matches unresolved and explain conflicts in the case.
4. Generate a plan with live snapshots. Review all additions, date precision, qualifiers, work/edition scope, and source support before exporting.
5. Export the reviewed case. The user submits the batch in QuickStatements. Record returned QIDs and retain the execution report before generating a subsequent batch.

Use `uv run wikidata-pilot` for every CLI invocation. Edit the structured case; do not hand-edit generated commands to bypass validation.

## Git conventions

Do not use `git -C`. Use imperative commit headlines of at most 50 characters and a body explaining what changed and why. Include a `Changes:` list for substantial commits. An amend request means squash current changes into the previous commit and rewrite its message.

## Repository-specific exception

This repository intentionally has no `CLAUDE.md` compatibility symlink, at the owner's direction.

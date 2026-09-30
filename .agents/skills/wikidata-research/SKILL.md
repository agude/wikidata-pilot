---
name: wikidata-research
description: Researches books, stories, collections, editions, and authors for sourced Wikidata proposals. Use when identifying literary works or people, checking bibliographic facts, deciding which claims to add, or preparing a research case. Does not cover repository tooling changes or submit edits to Wikidata.
---

# Wikidata research

Produce an identity decision and source-backed claims within the user's scope.
Field lists are prompts to consider, not required fields or permission to
research unrelated facts. For a small addition, inspect the affected entity
and evidence rather than restarting the whole case.

## Choose the reference

- Read [books.md](references/books.md) for works, stories, collections, editions,
  publication history, and contents.
- Read [authors.md](references/authors.md) for author identity and biography.
- Use the repository's [modeling guide](../../../docs/modeling.md) for recorded
  modeling decisions, and [README](../../../README.md#case-format) when writing
  the case schema. Run commands from the repository root, three directories
  above this skill. Keep repository policy in [AGENTS.md](../../../AGENTS.md).

## Research

1. Identify the subject: person, work, collection, or edition. Read an existing
   case before creating another. Its top-level records are `sources` and
   `entities`. A story and a collection can share a title.
2. Check local labels and aliases with `just pilot cache --find "NAME"`.
   Reuse confirmed author QIDs as anchors when searching their linked works.
   Compare attribution, alternate titles, publication history, and identifiers.
   Use `match` for additional candidates and `inspect QID` to examine them.
   Neither a label match nor an empty search resolves identity; search results
   can lag recent creations. Record candidates and reasons for existing,
   create, or unresolved decisions.
3. Consult the relevant field checklist and existing modeling guidance. Research
   only missing facts needed for the request. Start with the text itself
   (title/copyright pages, contents, bylines), then publisher or author catalogs,
   library authority/catalog records, and specialist bibliographies. Retailer
   listings and search snippets supply leads; inspect the underlying source.
4. For each proposed claim, record the source URL, actual retrieval date,
   supporting excerpt, locator, and source ID. Check that the passage supports
   this entity and this claim, even when the source was verified for another
   fact. Preserve conflicting evidence in the resolution reason or source
   excerpts; leave unsupported claims out. Do not infer exact dates, literary
   form, or biography from titles, labels, model memory, or neighboring records.
5. Use the local conventions when applicable. Check Wikidata's current property
   definitions or project guidance for unfamiliar modeling or conflicting
   constraints. Metadata is a lookup aid, not evidence. Fetch newly encountered
   IDs with `cache --case CASE`; refresh metadata explicitly when needed.

## Record and review

Keep the working case, sources, and outputs in `requests/<request-name>/`,
which is ignored by Git. Reuse `case.json`; put numbered QS batches and their
case snapshots/results in `batches/`. Preserve submitted batches and results;
choose a new batch filename instead of overwriting them.

Write claims using the datatypes supported by the case schema. Match date
precision to the evidence. Unresolved identity decisions block export.
Relationships to new local targets are deferred until their QIDs are recorded.

```sh
just pilot prepare requests/REQUEST/case.json --output requests/REQUEST/batches/001-create.qs
```

Generate affected outputs once. Add `--snapshot` when existing statements
matter or before submission. Resolve validator findings and inspect the plan
and QS before handing them to the user. The tool checks structure, not whether
an excerpt proves a claim. Report supported additions, unresolved decisions,
and deferred relationships concisely. The user submits QS manually; record
returned QIDs before preparing subsequent batches.

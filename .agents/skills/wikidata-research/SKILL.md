---
name: wikidata-research
description: Researches books, stories, collections, editions, and authors for sourced Wikidata proposals. Use when identifying literary works or people, checking bibliographic facts, deciding which claims to add, or preparing a research case. Does not cover repository tooling changes or submit edits to Wikidata.
---

# Wikidata research

Use Wikidata APIs for all Wikidata reads. Do not browse item or property HTML
or `Special:WhatLinksHere`. Follow [API access](references/access.md) for
compact inspection, name searches, linked items, backlinks, and guidance.
Check local metadata and modeling guidance first. Use browsing tools for
external evidence, such as publisher catalogs and library records.

The JSON case records entities (people, works, collections, or editions) and
claims (proposed statements). Propose only facts supported by sources.
Field lists are optional prompts, not permission to research unrelated facts.
For a small addition, inspect only the affected entity and its linked evidence.

## Read the guidance

- Read [books.md](references/books.md) for works, stories, collections,
  editions, publication history, and contents.
- Read [authors.md](references/authors.md) for author identity and biography.
- Read the [guide to representing items](../../../docs/modeling.md) for local
  rules. Use the [README](../../../README.md#case-format) for the case format
  and follow [AGENTS.md](../../../AGENTS.md). Run commands with `just pilot`
  from the repository root, three directories above this skill.

## Research

1. **Identify the subject.** Read the existing case before creating another.
   Its top-level fields are `schema_version`, `title`, `sources`, and
   `entities`. A story and a collection can share a title; keep them distinct.
2. **Check possible matches.** Search cached names and aliases with
   `just pilot cache --find "NAME"`. Use confirmed author or editor Wikidata
   item IDs (QIDs) to search linked works. Use `just pilot match` to find
   candidates and `just pilot inspect QID` to examine them. Compare authors,
   alternate titles, publication history, and identifiers. A matching name does
   not confirm identity, and an empty search does not prove absence; results can lag new
   items. Record candidates and explain whether the subject matches an existing
   item (`existing`), needs a new item (`create`), or is uncertain (`unresolved`).
3. **Find evidence for missing facts.** Use the relevant checklist and local
   guidance. Research only facts needed for the request. Start with the text:
   title and copyright pages, contents, and bylines. Then check publisher or
   author catalogs, library records identifying people or editions, and
   specialist bibliographies. Treat retailer listings and search snippets as
   leads; inspect the source they point to.
4. **Document each proposed fact.** Record its source URL, actual retrieval date,
   supporting passage, source location (such as a page or section), and source
   ID. Link the fact to its source and confirm support for the subject and fact,
   even if the source was verified for another claim. Preserve conflicts in the match
   explanation or source excerpts. Omit unsupported claims. Do not infer exact
   dates, type of writing, or biography from titles, labels, model memory, or
   nearby records.
5. **Check how to represent the facts.** Follow local modeling rules. Check
   current property definitions or project guidance for unfamiliar relationships
   or conflicting rules. Cached labels and descriptions help identify IDs
   but are not evidence. Fetch metadata for new IDs with
   `just pilot cache --case CASE`; use `--refresh` when it needs updating.

## Record and review

Keep the case, source downloads, and outputs under the ignored
`requests/<request-name>/` directory. Reuse `case.json`. Save numbered
QuickStatements (QS) batches, case snapshots, and execution reports in
`batches/`. Never overwrite a submitted batch or its result; choose a new
filename for each later batch.

Use only value types supported by the case format. Match dates to the evidence:
year, month, or exact day. Resolve uncertain matches before preparing a batch.
Wait to export relationships to new items until their QIDs are recorded and
their case decisions are updated to `existing`.

For Google Knowledge Graph ID (P2671, `/g/`) and Freebase ID (P646, `/m/`)
additions, omit QuickStatements references: the identifier links to the entity
being identified. Confirm that the linked entity is the correct person or work,
including work/edition scope. Keep inspected source captures, URLs, retrieval
dates, excerpts, and identity decisions in the local case for review. The
exporter omits reference snaks for these two external-ID properties while
retaining evidence validation and qualifiers. Other claims keep references.

Prepare affected outputs once:

```sh
just pilot prepare requests/REQUEST/case.json --output requests/REQUEST/batches/001-create.qs
```

Add `--snapshot` when current statements matter or before submission. Resolve
validation findings, then review the plan, proposal JSON, and QS batch.
Validation checks the case format; it does not verify that a source supports a
fact.

To correct a submitted value, inspect the live statement and record the new
value in a new batch case. The exporter only adds statements. When
QuickStatements 3.0 supports the replacement, use `SWITCH_VALUE` in a separate
reviewed batch to preserve references. Do not leave both values in place.
See the [switch statement guide](https://meta.wikimedia.org/wiki/QuickStatements_3.0/Documentation/User_guide#Switch_statement).

Report supported additions, uncertain matches, and relationships waiting for
QIDs concisely. The user submits the batch manually. Record returned QIDs and
the execution report before preparing another batch.

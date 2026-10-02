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

## Use enough evidence for the requested entry

For a basic entry, collect enough evidence to identify the subject and support
its core statements, then stop. One suitable source can support several claims;
do not require multiple independent sources for routine title, authorship, or
publication facts. Optional biography, genre, dates, and identifiers do not
block a proposal when they are unknown; omit them unless requested.

Judge a source against the specific claim. Publisher pages, author websites,
interviews, podcasts, credits, library records, specialist bibliographies, and
retailer or community catalogs can support facts they explicitly document.
For example, an author interview can establish a pen name or authorship, and a
retailer listing can establish the listed edition's title and byline. Neither
automatically establishes an exact first-publication date or unrelated biography.
Prefer an accessible source that directly supports the fact; do not require
academic coverage, institutional catalogs, or book scans for every entry.

Inspect the relevant material and preserve the supporting excerpt and locator.
For podcasts, use checked episode notes, a transcript, or audio with a timestamp.
`verified` means the inspected material supports the linked claims; it does not
mean the source is authoritative for every fact. Search snippets remain leads.
If a passage is contradictory, implausible, or unclear, omit the affected claim
or check one targeted alternative. Do not reject an entire source category or
restart the whole case audit because one claim has weak support.

## Read the guidance

- Read [books.md](references/books.md) for works, stories, collections,
  editions, publication history, and contents.
- Read [authors.md](references/authors.md) for author identity and biography.
- Read the [guide to representing items](../../../docs/modeling.md) for local
  rules. Use the [README](../../../README.md#case-format) for the case format
  and follow [AGENTS.md](../../../AGENTS.md). Run commands with `just pilot`
  from the repository root, three directories above this skill.

## Collect evidence first

1. **Identify the subject.** Read the existing case before creating another.
   Its top-level fields are `schema_version`, `title`, `sources`, and
   `entities`. A story and a collection can share a title; keep them distinct.
2. **Find evidence for requested facts.** Use the relevant checklist and local
   guidance. Research only facts needed for the request. Start with an accessible
   source that directly supports the core facts. Use title and copyright pages,
   contents, bylines, publisher or author catalogs, interviews, or relevant
   bibliographic records as needed. An inspected retailer listing can support
   the edition facts it documents. Search snippets are leads to inspect.
3. **Document each proposed fact.** Record its source URL, actual retrieval date,
   supporting passage, source location (such as a page or section), and source
   ID. Link the fact to its source and confirm support for the subject and fact,
   even if the source was verified for another claim. Preserve conflicts in the match
   explanation or source excerpts. Omit unsupported claims. Do not infer exact
   dates, type of writing, or biography from titles, labels, model memory, or
   nearby records.
4. **Draft the case offline.** Follow local modeling rules and reuse cached
   property and item IDs. Keep unconfirmed identities `unresolved`. Save source
   excerpts and proposed claims before starting Wikidata matching. An unresolved
   case is a valid research artifact, though it cannot be exported.

For a source-collection request, stop here and report the evidence and gaps.
Do not run Wikidata searches, authority-ID lookups, or live snapshots unless
needed to answer the request. For a creation or edit proposal, continue below.

### Parallel source research

For two or more independent subjects, use multiple available Luna agents to
research in parallel, such as one agent per book. Assign each agent the subject,
requested facts, relevant local guidance, and a separate output path under
`requests/<request-name>/research/`. Each agent must inspect source material and
return URLs, actual retrieval dates, supporting excerpts, locators, proposed
facts, and conflicts or gaps. Use as many agents as the available slots allow;
process remaining subjects in later groups. If Luna agents are unavailable,
continue with the available research tools.

Keep source research separate from shared case updates. Agents save their own
findings; the coordinating agent checks claim support and work/edition scope,
merges the evidence into `case.json`, and performs the shared identity pass.
Do not have each agent repeat Wikidata matching, metadata updates, or snapshots.
Agent summaries and search snippets alone are not verified evidence.

## Check identities after collecting evidence

1. **Search once with the collected facts.** Check cached names and aliases with
   `just pilot cache --find "NAME"`. Put supported identifiers, alternate titles,
   and author hints in the case, then run `just pilot match CASE` once for the
   unresolved entities. Reuse saved candidates and prior confirmed decisions.
2. **Inspect plausible candidates together.** Use
   `just pilot inspect QID... --property PID...` for the properties needed to
   distinguish identity and work/edition scope. Save the output in the request
   directory and reuse it during drafting. Compare authors, alternate titles,
   publication history, and identifiers. A matching name does not confirm
   identity. Record the decision and its evidence as `existing`, `create`, or
   `unresolved`.
3. **Follow up only on a specific identity gap.** If the first pass cannot
   distinguish a candidate or misses an expected work, use a source-supported
   identifier, alternate name, or a confirmed author's linked works. An empty
   search does not prove absence; results can lag edits. Record search context
   and remaining uncertainty. Do not cycle through every available database or
   list an author's entire bibliography after identity is resolved. Leave
   ambiguous identities unresolved rather than forcing creation.
4. **Finish metadata and modeling checks.** Fetch missing metadata once with
   `just pilot cache --case CASE` after the claim set is stable. Use `--refresh`
   only when metadata needs updating. Consult current property definitions or
   project guidance for unfamiliar relationships or conflicting rules; reuse
   local guidance for covered cases. Metadata is not claim evidence.

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

Keep draft preparation offline. Add `--snapshot` once at final review before
submission when the batch adds claims to existing items, or earlier when a
specific decision depends on current statements. Repeat only if those
statements may have changed or the affected items change. Source corrections
and wording changes alone do not require another live snapshot. A creation-only
batch needs identity checks, but no snapshot of unrelated existing items.
Resolve validation findings, then review the plan, proposal JSON, and QS batch.
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

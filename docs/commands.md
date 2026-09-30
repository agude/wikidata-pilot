# Command reference

Run `just pilot COMMAND ...` from the repository root. `--help` lists syntax
and flags; this reference defines behavior. [README](../README.md) covers
installation and the case format. [Modeling](modeling.md) covers claim scope.

## Research commands

Read Wikidata through these APIs. Check local metadata and modeling guidance
first. Browse external sources to verify facts; do not browse Wikidata entity
HTML or `Special:WhatLinksHere`. Research commands print compact JSON without
saving files or updating the metadata cache. Store saved results under
`requests/<request-name>/`.

| Need | Command |
|---|---|
| Local label or alias matches | `cache --find "NAME"` |
| Name candidates | `search "NAME"` |
| Exact ISBN or authority ID | `identifier PID "VALUE"` |
| Candidate statements | `inspect ID... --property PID...` |
| Works by an author or contents of a collection | `linked QID --property PID` |
| Superclasses or instance classes | `ancestors QID` |
| QID for a Wikipedia page | `resolve SITE "TITLE"` |
| Incoming item-page links | `backlinks QID` |
| Recent edits | `history ID` |
| Community guidance | `page "TITLE"` |

### Pagination and evidence

`search`, `identifier`, `linked`, and `ancestors` return `next_offset`. Repeat
with the same arguments and `--offset VALUE` until it is null. `backlinks` and
`history` return `next_cursor`; repeat with `--cursor 'VALUE'` until null.
`--limit` accepts 1–50. Do not treat a first page as an exhaustive list.

SPARQL commands (`identifier`, `linked`, `ancestors`) use best-ranked direct
statements: deprecated statements are excluded, and preferred statements
suppress normal statements for that property. Results are sorted by entity
URI, not relevance or hierarchy depth. The query service and name search can
lag edits. Empty results do not prove absence. Inspect candidate records
before deciding identity; Wikidata statements do not replace source evidence.

## inspect

```sh
just pilot inspect Q48997316 Q724395 --property P31 P50 P577
just pilot inspect P123 --property P2302
```

Fetch 1–50 QIDs or PIDs in one entity API request. Duplicate IDs are fetched
once. One input returns a compact record; multiple inputs return
`{"entities": [RECORD, ...]}`. A missing requested record fails the command.

Output includes English labels, descriptions, aliases, and all claims by
default. `--property` selects claims; selected properties without statements
have empty lists. Statements retain IDs, ranks, qualifiers, separate reference
groups, time precision, and unknown or no-value statements. Labels for claim
properties and item values come from the local cache, with IDs as fallback.
`--cache PATH` selects that cache without updating it.

`--raw` returns the fetched API response, including sitelinks. It cannot be
combined with `--property`. Live plan snapshots retain full API responses.

## search

```sh
just pilot search "Keith Laumer"
just pilot search "publisher" --type property
```

Search English names and aliases. The default type is `item` and limit is 10.
Results contain IDs, labels, and descriptions; a matching name is a candidate,
not an identity decision.

## identifier

```sh
just pilot identifier P212 "9780441069972"
```

Find exact string or external-identifier values through SPARQL. The default
limit is 10. Values are escaped as string literals, including values shaped
like QIDs. Supply the representation Wikidata stores; the command does not
normalize ISBNs, remove punctuation, or check the property's datatype.
Inspect returned items to confirm edition or person identity.

## linked

```sh
just pilot linked Q724395 --property P50
```

Find items with the selected property pointing to the target QID. The default
limit is 50. Use P50 for an author's works, P629 for editions of a work, and
P1433 for items published in a collection. Confirm the target's identity and
scope before searching.

## ancestors

```sh
just pilot ancestors Q149537
just pilot ancestors Q724395 --instance-of
```

By default, follow one or more P279 (`subclass of`) links from a class. With
`--instance-of`, follow P31 (`instance of`) and then zero or more P279 links;
this includes the instance's immediate classes. The starting QID is excluded,
and the default limit is 50. Results describe recorded classifications; they
are not an automatic constraint check or evidence of literary form.

## resolve

```sh
just pilot resolve enwiki "Keith Laumer"
```

Resolve one page title on a Wikimedia wiki using its site ID, such as `enwiki`
or `frwiki`. Use the linked article's title; this command does not query the
source wiki to resolve article redirects. It requests Wikidata redirect
resolution. Output includes the requested title, returned sitelink title, QID,
English metadata, and redirect
information when supplied. A title without a linked item returns `id: null`.
This does not establish that the subject lacks a Wikidata item. Invalid site
IDs fail through the API; inspect a returned QID before recording identity.

## backlinks

```sh
just pilot backlinks Q1368527 --limit 10
```

List incoming item-page links, equivalent to the item links from
`Special:WhatLinksHere`. The default limit is 50. Links do not specify a
relationship; use `linked` when the property matters.

## history

```sh
just pilot history Q48997316 --limit 5
just pilot history P123
```

Read revision metadata for an item or property, newest first. The default
limit is 10. Results include revision and parent IDs, timestamps, users, and
edit comments when available. Hidden fields remain hidden. No historical
entity content or statement diff is fetched; comments alone do not prove what
changed. Missing records fail the command.

## page

```sh
just pilot page "Wikidata:WikiProject Books"
just pilot page "Wikidata:WikiProject Books" --section 0
```

Without `--section`, return heading indices and source pages. Select a numeric
index to fetch that section as wikitext; section 0 is the introduction. If a
heading comes from a transcluded page, list that reported page's headings and
select a numeric index there. Template indices such as `T-1` are unsupported.
The page revision is included when available.

Fetch only relevant sections. Record the guidance URL and retrieval date for
modeling decisions. Guidance defines conventions, not facts about a subject.

## Case commands

Keep cases and generated outputs in ignored request directories. See the
[case format](../README.md#case-format) and [review workflow](../README.md#quick-start).

## init

`init PATH` creates an illustrative case and its parent directory. It refuses
to overwrite a file. Replace or verify the unverified example evidence.

## match

`match CASE` searches unresolved entities and saves candidates in the case.
It checks exact identifiers before title and author candidates. It does not
resolve ambiguous identity or prove absence. Review candidates before recording
`existing`, `create`, or `unresolved` decisions.

## validate

`validate CASE` checks structure, evidence links, and resolution decisions.
It does not verify that a source passage supports a claim.

## plan

`plan CASE` writes Markdown and JSON proposals beside the case; `--output`
selects the Markdown path. `--snapshot` fetches current records for resolved
QIDs. Offline planning does not check current statements. `--cache` selects
metadata used for labels; planning does not update it.

## prepare

`prepare CASE --output PATH.qs` validates and writes the review plan, proposal
JSON, and staged QS batch. It is offline unless `--snapshot` is supplied.
Review all outputs before manual submission. Preserve submitted files and use
a new numbered batch path for later exports.

## export

`export CASE --output PATH.qs` writes staged QuickStatements without fetching
live records. Relationships to new items remain deferred until returned QIDs
are recorded. It does not submit, remove, or move Wikidata statements.

## cache

`cache --find "NAME"` returns all exact, case-insensitive local label and alias
matches. `cache ID...` and `cache --case CASE` fetch only missing metadata;
`--refresh` explicitly refetches selected entries. `--file` overrides the
tracked `data/wikidata_ids.json` default. Updates fail without saving partial
changes when an ID is missing or redirected. Metadata is a lookup aid, not
claim evidence.

## Failures

Exit codes: 0 for success, 1 for validation findings, 2 for malformed input,
file errors, or remote failures. A successful API read does not establish
identity or verify a proposed claim. No command submits edits to Wikidata.

## API sources

- [Wikibase API](https://www.mediawiki.org/wiki/Wikibase/API): entities, names,
  and sitelink resolution.
- [SPARQL tutorial](https://www.wikidata.org/wiki/Wikidata:SPARQL_tutorial):
  direct statements and hierarchy paths.
- [Backlinks](https://www.mediawiki.org/wiki/API:Backlinks),
  [revisions](https://www.mediawiki.org/wiki/API:Revisions), and
  [page parsing](https://www.mediawiki.org/wiki/API:Parsing_wikitext):
  links, history, and guidance sections.

# Wikidata API access

Read Wikidata through `just pilot` from the repository root. Check the local
metadata cache and modeling guide first. Use browsing tools for external
sources such as publisher catalogs, copyright pages, and library records.
Do not browse Wikidata item or property HTML or `Special:WhatLinksHere`.

## Select a command

| Need | Command | Result |
|---|---|---|
| Local ID metadata | `cache --find "NAME"` | All local label or alias matches; no network |
| Name candidates | `search "NAME"` | Item IDs, labels, descriptions |
| Property candidates | `search "NAME" --type property` | Property IDs, labels, descriptions |
| Statements on an item or property | `inspect ID --property PID...` | Selected claims and English metadata |
| Items with a relationship to a target | `linked QID --property PID` | Incoming best-ranked statements for that property |
| Incoming item-page links | `backlinks QID` | Item IDs; relationship unspecified |
| Guidance headings | `page "PAGE TITLE"` | Section indices, headings, source pages |
| Guidance text | `page "PAGE TITLE" --section INDEX` | Selected section as wikitext |

These commands print compact JSON without saving files. Save outputs only
when needed, under the current `requests/<request-name>/` directory.

## Search and inspect candidates

Start with a confirmed author QID to find linked works, then compare title,
author, publication history, and identifiers on candidate items:

```sh
just pilot cache --find "Keith Laumer"
just pilot linked Q724395 --property P50 --limit 10
just pilot inspect Q48997316 --property P31 P50 P577
```

For editions of a work, use `linked WORK_QID --property P629`. For contents
of a collection, use `linked COLLECTION_QID --property P1433`. Replace the
placeholder with a confirmed QID. These find relationships already recorded
on Wikidata; verify facts against external sources before proposing claims.

Name search and relationship queries return `next_offset`. Repeat the same
query with `--offset VALUE` until it is null. Backlinks return `next_cursor`;
repeat with `--cursor 'VALUE'` until it is null. Limits accept 1–50; defaults
are 10 for name search and 50 for relationship queries and backlinks. Do not
claim a list is complete after reading only its first page.

Relationship queries use the SPARQL API and best-ranked direct statements.
Deprecated statements are excluded; normal statements are excluded where a
preferred statement exists for that property. Search indexes and the query
service can lag edits. An empty result does not establish absence. Inspect
candidate items through the entity API before recording an identity decision.
Backlinks identify links without specifying the property; use `linked` when
the relationship matters.

## Inspect statement meaning and constraints

```sh
just pilot inspect P123 --property P2302
just pilot inspect Q48997316 --property P31 P123 P629
```

`inspect` returns English labels, descriptions, and aliases. Claim output
retains statement IDs, ranks, qualifiers, separate reference groups, date
precision, and unknown or no-value statements. Property and item labels come
from the local metadata cache when available; missing labels fall back to IDs.
An explicitly selected property with no statements returns an empty list.

Without `--property`, all claims are returned. Use `--raw` for the full fetched
API response, including sitelinks; it cannot be combined with `--property`.
Planning with `--snapshot` still retains full API payloads. Compact output is
for inspection, not a replacement for source verification or identity review.

## Read community guidance

```sh
just pilot page "Wikidata:WikiProject Books"
```

Find the required heading in `sections`, then run the command with its numeric
`index` as `--section`. Section 0 returns the introduction. Fetch only sections
needed for the decision. If a heading comes from a transcluded page, use its
reported `page` to list that page's sections and select a numeric index there.
Do not pass template section tokens such as `T-1` to `--section`.

The result includes the page revision when supplied by the API. Record the
page URL and actual retrieval date when guidance informs a modeling decision.
A guidance page establishes modeling conventions; it does not verify a fact
about a book or author.

## API references

- [Wikibase API](https://www.mediawiki.org/wiki/Wikibase/API): entity retrieval
  and name search.
- [Wikidata data access](https://www.wikidata.org/wiki/Wikidata:Data_access):
  structured queries and endpoint selection.
- [Backlinks API](https://www.mediawiki.org/wiki/API:Backlinks): incoming links
  and continuation.
- [Parsing wikitext](https://www.mediawiki.org/wiki/API:Parsing_wikitext):
  section text and page revisions.
- [TOC data](https://www.mediawiki.org/wiki/API:Parsing_wikitext/TOCData):
  heading indices and transcluded source pages.

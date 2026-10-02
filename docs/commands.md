# Command reference

Run `just pilot COMMAND ...` from the repository root. `--help` lists syntax
and flags; this reference defines behavior. [README](../README.md) covers
installation and the case format. [Modeling](modeling.md) covers claim scope.

## Research commands

Read Wikidata through these APIs. Check local metadata and modeling guidance
first. Browse external sources to verify facts; do not browse Wikidata entity
HTML or `Special:WhatLinksHere`. Research commands print compact JSON without
saving request artifacts or updating tracked metadata. Store saved results under
`requests/<request-name>/`.

### API access

Set `WIKIDATA_PILOT_CONTACT` to a real operator email address or project URL
before a request needs the network. The value is included in the versioned
User-Agent. A cache hit and offline commands do not require contact settings.
No contact value is built into the package.

`just pilot` and `bin/pilot` load a repository-root `.env` file when present.
Use it for `WIKIDATA_PILOT_CONTACT` and `GOOGLE_KG_API_KEY`. The file is ignored
by Git; existing shell environment values take precedence. uv parses the file
as environment assignments, without executing shell commands. `google-kg`
uses `GOOGLE_KG_API_KEY` for its default API backend.

`just pilot` stores shared endpoint locks, cooldown timestamps, and candidate
results in the ignored `.wikidata-pilot-state/` directory. Set
`WIKIDATA_PILOT_STATE_DIR` to use another writable directory. Direct calls to
`bin/pilot` use the same repository state directory even when run from another
working directory. An installed console script outside the repository uses
`$XDG_CACHE_HOME/wikidata-pilot` (or `~/.cache/wikidata-pilot`). Processes on
the same machine share coordination only when they use the same state
directory. State does not coordinate across machines. The OS releases a lock
when its process exits, including an interrupted process.

Requests to each API endpoint are serialized across CLI processes that use the
same state directory. Action API reads send `maxlag=5`. Both endpoints use a
20-second HTTP timeout and request compressed responses. The client makes at
most three attempts per HTTP request and waits at most 120 seconds for
cooldowns and locks combined; network response time is separate. It honors
`Retry-After` seconds and HTTP dates. A headerless 429 uses exponential backoff
starting at five seconds with jitter. A recognized outage message waits at
least 60 seconds. A 503 is retried only when it includes `Retry-After` or
identifies `maxlag`; query timeouts and other 503 responses fail without
retry. HTTP 200 Action API `maxlag` errors are retried. Wait messages on stderr
state that the script will continue automatically. Cooldowns are saved before
waiting, including after the last attempt. When retries are exhausted or a
requested delay exceeds the wait budget, the error states that the script is
exiting and gives the time after which to rerun the command.

Successful `search`, `identifier`, `linked`, and `ancestors` candidate results
are cached for five minutes, with a maximum of 128 entries. Expired entries
are removed when a result is written. `--fresh` bypasses this candidate cache;
it still honors shared locks and server cooldowns. Inspection, metadata
refresh, guidance, revision history, and snapshots always fetch current API
data.

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

Relationship SPARQL commands (`linked`, `ancestors`, and `identifier` for
P1433/P2860) use best-ranked direct statements: deprecated statements are
excluded, and preferred statements suppress normal statements for that
property. Results are sorted by entity URI, not relevance or hierarchy depth.
The query service and Action API search index can lag edits. Empty results do
not prove absence. Inspect candidate records before deciding identity;
Wikidata statements do not replace source evidence.

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
not an identity decision. Successful pages are cached for five minutes. Add
`--fresh` to bypass the candidate cache.

## identifier

```sh
just pilot identifier P212 "9780441069972"
```

Find candidate string or external-identifier values with the Action API
`haswbstatement` search. The default limit is 10. The search index is
case-insensitive and may lag edits, so the command batch-inspects hits and
returns only case-sensitive exact values from best-ranked statements:
deprecated statements are excluded, and preferred statements suppress normal
statements for that property. Search offsets preserve the API continuation,
even when verification filters every result from a page. The index currently
omits P1433 (`published in`) and P2860 (`cites`); those properties use direct
SPARQL relationship queries and require a QID value. No throttling error
triggers automatic SPARQL fallback. Supply the representation Wikidata stores;
the command does not normalize ISBNs, remove punctuation, or check the
property's datatype. Add `--fresh` to bypass the candidate cache. Inspect
returned items to confirm edition or person identity.

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

## google-kg

`google-kg` searches Google's Knowledge Graph API for identifier candidates and
writes a Markdown review report, JSON report, and saved responses with source
metadata. It does not accept matches, change a case, or export statements.
Every candidate requires identity review: results can include namesakes,
related people, other books, editions, and carousels.

Set `GOOGLE_KG_API_KEY` in the repository-root `.env` or shell. The default
`--backend api` needs no browser. Requests send the key only in the
`X-Goog-Api-Key` header; response echoes of the key are redacted before saving.
Errors never print request headers or transport exception details.

Use `--backend browser` for Google Search scraping. Install its browser once
after `just sync`:

```sh
PLAYWRIGHT_BROWSERS_PATH="$PWD/.wikidata-pilot-state/browsers" \
  UV_CACHE_DIR="$PWD/.uv-cache" uv run playwright install chromium
```

For example, with the Falcorian operator identity:

```sh
export WIKIDATA_PILOT_CONTACT=https://www.wikidata.org/wiki/User:Falcorian
just pilot google-kg --qids-file /tmp/missing-google-kg-qids.txt \
  --max-items 3 --output requests/google-kg-trial/google-kg
just pilot google-kg requests/REQUEST/case.json
```

Supply exactly one case, `--qids QID...`, or `--qids-file PATH` (whitespace
separated QIDs). Case input selects resolved existing entities and retains
author search hints. `--output DIRECTORY` is required for QID inputs; a case
defaults to `google-kg/` beside the case. `--max-items` defaults to 10 and limits
selected unique QIDs before network access. Wikidata context is fetched in
batches, with author labels fetched once for search hints.

Items with an existing non-deprecated P2671 value are marked `already_present`.
Other P2671 statements, including deprecated values and unknown/no-value
statements, are marked `identifier_review`. Neither status triggers a Google
search. P646 is preserved for comparison and does not exclude an item from
searching for a missing P2671. `/g/` candidates map to P2671 and `/m/` candidates
map to P646. An existing `/m/` value is already a Google-compatible identifier;
Google need not also expose a `/g/` ID for that entity.

The API backend makes one English query per selected item that needs a lookup,
with `--limit` candidates (default 5, range 1–20). People explicitly classified
with P31 Q5 use Google's `Person` filter; other items have no type filter.
Requests use a 20-second timeout and the same minimum 10-second pause between
lookups. HTTP errors, API errors, malformed responses, and network failures
stop further live requests, without automatic retries. Empty candidate lists
are `no_candidates` and remain inconclusive.

API candidates retain name, description, types, website, detailed description,
result score, and JSON locators with excerpts. Scores describe search relevance
and never establish identity. Raw responses use `.response.json` files under
`raw/`; adjacent metadata records the request URL without credentials, query,
backend, and retrieval timestamp. API and browser caches are separate. Changing
the candidate limit or type filter also requires a separate API request.

The browser backend opens a separate Chromium browser, uses English search
pages, and waits two seconds for each page to render. `--headed` shows its window. It sends
one search per selected item with a label, adding the first known author when
available. `--delay SECONDS` sets the pause between searches and must be at least
10 seconds. HTTP errors, consent pages, CAPTCHA pages, and JavaScript
interstitials stop further live searches. They are reported as `blocked`, never
as evidence that an entity lacks an ID. Browser failures are `failed`;
unattempted items remain `not_attempted`. Any of these statuses gives exit code
2; candidate and empty-result reports give exit code 0. A live browser or file
failure also stops further live requests; saved-page failures leave other page
pairs available for processing.

Rendered HTML is parsed for `data-kpid`, `data-entityid`, Google search links
with `kgmid`, and `g.co/kg/` entity links. Candidate JSON retains each
occurrence's attribute, excerpt, and HTML line/column locator. Review the
saved HTML and open candidate links to distinguish the searched entity from
related entities. Ordinary pages without extracted IDs are `no_candidates`,
which remains inconclusive. Search queries, current Wikidata statements,
source URLs, capture times, and existing-ID comparisons remain in the report.

Non-blocked responses are reused for the same QID and request for 24 hours.
`--fresh` fetches again. Draft reports may be regenerated; every capture gets a
new filename under `raw/`, preserving earlier evidence. Source pages may
contain unrelated search content; request artifacts remain untracked.

To parse pages saved from a regular browser, use `--saved-pages DIRECTORY`,
which selects the browser backend unless `--backend` is supplied explicitly.
For each selected item that needs a search, supply `QID.html` and `QID.json`.
The JSON must record the actual source URL and retrieval date or timestamp:

```json
{"url": "https://www.google.com/search?q=Example&hl=en", "retrieved": "2026-10-01"}
```

Saved-page mode makes no Google requests, but still checks current Wikidata
context. Missing or invalid page pairs are reported as failures. Resolve
browser consent or access issues manually before saving pages; rerunning the
command does not bypass those restrictions.

After identity review, add accepted IDs and their supporting evidence to the
structured case. Use `prepare --snapshot` for the final review and submit the
generated batch manually.

## init

`init PATH` creates an illustrative case and its parent directory. It refuses
to overwrite a file. Replace or verify the unverified example evidence.

## match

`match CASE` searches unresolved entities and saves candidates in the case.
It checks exact identifiers before title and author candidates. It does not
resolve ambiguous identity or prove absence. Review candidates before recording
`existing`, `create`, or `unresolved` decisions.

## record-qids

`record-qids CASE REPORT --batch PATH.qs` previews QID assignments from saved
Wikidata item-creation history lines. It accepts lines that identify a new item
by label and QID and include a QuickStatements 3.0 batch number. It verifies
that each label appears exactly once in both the submitted QS file's `CREATE`
commands and the case. Unknown labels, duplicate labels, conflicting QIDs, and
reports containing multiple batches stop the command.

Preview is the default. Review the mapping, then add `--apply` to update matched
case entities to `existing`. Existing matching QIDs are left unchanged;
creation results absent from the report remain marked `create`. The command
does not make network requests or submit edits. Use `--partial` to apply a
full-batch report to a case containing only some of its entities. Out-of-case
results must still match a `CREATE` label in the supplied QS file and are shown
as skipped; ambiguous case labels remain errors.

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

P2671 and P646 external-ID claims are exported without reference snaks because
the identifiers link to the entity. Keep verified evidence and identity
decisions in the case; evidence validation and qualifiers still apply.

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

- [API etiquette](https://www.mediawiki.org/wiki/API:Etiquette/en),
  [User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy),
  and [maxlag](https://www.mediawiki.org/wiki/Manual:Maxlag_parameter):
  client identification and server load handling.
- [WikibaseCirrusSearch statement search](https://www.mediawiki.org/wiki/Help:Extension:WikibaseCirrusSearch):
  `haswbstatement` syntax, case behavior, and excluded properties.
- [WDQS query limits](https://www.mediawiki.org/wiki/Wikidata_query_service/User_Manual#Query_limits):
  limits for relationship and hierarchy queries.
- [Wikibase API](https://www.mediawiki.org/wiki/Wikibase/API): entities, names,
  and sitelink resolution.
- [SPARQL tutorial](https://www.wikidata.org/wiki/Wikidata:SPARQL_tutorial):
  direct statements and hierarchy paths.
- [Backlinks](https://www.mediawiki.org/wiki/API:Backlinks),
  [revisions](https://www.mediawiki.org/wiki/API:Revisions), and
  [page parsing](https://www.mediawiki.org/wiki/API:Parsing_wikitext):
  links, history, and guidance sections.

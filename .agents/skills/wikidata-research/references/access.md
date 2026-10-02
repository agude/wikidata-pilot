# Wikidata API access

Read Wikidata through `just pilot`. Use the repository's
[command reference](../../../../docs/commands.md#research-commands) to select
an operation and follow pagination. Each command's `--help` points to its
reference section.

Collect external evidence and draft the case before matching identities on
Wikidata. Source collection can finish with unresolved identities and needs no
live snapshot. For proposals, run one matching pass, batch candidate inspection,
and reuse saved results. Use relationship queries only for a specific unresolved
identity or requested relationship. Fetch a live snapshot at final review when
adding claims to existing items; do not repeat it for source-only revisions.

Check local metadata and modeling guidance first. Do not browse Wikidata
entity HTML or `Special:WhatLinksHere`. Browse external sources to verify
facts. Inspect candidate identities before recording a match; empty searches
do not prove absence. Save research outputs under the request directory.

# API etiquette implementation plan

Make API requests identifiable, serialized, and bounded. Reduce repeated
candidate searches while keeping item inspection and submission snapshots
fresh. No API account or automatic Wikidata writes are required.

## Implementation

1. Add a shared HTTP request layer for Action API and SPARQL reads. Serialize
   requests to each endpoint across CLI processes with OS file locks. Store
   cooldown timestamps and temporary query results in an ignored local state
   directory; allow an environment override. Use atomic state writes and
   recover safely from interrupted processes. Never hold a stale lock based
   only on a PID file.
2. Handle 429, retryable 503, and Action API `maxlag` errors, including HTTP
   200 responses. Honor `Retry-After` seconds or HTTP dates. Otherwise use
   exponential backoff starting at five seconds with jitter. The reported
   outage rule requires at least 60 seconds. Persist cooldowns before waiting,
   including on the final failed attempt. Do not retry malformed queries,
   other permanent errors, or expensive query timeouts indiscriminately.
   Limit requests to three attempts and waiting to 120 seconds per HTTP request;
   if a server delay exceeds the remaining budget, retain it and exit with
   an actionable cooldown message. Print wait diagnostics to stderr only.
3. Build the User-Agent from the package version and a configurable real
   operator contact or project URL. Do not invent a URL or email. Contact
   is supplied through `WIKIDATA_PILOT_CONTACT`; fail clearly on network use
   when absent, while allowing offline commands and valid candidate cache hits.
   Add `maxlag=5` to background Action API reads. Keep the 20-second request
   timeout and compressed responses.
4. Cache successful candidate searches for five minutes in the local state
   directory, keyed by endpoint and all query parameters. Never cache errors.
   Keep entity inspection, metadata refresh, guidance, history, and submission
   snapshots fresh. Provide an explicit cache bypass for candidate commands.
   Bound cache growth and expire old entries; do not put response caches in
   the tracked QID/PID metadata file. Retain existing batch inspection.
5. Route string/external-ID lookups through Action API `haswbstatement`
   search, then batch-inspect candidates and verify case-sensitive exact
   values. Escape search syntax safely. Preserve raw search continuation
   offsets even when verification filters out candidates. Verify statement
   ranks according to documented semantics. Avoid automatic SPARQL fallback
   on throttling. Keep SPARQL for unsupported properties (P1433/P2860),
   hierarchy traversal, and current relationship queries. Document any
   search-index limitations and do not normalize ISBNs silently.
6. Update docs/commands.md with configuration, cache freshness, retry budgets,
   cooldowns, identifier behavior, and authoritative source links. Keep CLI
   help concise and linked to that reference. Update AGENTS.md with a short
   instruction to honor cooldowns and use the documented settings. Preserve
   the user's existing skill, author/book reference, and metadata edits.

## Verification

Use mocked responses and clocks for Retry-After forms, bounded retries,
429/503/maxlag handling, permanent failures, cache hit/expiry/bypass, and
fresh snapshots. Test cross-process serialization and cooldown persistence,
including process exit while holding a lock. Test identifier escaping,
case-sensitive verification, missing/redirected candidates, continuation
when a page filters to zero results, and statement rank handling.

Run repository lint, strict type checks, the coverage gate, package smoke
test, and documentation link checks. Do not probe the throttled endpoint to
validate retry behavior. Review changes before committing only task files.

## Sources

- [Action API etiquette](https://www.mediawiki.org/wiki/API:Etiquette/en)
- [WDQS limits](https://www.mediawiki.org/wiki/Wikidata_query_service/User_Manual#Query_limits)
- [Wikimedia rate limits](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits)
- [User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy)
- [Maxlag](https://www.mediawiki.org/wiki/Manual:Maxlag_parameter)
- [Statement search](https://www.mediawiki.org/wiki/Help:Extension:WikibaseCirrusSearch)

## Completion

Implemented by a Luna agent and reviewed by the parent session. Coordination
uses Python standard-library `fcntl.flock` on Linux. The runner shares an
ignored repository state directory; other local processes coordinate only
when configured to use the same directory. No contact was invented or account
created. Retry behavior is verified with mocked responses and process tests.

# Reduce repeated agent setup and research

## Scope

Make small, sourced edits predictable for a fresh agent session. Reuse local ID metadata and recorded modeling decisions. Keep evidence verification, explicit identity decisions, and manual QuickStatements submission.

## Implementation

1. Add `bin/pilot` and a `just pilot` entry point. Use uv and writable repository-local cache directories by default, preserve explicit environment overrides, and forward arguments without losing spaces. Keep these cache directories ignored. Make `just check` and hooks use writable caches too.
2. Add `docs/modeling.md`, with linked primary Wikidata sources and a verification date. Cover work versus edition or collection, story-to-collection relationships, literary form versus broad instance classification, and original versus later publication dates. Document the novella example as a repository convention supported by the property definitions, not a universal requirement. Recheck when the case has conflicting evidence or falls outside the guide.
3. Add `prepare CASE --output PATH.qs [--snapshot] [--cache PATH]`. Validate and render a plan, structured proposal, and staged QS from the same case. Default to offline planning. Validate evidence, path collisions, cache input, and QS construction before writing any outputs. Use existing plan naming beside the case. Report deferred claims. Leave existing commands compatible. Do not edit the case or fetch metadata implicitly.
4. Update AGENTS.md and README. Put exact entry commands and the top-level `entities` schema where agents see them. For incremental changes, read only affected entities and sources, consult metadata and modeling guidance before external research, verify support for each new claim, keep the requested scope, and regenerate affected outputs once. Use live snapshots when current statements matter or before submission; do not imply an offline plan is a live check.
5. Test argument forwarding, environment overrides, offline preparation, snapshot opt-in, validation failures, collision prevention, and unchanged inputs. Run `just check` and the repository standards audit.

## Completion criteria

A fresh agent can find the novella convention locally, inspect an existing case without guessing its schema, and regenerate review outputs and QS with one command. No external writes occur. Existing research files and metadata changes from another session remain untouched.

# Authors

Use this checklist to identify a person or research requested biographical
facts. A book request does not become a biography request because author
fields are missing.

## Identify the person

Collect the source byline and identity evidence first. Reuse a supplied or
previously confirmed Wikidata item ID (QID) as a matching lead. For people with
the same name, compare credited works, dates, pen names, and library records.
A matching name or occupation is insufficient. Make sure each record describes
this person, not a namesake, organization, or several people together. Use the
confirmed QID to search linked works when a requested work remains unresolved.

Publisher or author biographies, interviews, podcasts, credits, and library
records can support the name, authorship, or occupation they explicitly document.
A suitable source for these core facts is enough for a lean author proposal;
do not require a full biography or an authority record. Use checked podcast
notes, a transcript, or audio with a timestamp. Record evidence for each
proposed fact. Preserve conflicting
dates; do not average them or silently choose the more precise one. Omit
missing dates.

When creating a person item, use authority IDs found in the consulted sources
to help check identity. Search another authority database when a specific
identity conflict remains or the user requests those IDs. For specialist
databases such as ISFDB, follow the author's
profile from a known work when possible and compare its bibliography with the
source byline. Treat name-search results as leads. Add an ID only when the
records identify the same person; cite the profile or ID record and the
supporting identity evidence. An empty search, timeout, rate limit, or
unavailable page does not establish that no ID exists.

## Fields to consider

| Field | Property / case field | Evidence to check |
|---|---|---|
| Name and identification | `label`, `description` | Established name and supported description |
| Person type | P31 = Q5 | Person, not an organization or an identity shared by several people |
| Occupation | [P106](https://www.wikidata.org/wiki/Property:P106) | Explicit occupation |
| Pen name | [P742](https://www.wikidata.org/wiki/Property:P742) | Source linking the name to the person |
| Birth / death | [P569](https://www.wikidata.org/wiki/Property:P569) / [P570](https://www.wikidata.org/wiki/Property:P570) | Supported date and precision |
| Citizenship | [P27](https://www.wikidata.org/wiki/Property:P27) | Explicit citizenship; language or residence is insufficient |
| Authority ID | [P214](https://www.wikidata.org/wiki/Property:P214), [P213](https://www.wikidata.org/wiki/Property:P213), [P244](https://www.wikidata.org/wiki/Property:P244), [P227](https://www.wikidata.org/wiki/Property:P227), [P1233](https://www.wikidata.org/wiki/Property:P1233) | VIAF, ISNI, LCCN, GND, or ISFDB for speculative-fiction authors |

## Record the facts

Use the value types in the [README](../../../../README.md#case-format): item
IDs for person type, occupation, and citizenship; strings for pen names; time
values for birth and death; external IDs for authority records. The case's
`identifiers` map helps find matches; add a separate sourced claim when
proposing an ID. Put P50 on the authored work, pointing to the person. A pen
name alone does not justify a second person item. Collect alternative names
for identity checks. The tool does not export them, so do not add an `aliases`
case field.

Property uses were checked on 2026-09-29 against the linked definitions.
Check current rules for shared pen names or conflicting library records.

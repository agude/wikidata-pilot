# Authors

Use this checklist for person identity or requested biographical additions.
Do not expand a book task into a biography task because an author lacks fields.

## Resolve the person first

Start with a supplied or previously confirmed QID. For namesakes, compare
credited works, dates, pseudonyms, and authority records. A matching name or
occupation is insufficient. Confirm that an authority record describes this
person rather than a namesake, organization, or combined record. The confirmed
QID anchors subsequent searches for the author's works.

Prefer publisher/author biographies, library authority records, and reliable
biographical references. Record support for each proposed fact. Preserve
conflicting dates; do not average them or silently choose the more precise
source. Leave missing dates out.

## Fields to consider

| Field | Property / case field | Evidence to check |
|---|---|---|
| Name and identification | `label`, `description` | Established name and supported description |
| Human classification | P31 = Q5 | Person, not a shared persona or organization |
| Occupation | [P106](https://www.wikidata.org/wiki/Property:P106) | Explicit occupation |
| Pseudonym | [P742](https://www.wikidata.org/wiki/Property:P742) | Source linking the name to the person |
| Birth / death | [P569](https://www.wikidata.org/wiki/Property:P569) / [P570](https://www.wikidata.org/wiki/Property:P570) | Date and supported precision |
| Citizenship | [P27](https://www.wikidata.org/wiki/Property:P27) | Explicit citizenship; language/residence is insufficient |
| Authority identifier | [P214](https://www.wikidata.org/wiki/Property:P214), [P213](https://www.wikidata.org/wiki/Property:P213), [P244](https://www.wikidata.org/wiki/Property:P244), [P227](https://www.wikidata.org/wiki/Property:P227) | VIAF, ISNI, LCCN, or GND identity record |

Classification, occupation, and citizenship use item values; pseudonyms use
strings; dates use time; authority identifiers use external IDs. The case's
`identifiers` map supplies search hints; add sourced claims separately when
proposing identifiers for Wikidata. P50 belongs on the authored work, pointing
to the person. A pen name alone does not justify creating a second person.
Collect alias evidence for identity checks; the current exporter does not emit
aliases, so do not add an `aliases` case field.

Property roles checked 2026-09-29 against the linked Wikidata definitions.
Inspect current constraints for shared pseudonyms or conflicting authority records.

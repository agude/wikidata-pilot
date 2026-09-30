# Books, stories, collections, and editions

Consider fields relevant to the request; omit unsupported facts. A catalog
record for an edition does not establish every fact about the underlying work.

## Find the evidence

Start from a confirmed author's QID and search linked works. Compare alternate
titles and identifiers. Check title and copyright pages, contents, and bylines.
Publisher catalogs help identify contents and form; library records identify
editions. Specialist bibliographies can establish earlier appearances. Record
which version each source describes. A contents list establishes inclusion,
not necessarily first publication, authorship, or literary form.

## Fields to consider

| Subject | Field | Property | Evidence to check |
|---|---|---|---|
| Work or collection | Classification | P31 | Subject scope; see the modeling guide |
| Work | Title / subtitle | P1476 / P1680 | Published wording and language |
| Work | Author | P50 | Attribution and person identity |
| Work | Literary form | P7937 | Explicit classification, such as novella |
| Work | Genre | P136 | Sourced genre, separate from form |
| Work | Original language | [P407](https://www.wikidata.org/wiki/Property:P407) | Language of the original |
| Work | First publication | [P577](https://www.wikidata.org/wiki/Property:P577) | Earliest supported appearance and precision |
| Story | Published in | P1433 | Specific containing collection or edition |
| Story relationship | Contents order | [P1545](https://www.wikidata.org/wiki/Property:P1545) qualifier | Order in that contents list |
| Edition | Edition of | P629 | Underlying work identity |
| Edition | Publication date / place | P577 / P291 | Edition-specific imprint |
| Edition | Publisher | P123 | Imprint organization, not retailer |
| Edition | ISBN | P212 / P957 | ISBN-13 / ISBN-10 of that edition |
| Relevant item | Editor / translator | P98 / P655 | Explicit role and work/edition scope |

Item values need QIDs or local entity keys. Titles/subtitles use monolingual
text; dates use time; ISBNs use external IDs; contents order uses a string
qualifier. Use the case schema rather than adding field names as new keys.

## Modeling and stopping

Keep works, editions, and same-title collections distinct. A later anthology
date does not replace a story's first publication date. Consult the
[modeling guide](../../../../docs/modeling.md) for local conventions. Stop when
the requested claims have support or a documented conflict, rather than filling
every row.

Property roles checked 2026-09-29 against
[WikiProject Books](https://www.wikidata.org/wiki/Wikidata:WikiProject_Books) and
linked definitions. Consult current guidance for cases outside these conventions.

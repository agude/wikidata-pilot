# Books, stories, collections, and editions

A work is the creative text; an edition is a particular published version.
Research only fields relevant to the request and omit unsupported facts. An
edition's catalog record does not establish every fact about the work.

## Find evidence

Start with a confirmed author or editor QID and search linked works. Compare
alternate titles and identifiers. Check title and copyright pages, contents,
and bylines. Publisher catalogs help identify contents and type of writing;
library records identify editions; specialist bibliographies can establish
earlier appearances. Confirm which version each source describes. A contents
list establishes inclusion; it does not necessarily establish first
publication, authorship, or type of writing.

For large reviews of scans across several volumes, use available Luna agents
to read separate books in parallel. Use text recognition (OCR) to find pages,
then verify names, titles, credits, identifiers, and numbering in the images.
When the print is ambiguous, treat OCR and other agents' transcriptions as
leads. A prologue or other front matter may precede the first story; check its
byline, layout, and transition to the next title before creating a separate
work. Keep order qualifiers aligned with the contents list; do not add
placeholder stories to fill number gaps.

When titles differ between a cover, title page, copyright page, publisher
catalog, or in-book series list, record each useful wording and its location.
Explain which one you use as the work title; do not silently combine them.
Keep a series name and number separate from the title unless the source
includes them in it. Check membership of a numbered series or subgroup before
treating it as the same as a broader series or franchise.

## Fields to consider

Publisher claims belong on editions. Wikidata's [P123 conflict
constraint](https://www.wikidata.org/wiki/Property:P123#constraints) excludes
items typed as literary work (`Q7725634`) or written work (`Q47461344`). Do
not add a publisher to those items or change their type to bypass the rule.

Identify the edition described by the source and search for an existing item.
If none matches and the evidence supports a new item, record a separate
edition with:

- `P31 = Q3331189` (version, edition, or translation).
- `P123 =` the confirmed publishing house QID.
- `P629 =` the underlying work QID or its local case key.

Keep the work separate. If the source does not identify an edition, omit the
publisher claim and record what remains uncertain. Relationships to new items
wait until their QIDs are recorded. An existing publisher statement on a work
needs review; the tool cannot delete or move statements automatically.

| Subject | Field | Property | Evidence to check |
|---|---|---|---|
| Work or collection | Item type | P31 | What the item represents; see the modeling guide |
| Work | Title / subtitle | P1476 / P1680 | Published wording and language |
| Work | Author | P50 | Credited author and confirmed identity |
| Work | Type of writing | P7937 | Explicit description, such as novella |
| Work | Genre | P136 | Sourced genre, distinct from type of writing |
| Work | Original language | [P407](https://www.wikidata.org/wiki/Property:P407) | Language of the original |
| Work | First publication | [P577](https://www.wikidata.org/wiki/Property:P577) | Earliest supported appearance and date detail |
| Story | Published in | P1433 | Specific containing collection or edition |
| Story | Contents order | [P1545](https://www.wikidata.org/wiki/Property:P1545) | Order in that contents list |
| Work | Edition or translation | P747 | Specific existing edition |
| Edition | Edition of | P629 | Confirmed underlying work |
| Edition | Publication date / place | P577 / P291 | Edition's imprint |
| Edition | Publisher | P123 | Named publisher, not retailer |
| Edition | Cover artist | P110 | Credit for that edition's cover; can differ between editions |
| Edition | ISBN | P212 / P957 | ISBN-13 / ISBN-10 for that edition |
| Relevant item | Editor / translator | P98 / P655 | Explicit role and work or edition scope |

When an edition links to a work with P629, inspect the work for P747. Add a
missing P747 only when current property rules call for it and the source
identifies that edition. Check live statements first.

Use the value types in the [README](../../../../README.md#case-format): QIDs or
local entity keys for item values, text with a language for titles and
subtitles, time values for dates, and external IDs for ISBNs. Record contents
order as a text qualifier attached to the relationship. Do not add checklist
labels as case fields.

## ISBNs

Keep ISBN-10 grouping hyphens in P957, such as `0-671-72184-4`; omitting them
can trigger a format warning. To derive ISBN-13 from ISBN-10, prefix `978` to
the first nine digits and calculate a new check digit; never reuse the ISBN-10
check digit. Verify both check digits and prefer a printed ISBN-13. Books
first published from 2007 onward use ISBN-13, including `979` prefixes; use
the printed ID instead of synthesizing ISBN-10.

## Represent the facts and stop

Keep works, editions, and collections with the same title distinct. A later
anthology appearance date does not replace a story's first publication date.
Follow the [guide to representing items](../../../../docs/modeling.md).
Stop when the requested facts have evidence or a documented conflict; do not
research every checklist field just to fill the table.

Property uses were checked on 2026-09-29 against [WikiProject
Books](https://www.wikidata.org/wiki/Wikidata:WikiProject_Books) and linked
definitions. Check current guidance for cases outside these rules.

# Modeling decisions

Verified 2026-09-29 against Wikidata's [WikiProject Books](https://www.wikidata.org/wiki/Wikidata:WikiProject_Books), [P7937](https://www.wikidata.org/wiki/Property:P7937), and [novella (Q149537)](https://www.wikidata.org/wiki/Q149537).

Represent a creative work separately from a particular edition, and distinguish a story from a same-title collection. The Books project lists P7937 (“form of creative work”) among work properties, with a novel example. Use it to express literary form. This repository uses P31 Q7725634 for a literary work and adds P7937 Q149537 when the source supports a novella classification. This is a repository convention, not a universal requirement.

For a story that appears in an anthology, use P1433 (“published in”) when the source supports that relationship. The Books project recommends it for narrative within a collection. Keep a work's first publication date separate from its appearance date in a later anthology.

Put publisher claims on the edition described by the source. The
[P123 conflicts-with constraint](https://www.wikidata.org/wiki/Property:P123#constraints)
excludes items classified as literary work (Q7725634) or written work
(Q47461344). Preserve the work's classification; search for a matching edition
before proposing a new item. If a new edition is supported, give it
`P31 = Q3331189` (version, edition or translation), `P123 =` the confirmed
publishing house, and `P629 =` the underlying work. If edition identity remains
uncertain, leave the publisher claim out. Existing conflicting statements need
separate review because the exporter only adds statements. Checked 2026-09-29
against P123 and the Books project's edition guidance.

Recheck this guide when case evidence conflicts with it or the work falls outside these examples. Metadata labels and property definitions guide modeling; they do not support facts about a specific work.

"""Checked-in English entity metadata; never a cache of claims or evidence."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from .models import Case
from .wikidata import WikidataClient

DEFAULT_CACHE = Path("data/wikidata_ids.json")


class Metadata(BaseModel):
    """Display metadata for one QID or PID, fetched on a recorded date."""

    model_config = ConfigDict(extra="forbid")
    label: str = ""
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    datatype: str | None = None
    retrieved: date


class IdCache:
    """Load, search, and explicitly update a small JSON metadata dictionary."""

    def __init__(self, path: Path = DEFAULT_CACHE) -> None:
        self.path = path
        self.entries = (
            TypeAdapter(dict[str, Metadata]).validate_json(path.read_text(encoding="utf-8"))
            if path.exists()
            else {}
        )
        self._validate_ids(self.entries)

    @staticmethod
    def _validate_ids(ids: Iterable[str]) -> None:
        for identifier in ids:
            if not re.fullmatch(r"[QP][1-9][0-9]*", identifier):
                raise ValueError(f"Invalid Wikidata ID: {identifier}")

    def display(self, identifier: str) -> str:
        entry = self.entries.get(identifier)
        return f"{entry.label} ({identifier})" if entry and entry.label else identifier

    def find(self, name: str) -> dict[str, Metadata]:
        """Return all exact case-insensitive label or alias matches."""
        return {
            identifier: entry
            for identifier, entry in sorted(self.entries.items())
            if name.casefold() in {text.casefold() for text in [entry.label, *entry.aliases]}
        }

    def update(self, ids: Iterable[str], client: WikidataClient, *, refresh: bool = False) -> int:
        """Fetch missing IDs, or refresh requested IDs; save only after success."""
        requested = sorted(set(ids))
        self._validate_ids(requested)
        pending = [
            identifier for identifier in requested if refresh or identifier not in self.entries
        ]
        if not pending:
            return 0
        fetched = client.metadata(pending)
        additions = {
            identifier: Metadata.model_validate(value) for identifier, value in fetched.items()
        }
        updated = {**self.entries, **additions}
        contents = (
            json.dumps(
                {key: entry.model_dump(mode="json") for key, entry in sorted(updated.items())},
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as output:
            temporary = Path(output.name)
            try:
                output.write(contents)
                output.close()
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
        self.entries = updated
        return len(additions)


def case_ids(case: Case) -> set[str]:
    """Collect IDs from decisions, candidates, identifiers, claims, and qualifiers."""
    ids = {"P854", "P813"} if case.sources else set()
    for entity in case.entities:
        if entity.resolution.qid:
            ids.add(entity.resolution.qid)
        ids.update(candidate.qid for candidate in entity.resolution.candidates)
        ids.update(entity.identifiers)
        for claim in entity.claims:
            ids.add(claim.property)
            if claim.datatype == "item" and claim.value.startswith("Q"):
                ids.add(claim.value)
            for qualifier in claim.qualifiers:
                ids.add(qualifier.property)
                if qualifier.datatype == "item" and qualifier.value.startswith("Q"):
                    ids.add(qualifier.value)
    return ids

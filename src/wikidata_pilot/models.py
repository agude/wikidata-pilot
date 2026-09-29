"""Typed case files for evidence-backed Wikidata proposals."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Source(StrictModel):
    id: str = Field(min_length=1)
    url: HttpUrl
    retrieved: date
    excerpt: str = Field(min_length=1)
    locator: str | None = None
    verification: Literal["verified", "illustrative_unverified"] = "illustrative_unverified"


class Qualifier(StrictModel):
    property: str = Field(pattern=r"^P[1-9][0-9]*$")
    datatype: Literal["item", "string", "time"]
    value: str
    precision: Literal["year", "month", "day"] | None = None

    @model_validator(mode="after")
    def validate_time_precision(self) -> Qualifier:
        if (self.datatype == "time") != (self.precision is not None):
            raise ValueError("time qualifiers require precision year, month, or day")
        if self.datatype == "time":
            parse_time(self.value, self.precision or "day")
        if self.datatype == "item" and not re.fullmatch(
            r"Q[1-9][0-9]*|[a-z][a-z0-9-]*", self.value
        ):
            raise ValueError("item qualifier value must be a QID or local entity key")
        return self


class Claim(StrictModel):
    id: str
    property: str = Field(pattern=r"^P[1-9][0-9]*$")
    datatype: Literal["item", "string", "external-id", "time", "monolingualtext"]
    value: str
    language: str | None = None
    precision: Literal["year", "month", "day"] | None = None
    sources: list[str] = Field(min_length=1)
    qualifiers: list[Qualifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_datatype_fields(self) -> Claim:
        if (self.datatype == "monolingualtext") != (self.language is not None):
            raise ValueError("monolingualtext requires language; other datatypes forbid it")
        if (self.datatype == "time") != (self.precision is not None):
            raise ValueError("time claims require precision year, month, or day")
        if self.datatype == "time":
            parse_time(self.value, self.precision or "day")
        if self.datatype == "item" and not re.fullmatch(
            r"Q[1-9][0-9]*|[a-z][a-z0-9-]*", self.value
        ):
            raise ValueError("item claim value must be a QID or local entity key")
        if self.language is not None and not re.fullmatch(
            r"[a-z]{2,3}(?:-[A-Za-z0-9]+)*", self.language
        ):
            raise ValueError("language must be a language tag")
        return self


class Candidate(StrictModel):
    qid: str = Field(pattern=r"^Q[1-9][0-9]*$")
    label: str
    description: str | None = None
    matched_by: list[str] = Field(default_factory=list)


class Resolution(StrictModel):
    status: Literal["unresolved", "existing", "create"] = "unresolved"
    qid: str | None = None
    reason: str | None = None
    candidates: list[Candidate] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_state(self) -> Resolution:
        if self.qid is not None and not re.fullmatch(r"Q[1-9][0-9]*", self.qid):
            raise ValueError("qid must be a Wikidata item ID")
        if (self.status == "existing") != (self.qid is not None):
            raise ValueError("existing resolution requires qid; other states forbid qid")
        if self.status != "unresolved" and (not self.reason or not self.reason.strip()):
            raise ValueError("resolved decisions require a reason")
        return self


class Entity(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    kind: Literal["work", "collection", "edition", "person"]
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    title: str | None = None
    alternate_titles: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    identifiers: dict[str, str] = Field(default_factory=dict)
    claims: list[Claim] = Field(default_factory=list)
    resolution: Resolution = Field(default_factory=Resolution)

    @model_validator(mode="after")
    def validate_identifiers(self) -> Entity:
        if any(not re.fullmatch(r"P[1-9][0-9]*", key) for key in self.identifiers):
            raise ValueError("identifier keys must be Wikidata property IDs")
        return self


class Case(StrictModel):
    schema_version: Literal[1] = 1
    title: str
    sources: list[Source]
    entities: list[Entity]

    @model_validator(mode="after")
    def unique_keys(self) -> Case:
        keys = [entity.key for entity in self.entities]
        if len(keys) != len(set(keys)):
            raise ValueError("entity keys must be unique")
        source_ids = [source.id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source IDs must be unique")
        for entity in self.entities:
            claim_ids = [claim.id for claim in entity.claims]
            if len(claim_ids) != len(set(claim_ids)):
                raise ValueError(f"claim IDs must be unique within {entity.key}")
        return self


def load_case(path: Path) -> Case:
    """Load a validated UTF-8 JSON case file."""
    return Case.model_validate_json(path.read_text(encoding="utf-8"))


def save_case(path: Path, case: Case) -> None:
    """Write a case file as readable, deterministic JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(case.model_dump_json(indent=2) + "\n", encoding="utf-8")


def parse_time(value: str, precision: str) -> date:
    """Validate exact ISO year, month, or day values, including calendar validity."""
    patterns = {
        "year": r"[0-9]{4}",
        "month": r"[0-9]{4}-[0-9]{2}",
        "day": r"[0-9]{4}-[0-9]{2}-[0-9]{2}",
    }
    if precision not in patterns or not re.fullmatch(patterns[precision], value):
        raise ValueError(f"Invalid time value: {value}; expected {precision} precision")
    parts = [int(part) for part in value.split("-")]
    return date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)

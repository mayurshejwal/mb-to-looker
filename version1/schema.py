"""Typed state objects passed between agents via session.state.

Fix G: previously pure dead code (metabase.py returned raw dicts). These now
serve two live purposes:
  1. Canonical documentation of the state contract every agent relies on.
  2. from_dict() / to_dict() helpers so any tool can round-trip between the
     raw Metabase JSON and a typed object when validation is useful — without
     forcing serialization overhead in the hot path.

Plain dataclasses (not pydantic) keep tool-signature token cost low and keep
session-state values trivially JSON-serializable.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class MBField:
    id: int
    name: str
    display_name: str
    base_type: str                 # e.g. type/Integer, type/Text
    semantic_type: Optional[str]   # e.g. type/Category, type/PK
    fk_target_field_id: Optional[int] = None

    @classmethod
    def from_dict(cls, d: dict) -> "MBField":
        return cls(id=d["id"], name=d["name"],
                   display_name=d.get("display_name", d["name"]),
                   base_type=d.get("base_type", ""),
                   semantic_type=d.get("semantic_type"),
                   fk_target_field_id=d.get("fk_target_field_id"))


@dataclass
class MBTable:
    id: int
    name: str
    schema: Optional[str]
    fields: list[MBField] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "MBTable":
        return cls(id=d["id"], name=d["name"], schema=d.get("schema"),
                   fields=[MBField.from_dict(f) for f in d.get("fields", [])])

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MBQuestion:
    id: int
    name: str
    query_type: str                # "native" | "query" (MBQL)
    native_sql: Optional[str]
    mbql: Optional[dict]
    source_table_id: Optional[int]
    viz_type: str
    viz_settings: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "MBQuestion":
        return cls(id=d["id"], name=d["name"],
                   query_type=d.get("query_type", "query"),
                   native_sql=d.get("native_sql"), mbql=d.get("mbql"),
                   source_table_id=d.get("source_table_id"),
                   viz_type=d.get("viz_type", "table"),
                   viz_settings=d.get("viz_settings", {}))


@dataclass
class MBDashcard:
    card_id: int
    row: int
    col: int
    size_x: int
    size_y: int
    param_mappings: list[dict] = field(default_factory=list)


@dataclass
class MBDashboard:
    id: int
    name: str
    parameters: list[dict] = field(default_factory=list)
    cards: list[MBDashcard] = field(default_factory=list)


@dataclass
class MigrationResult:
    """One row in the final review report (mirrors report.py entity shape)."""
    entity_type: str               # "view" | "look" | "dashboard"
    name: str
    status: str                    # "ok" | "needs_review" | "failed"
    source_id: Optional[int] = None
    output_path: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

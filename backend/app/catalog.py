"""Coded catalogue of everyday plastic items (shared/plastic_catalog.json).

Each item has a three-digit code, its resin type, recycling steps and an upcycling project.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from .config import REPO_ROOT

CATALOG_PATH = REPO_ROOT / "shared" / "plastic_catalog.json"


class Resin(BaseModel):
    number: int = Field(ge=1, le=7)
    type: str


class Recycling(BaseModel):
    accepted: str
    steps: list[str] = Field(min_length=3, max_length=3)


class Upcycling(BaseModel):
    title: str
    materials: list[str] = Field(min_length=1)
    steps: list[str] = Field(min_length=3, max_length=3)
    precautions: list[str]


class CatalogItem(BaseModel):
    code: str
    name: str
    aliases: list[str]
    resin: Resin
    recycling: Recycling
    upcycling: Upcycling

    @field_validator("code")
    @classmethod
    def three_digits(cls, value: str) -> str:
        if not re.fullmatch(r"\d{3}", value):
            raise ValueError("code must be exactly three digits")
        return value


class CatalogSummary(BaseModel):
    code: str
    name: str
    aliases: list[str]
    resin: Resin


class Catalog:
    def __init__(self, path: Path = CATALOG_PATH):
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.version: str = raw["version"]
        self.items = [CatalogItem.model_validate(item) for item in raw["items"]]
        codes = [item.code for item in self.items]
        if len(codes) != len(set(codes)):
            raise ValueError("Duplicate item codes in catalogue")
        self._by_code = {item.code: item for item in self.items}

    @staticmethod
    def normalise_code(value: str) -> str | None:
        """'1', '01' and '001' all mean item 001. Returns None for non-numeric input."""
        digits = value.strip().lstrip("#")
        if not digits.isdigit() or len(digits) > 3:
            return None
        return digits.zfill(3)

    def get(self, code: str) -> CatalogItem | None:
        normalised = self.normalise_code(code)
        return self._by_code.get(normalised) if normalised else None

    def search(self, query: str) -> list[CatalogItem]:
        """Exact code first, then name or alias matches."""
        if (item := self.get(query)) is not None:
            return [item]
        text = query.strip().lower()
        if not text:
            return []
        return [i for i in self.items if text in i.name.lower() or any(text in a.lower() for a in i.aliases)]

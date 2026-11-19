"""Curated guides written by the team, loaded from shared/curated_guides.json.

The same file is bundled into the Android app, so both clients show identical safety content.
Hazardous guidance always comes from here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypedDict

from .config import REPO_ROOT


class CuratedGuide(TypedDict):
    kind: Literal["upcycle", "disposal"]
    title: str
    materials: list[str]
    steps: list[str]
    precautions: list[str]


def _load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    for name, guide in data["guides"].items():
        if len(guide["steps"]) != 3 or guide["kind"] not in {"upcycle", "disposal"}:
            raise ValueError(f"Curated guide for {name} is invalid")
    if data["guides"]["Hazardous"]["kind"] != "disposal":
        raise ValueError("Hazardous guidance must be a disposal guide")
    return data


_DATA = _load(REPO_ROOT / "shared" / "curated_guides.json")

SAFETY_NOTICE: str = _DATA["safety_notice"]
# Added to every Glass and Metal guide, including generated ones.
MANDATORY_PRECAUTIONS: dict[str, list[str]] = _DATA["mandatory_precautions"]
CURATED: dict[str, CuratedGuide] = _DATA["guides"]

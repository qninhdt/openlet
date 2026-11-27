"""Typed filesystem records returned by LetFS drivers and Filesystem facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from openlet_sdk.config import JSON


@dataclass(frozen=True, slots=True)
class VersionedText:
    text: str
    version: int


@dataclass(frozen=True, slots=True)
class GlobHit:
    path: str
    node_id: str
    kind: Literal["file", "directory"]
    artifact_path: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class GlobResult:
    hits: list[GlobHit]
    truncated: bool


@dataclass(frozen=True, slots=True)
class GrepHit:
    path: str
    line_number: int
    line_text: str
    node_id: str
    artifact_path: str


@dataclass(frozen=True, slots=True)
class GrepResult:
    hits: list[GrepHit]
    truncated: bool


@dataclass(frozen=True, slots=True)
class SemanticHit:
    path: str
    artifact_path: str
    file_id: str
    score: float
    text: str

    def to_json(self) -> dict[str, JSON]:
        return {
            "path": self.path,
            "artifact_path": self.artifact_path,
            "file_id": self.file_id,
            "score": self.score,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class FileRef:
    path: str
    storage_id: str
    node_id: str
    name: str
    kind: Literal["file", "folder"]
    media_type: str
    size_bytes: int

"""Typed filesystem records returned by LetFS drivers and Filesystem facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from openlet_sdk.types import JSON


class NodeStatExtra(BaseModel):
    """Typed view of LetFS FileStat.extra metadata."""

    model_config = ConfigDict(extra="ignore")

    node_id: str = ""
    storage_id: str = ""
    media_type: str = ""
    readonly: bool = False
    is_blob: bool = False


def parse_stat_extra(extra: Mapping[str, object] | None) -> NodeStatExtra:
    """Validate raw FileStat.extra metadata into a NodeStatExtra model."""
    return NodeStatExtra.model_validate(extra) if extra else NodeStatExtra()


@dataclass(frozen=True, slots=True)
class VersionedText:
    """Text file content paired with its LetFS optimistic-concurrency version."""

    text: str
    version: int


@dataclass(frozen=True, slots=True)
class GlobHit:
    """Single path match returned by LetFS glob_files."""

    path: str
    node_id: str
    kind: Literal["file", "directory"]
    artifact_path: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class GlobResult:
    """Bounded glob search result with truncation indicator."""

    hits: Sequence[GlobHit]
    truncated: bool


@dataclass(frozen=True, slots=True)
class GrepHit:
    """Single line match returned by LetFS grep_files."""

    path: str
    line_number: int
    line_text: str
    node_id: str
    artifact_path: str


@dataclass(frozen=True, slots=True)
class GrepResult:
    """Bounded grep search result with truncation indicator."""

    hits: Sequence[GrepHit]
    truncated: bool


@dataclass(frozen=True, slots=True)
class SemanticHit:
    """Semantic search snippet hit returned by LetFS SemanticSearch."""

    path: str
    artifact_path: str
    file_id: str
    score: float
    text: str

    def to_json(self) -> dict[str, JSON]:
        """Serialize the semantic search hit into a JSON-compatible dict."""
        return {
            "path": self.path,
            "artifact_path": self.artifact_path,
            "file_id": self.file_id,
            "score": self.score,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class FileRef:
    """Resolved LetFS node reference for a virtual workspace path."""

    path: str
    storage_id: str
    node_id: str
    name: str
    kind: Literal["file", "folder"]
    media_type: str
    size_bytes: int

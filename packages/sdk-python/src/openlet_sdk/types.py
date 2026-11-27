"""Shared typing primitives and runtime narrowing guards for Openlet Python packages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeIs

type JsonScalar = bool | int | float | str | None
type JSON = JsonScalar | Sequence[JSON] | Mapping[str, JSON]
type JsonObject = Mapping[str, JSON]
type MutableJsonObject = dict[str, JSON]


def is_mapping(value: object) -> TypeIs[Mapping[object, object]]:
    """Return whether ``value`` is a ``Mapping``."""
    return isinstance(value, Mapping)


def is_str_mapping(value: object) -> TypeIs[Mapping[str, object]]:
    """Return whether ``value`` is a ``Mapping`` with string keys."""
    return is_mapping(value) and all(isinstance(k, str) for k in value)


def is_object_list(value: object) -> TypeIs[list[object]]:
    """Return whether ``value`` is a ``list``."""
    return isinstance(value, list)


def is_object_sequence(value: object) -> TypeIs[Sequence[object]]:
    """Return whether ``value`` is a non-string/bytes ``Sequence``."""
    return isinstance(value, Sequence) and not isinstance(
        value, str | bytes | bytearray
    )

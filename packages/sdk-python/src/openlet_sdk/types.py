"""Shared typing primitives and runtime narrowing guards for Openlet Python packages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeIs

type JsonScalar = None | bool | int | float | str
type JSON = JsonScalar | Sequence[JSON] | Mapping[str, JSON]
type JsonObject = Mapping[str, JSON]
type MutableJsonObject = dict[str, JSON]


def is_mapping(value: object) -> TypeIs[Mapping[object, object]]:
    return isinstance(value, Mapping)


def is_str_mapping(value: object) -> TypeIs[Mapping[str, object]]:
    return is_mapping(value) and all(isinstance(k, str) for k in value)


def is_object_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def is_object_sequence(value: object) -> TypeIs[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )

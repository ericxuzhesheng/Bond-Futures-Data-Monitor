"""Shared collection-result metadata for optional enrichments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class CollectionResult(Generic[T]):
    rows: list[T]
    status: str
    source: str
    message: str
    observation_date: str | None = None


def result_from_optional(
    rows: list[T], source: str, empty_message: str, observation_date: str | None = None
) -> CollectionResult[T]:
    if rows:
        return CollectionResult(rows, "ok", source, "采集成功", observation_date)
    return CollectionResult([], "empty", source, empty_message, observation_date)

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class MediaType(StrEnum):
    MOVIE = "MOVIE"
    EPISODE = "EPISODE"
    SUBTITLE = "SUBTITLE"
    UNKNOWN = "UNKNOWN"


class OperationStatus(StrEnum):
    PLANNED = "PLANNED"
    CONFLICT = "CONFLICT"
    MOVED = "MOVED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True)
class FoundFile:
    path: Path
    extension: str


@dataclass(frozen=True, slots=True)
class Movie:
    title: str
    year: int
    technical_tags: tuple[str, ...]
    extension: str


@dataclass(frozen=True, slots=True)
class Episode:
    series: str
    season: int
    episodes: tuple[int, ...]
    extension: str

    @property
    def episode_code(self) -> str:
        first, *rest = self.episodes
        suffix = "".join(f"-E{number:02d}" for number in rest)
        return f"S{self.season:02d}E{first:02d}{suffix}"


@dataclass(frozen=True, slots=True)
class Subtitle:
    language: str | None
    extension: str
    movie: Movie | None = None
    episode: Episode | None = None
    flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Conflict:
    reason: str


@dataclass(slots=True)
class PlannedOperation:
    source: Path
    media_type: MediaType
    target: Path | None
    status: OperationStatus = OperationStatus.PLANNED
    conflict: Conflict | None = None
    error: str | None = None


@dataclass(slots=True)
class ExecutionResult:
    operations: list[PlannedOperation] = field(default_factory=list)

    @property
    def moved(self) -> int:
        return sum(op.status is OperationStatus.MOVED for op in self.operations)

    @property
    def failed(self) -> int:
        return sum(op.status is OperationStatus.FAILED for op in self.operations)

    @property
    def skipped(self) -> int:
        return sum(
            op.status in {OperationStatus.SKIPPED, OperationStatus.CONFLICT}
            for op in self.operations
        )

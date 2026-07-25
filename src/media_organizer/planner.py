from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from media_organizer.config import Config
from media_organizer.models import (
    Conflict,
    Episode,
    FoundFile,
    MediaType,
    Movie,
    OperationStatus,
    PlannedOperation,
    Subtitle,
)
from media_organizer.parser import (
    legacy_episode_candidate,
    parse_episode,
    parse_episode_with_context,
    parse_movie,
)
from media_organizer.subtitles import compatible_subtitle, parse_subtitle


class UnsafePathError(ValueError):
    pass


def ensure_within(path: Path, root: Path) -> Path:
    root_resolved = root.resolve(strict=False)
    candidate = path.resolve(strict=False)
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise UnsafePathError(f"caminho fora da raiz configurada: {path}") from exc
    return candidate


def movie_target(config: Config, movie: Movie) -> Path:
    base = f"{movie.title} ({movie.year})"
    tags = ""
    if config.preserve_technical_tags_for_movies and movie.technical_tags:
        tags = f" [{' '.join(movie.technical_tags)}]"
    return config.movies_path / base / f"{base}{tags}{movie.extension}"


def episode_target(config: Config, episode: Episode) -> Path:
    name = f"{episode.series} {episode.episode_code}{episode.extension}"
    return config.series_path / episode.series / f"Season {episode.season:02d}" / name


def _subtitle_target(base_target: Path, subtitle: Subtitle) -> Path:
    qualifiers = tuple(filter(None, (subtitle.language, *subtitle.flags)))
    suffix = f".{'.'.join(qualifiers)}" if qualifiers else ""
    return base_target.with_name(f"{base_target.stem}{suffix}{subtitle.extension}")


def _operation(
    source: Path, media_type: MediaType, target: Path | None, config: Config
) -> PlannedOperation:
    operation = PlannedOperation(source=source, media_type=media_type, target=target)
    if target is None:
        operation.status = OperationStatus.SKIPPED
        return operation
    try:
        ensure_within(source, config.media_root)
        ensure_within(target, config.media_root)
    except UnsafePathError as exc:
        operation.status = OperationStatus.CONFLICT
        operation.conflict = Conflict(str(exc))
    return operation


def build_plan(files: Iterable[FoundFile], config: Config) -> list[PlannedOperation]:
    operations: list[PlannedOperation] = []
    recognized: list[tuple[Movie | None, Episode | None, Path]] = []
    subtitles: list[FoundFile] = []
    legacy_by_directory: dict[Path, list[tuple[FoundFile, int]]] = {}
    explicit_directories: set[Path] = set()

    for found in files:
        if found.extension in config.subtitle_extensions:
            subtitles.append(found)
        elif found.extension in config.video_extensions:
            episode = parse_episode(found.path)
            if episode is not None:
                explicit_directories.add(found.path.parent)
            else:
                candidate = legacy_episode_candidate(found.path, config.incoming_path)
                if candidate is not None:
                    legacy_by_directory.setdefault(found.path.parent, []).append(
                        (found, candidate.absolute_number)
                    )
                    continue
            movie = None if episode else parse_movie(found.path)
            if episode:
                target = episode_target(config, episode)
                operations.append(_operation(found.path, MediaType.EPISODE, target, config))
                recognized.append((None, episode, target))
            elif movie:
                target = movie_target(config, movie)
                operations.append(_operation(found.path, MediaType.MOVIE, target, config))
                recognized.append((movie, None, target))
            else:
                operations.append(_operation(found.path, MediaType.UNKNOWN, None, config))
        else:
            operations.append(_operation(found.path, MediaType.UNKNOWN, None, config))

    legacy_numbers = _legacy_episode_numbers(legacy_by_directory, explicit_directories)
    for entries in legacy_by_directory.values():
        for found, _ in entries:
            episode_number = legacy_numbers.get(found.path)
            episode = (
                parse_episode_with_context(
                    found.path,
                    config.incoming_path,
                    episode_number=episode_number,
                )
                if episode_number is not None
                else None
            )
            if episode is not None:
                target = episode_target(config, episode)
                operations.append(_operation(found.path, MediaType.EPISODE, target, config))
                recognized.append((None, episode, target))
            else:
                operations.append(_operation(found.path, MediaType.UNKNOWN, None, config))

    for found in subtitles:
        subtitle = parse_subtitle(found.path)
        target = None
        if subtitle:
            for movie, episode, video_target in recognized:
                if compatible_subtitle(subtitle, movie, episode):
                    target = _subtitle_target(video_target, subtitle)
                    break
        media_type = MediaType.SUBTITLE if target else MediaType.UNKNOWN
        operations.append(_operation(found.path, media_type, target, config))

    _mark_conflicts(operations)
    return sorted(operations, key=lambda operation: str(operation.source))


def _legacy_episode_numbers(
    candidates_by_directory: dict[Path, list[tuple[FoundFile, int]]],
    explicit_directories: set[Path],
) -> dict[Path, int]:
    episode_numbers: dict[Path, int] = {}
    for directory, entries in candidates_by_directory.items():
        if directory in explicit_directories:
            continue
        numbers = [number for _, number in entries]
        unique_numbers = set(numbers)
        if len(unique_numbers) != len(numbers):
            continue
        ordered = sorted(unique_numbers)
        first = ordered[0]
        if first > 1 and (len(ordered) < 2 or ordered != list(range(first, ordered[-1] + 1))):
            continue
        for found, number in entries:
            episode_numbers[found.path] = number if first == 1 else number - first + 1
    return episode_numbers


def _mark_conflicts(operations: list[PlannedOperation]) -> None:
    targets: dict[Path, PlannedOperation] = {}
    for operation in operations:
        if operation.target is None or operation.status is OperationStatus.CONFLICT:
            continue
        target = operation.target.resolve(strict=False)
        reason: str | None = None
        if operation.source.resolve(strict=False) == target:
            reason = "origem e destino são iguais"
        elif target.exists():
            reason = "destino já existe"
        elif target in targets:
            reason = "mais de um arquivo aponta para o mesmo destino"
            previous = targets[target]
            previous.status = OperationStatus.CONFLICT
            previous.conflict = Conflict(reason)
        if reason:
            operation.status = OperationStatus.CONFLICT
            operation.conflict = Conflict(reason)
        else:
            targets[target] = operation

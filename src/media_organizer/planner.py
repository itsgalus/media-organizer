from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
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
from media_organizer.subtitles import (
    SUBTITLE_DIRECTORY_NAMES,
    compatible_subtitle,
    parse_subtitle,
)


@dataclass(frozen=True, slots=True)
class _RecognizedVideo:
    source: Path
    movie: Movie | None
    episode: Episode | None
    target: Path
    operation: PlannedOperation


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
    recognized: list[_RecognizedVideo] = []
    video_sources: list[Path] = []
    subtitles: list[FoundFile] = []
    legacy_by_directory: dict[Path, list[tuple[FoundFile, int]]] = {}
    explicit_directories: set[Path] = set()

    for found in files:
        if found.extension in config.subtitle_extensions:
            subtitles.append(found)
        elif found.extension in config.video_extensions:
            video_sources.append(found.path)
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
                operation = _operation(found.path, MediaType.EPISODE, target, config)
                operations.append(operation)
                recognized.append(_RecognizedVideo(found.path, None, episode, target, operation))
            elif movie:
                target = movie_target(config, movie)
                operation = _operation(found.path, MediaType.MOVIE, target, config)
                operations.append(operation)
                recognized.append(_RecognizedVideo(found.path, movie, None, target, operation))
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
                operation = _operation(found.path, MediaType.EPISODE, target, config)
                operations.append(operation)
                recognized.append(_RecognizedVideo(found.path, None, episode, target, operation))
            else:
                operations.append(_operation(found.path, MediaType.UNKNOWN, None, config))

    _mark_conflicts(operations)
    for found in subtitles:
        subtitle = parse_subtitle(found.path)
        target = None
        if subtitle:
            for video in recognized:
                if compatible_subtitle(subtitle, video.movie, video.episode):
                    target = _subtitle_target(video.target, subtitle)
                    break
            if target is None and subtitle.movie is None and subtitle.episode is None:
                video = _contextual_video(
                    found.path,
                    config.incoming_path,
                    video_sources,
                    recognized,
                )
                if video is not None:
                    target = _subtitle_target(video.target, subtitle)
        media_type = MediaType.SUBTITLE if target else MediaType.UNKNOWN
        operations.append(_operation(found.path, media_type, target, config))

    _mark_conflicts(operations)
    return sorted(operations, key=lambda operation: str(operation.source))


def _contextual_video(
    subtitle_path: Path,
    incoming_path: Path,
    video_sources: list[Path],
    recognized: list[_RecognizedVideo],
) -> _RecognizedVideo | None:
    try:
        relative = subtitle_path.resolve(strict=False).relative_to(
            incoming_path.resolve(strict=False)
        )
    except ValueError:
        return None

    subtitle_indexes = [
        index
        for index, part in enumerate(relative.parts[:-1])
        if part.casefold() in SUBTITLE_DIRECTORY_NAMES
    ]
    if not subtitle_indexes:
        return None

    subtitle_directory_index = subtitle_indexes[-1]
    container = incoming_path.joinpath(*relative.parts[:subtitle_directory_index])
    incoming_resolved = incoming_path.resolve(strict=False)
    while container.resolve(strict=False) != incoming_resolved:
        container_resolved = container.resolve(strict=False)
        candidates = [
            source
            for source in video_sources
            if source.resolve(strict=False).is_relative_to(container_resolved)
        ]
        if candidates:
            if len(candidates) != 1:
                return None
            matching = [video for video in recognized if video.source == candidates[0]]
            if len(matching) != 1 or matching[0].operation.status is not OperationStatus.PLANNED:
                return None
            return matching[0]
        container = container.parent
    return None


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

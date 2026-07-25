from __future__ import annotations

import re
from pathlib import Path

from media_organizer.models import Episode, Movie, Subtitle
from media_organizer.parser import parse_episode, parse_movie

LANGUAGE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?i)(?:^|[._ -])"
            r"(?:portuguese[._ -]?brazil|portuguese|pt[._-]?br|ptb|pob|por|"
            r"brazilian|brazil|br|pt)"
            r"(?=$|[._ -])"
        ),
        "pt-BR",
    ),
    (
        re.compile(r"(?i)(?:^|[._ -])(?:english|eng|en[._-]?us|en)(?=$|[._ -])"),
        "en",
    ),
    (
        re.compile(r"(?i)(?:^|[._ -])(?:german|ger|deu|de)(?=$|[._ -])"),
        "de",
    ),
)
FLAG_PATTERN = re.compile(r"(?i)(?:^|[._ -])(?P<flag>forced|sdh|cc)(?=$|[._ -])")
SUBTITLE_DIRECTORY_NAMES = frozenset(
    {"subs", "sub", "subtitles", "subtitle", "legendas", "captions"}
)


def identify_language(stem: str) -> str | None:
    for pattern, language in LANGUAGE_PATTERNS:
        if pattern.search(stem):
            return language
    return None


def identify_flags(stem: str) -> tuple[str, ...]:
    flags: list[str] = []
    for match in FLAG_PATTERN.finditer(stem):
        flag = match.group("flag").lower()
        if flag not in flags:
            flags.append(flag)
    return tuple(flags)


def _context_components(path: Path) -> tuple[str, ...]:
    parent_parts = path.parent.parts
    subtitle_directory_indexes = [
        index
        for index, part in enumerate(parent_parts)
        if part.casefold() in SUBTITLE_DIRECTORY_NAMES
    ]
    if not subtitle_directory_indexes:
        return ()
    return parent_parts[subtitle_directory_indexes[-1] + 1 :]


def _subtitle_metadata(path: Path) -> tuple[str | None, tuple[str, ...]]:
    language = identify_language(path.stem)
    context_components = _context_components(path)
    if language is None:
        for component in reversed(context_components):
            language = identify_language(component)
            if language is not None:
                break

    flags: list[str] = []
    for component in (*context_components, path.stem):
        for flag in identify_flags(component):
            if flag not in flags:
                flags.append(flag)
    return language, tuple(flags)


def parse_subtitle(path: Path) -> Subtitle | None:
    language, flags = _subtitle_metadata(path)
    episode = parse_episode(path)
    if episode is not None:
        return Subtitle(
            language=language,
            extension=path.suffix.lower(),
            episode=episode,
            flags=flags,
        )
    movie = parse_movie(path)
    if movie is not None:
        return Subtitle(
            language=language,
            extension=path.suffix.lower(),
            movie=movie,
            flags=flags,
        )
    return Subtitle(language=language, extension=path.suffix.lower(), flags=flags)


def compatible_subtitle(subtitle: Subtitle, movie: Movie | None, episode: Episode | None) -> bool:
    if subtitle.episode and episode:
        return (
            subtitle.episode.series.casefold() == episode.series.casefold()
            and subtitle.episode.season == episode.season
            and subtitle.episode.episodes == episode.episodes
        )
    if subtitle.movie and movie:
        return (
            subtitle.movie.title.casefold() == movie.title.casefold()
            and subtitle.movie.year == movie.year
        )
    return False

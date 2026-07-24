from __future__ import annotations

import re
from pathlib import Path

from media_organizer.models import Episode, Movie, Subtitle
from media_organizer.parser import parse_episode, parse_movie

LANGUAGE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?i)(?:^|[._ -])(?:portuguese[._ -]?brazil|pt[._ -]?br|brazilian)(?:$|[._ -])"
        ),
        "pt-BR",
    ),
    (re.compile(r"(?i)(?:^|[._ -])(?:portuguese|pt)(?:$|[._ -])"), "pt-BR"),
    (re.compile(r"(?i)(?:^|[._ -])(?:english|eng|en)(?:$|[._ -])"), "en"),
)


def identify_language(stem: str) -> str | None:
    for pattern, language in LANGUAGE_PATTERNS:
        if pattern.search(stem):
            return language
    return None


def parse_subtitle(path: Path) -> Subtitle | None:
    language = identify_language(path.stem)
    episode = parse_episode(path)
    if episode is not None:
        return Subtitle(language=language, extension=path.suffix.lower(), episode=episode)
    movie = parse_movie(path)
    if movie is not None:
        return Subtitle(language=language, extension=path.suffix.lower(), movie=movie)
    return None


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

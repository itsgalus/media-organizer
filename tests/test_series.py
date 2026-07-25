from pathlib import Path

import pytest

from media_organizer.parser import (
    legacy_episode_candidate,
    parse_episode,
    parse_episode_with_context,
)


@pytest.mark.parametrize(
    ("filename", "series", "code"),
    [
        ("Breaking.Bad.S01E01.1080p.mkv", "Breaking Bad", "S01E01"),
        ("Serie.Name.1x04.mkv", "Serie Name", "S01E04"),
        ("Show.S01E01E02.mkv", "Show", "S01E01-E02"),
        ("Batman_The.Animated_Series.s02e03.mkv", "Batman The Animated Series", "S02E03"),
        ("Show.S00E01.mkv", "Show", "S00E01"),
        ("Show.S01E01-E02.mkv", "Show", "S01E01-E02"),
        ("Show.S01E01.E02.mkv", "Show", "S01E01-E02"),
        ("Show.S01E01E02E03.mkv", "Show", "S01E01-E02-E03"),
        ("Show.01x001.mkv", "Show", "S01E01"),
    ],
)
def test_parse_episode(filename: str, series: str, code: str) -> None:
    episode = parse_episode(Path(filename))
    assert episode is not None
    assert episode.series == series
    assert episode.episode_code == code


def test_episode_preserves_extension() -> None:
    episode = parse_episode(Path("The.Office.US.S02E03.MP4"))
    assert episode is not None
    assert episode.extension == ".mp4"


@pytest.mark.parametrize(
    "season_directory",
    ["Temporada 1", "Temporada 01", "Season 1", "Season 01", "S01"],
)
def test_contextual_episode_accepts_specific_season_directories(
    tmp_path: Path, season_directory: str
) -> None:
    incoming = tmp_path / "incoming"
    path = incoming / "Batman The Animated Series" / season_directory / "01 Asas de Couro.divx"
    episode = parse_episode_with_context(path, incoming)
    assert episode is not None
    assert episode.series == "Batman The Animated Series"
    assert episode.episode_code == "S01E01"
    assert episode.extension == ".divx"


@pytest.mark.parametrize(
    "filename",
    ["01 Asas de Couro.divx", "01 - Asas de Couro.divx", "01. Asas de Couro.divx"],
)
def test_contextual_episode_accepts_initial_number_separators(
    tmp_path: Path, filename: str
) -> None:
    incoming = tmp_path / "incoming"
    path = incoming / "Legacy Show" / "Temporada 1" / filename
    candidate = legacy_episode_candidate(path, incoming)
    assert candidate is not None
    assert candidate.absolute_number == 1


@pytest.mark.parametrize("directory", ["temp", "videos", "arquivos", "parte 1"])
def test_contextual_episode_rejects_vague_directory(tmp_path: Path, directory: str) -> None:
    incoming = tmp_path / "incoming"
    path = incoming / "Legacy Show" / directory / "01 Episode.avi"
    assert parse_episode_with_context(path, incoming) is None


def test_contextual_episode_rejects_number_in_middle(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    path = incoming / "Legacy Show" / "Season 01" / "Episode 01 Name.avi"
    assert parse_episode_with_context(path, incoming) is None


@pytest.mark.parametrize("filename", ["Show.S01E01.mkv", "Show.1x01.mkv"])
def test_explicit_episode_format_has_priority(tmp_path: Path, filename: str) -> None:
    incoming = tmp_path / "incoming"
    episode = parse_episode_with_context(incoming / filename, incoming)
    assert episode is not None
    assert episode.episode_code == "S01E01"


def test_file_outside_incoming_does_not_gain_legacy_context(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    outside = tmp_path / "Legacy Show" / "Season 01" / "01 Episode.avi"
    assert parse_episode_with_context(outside, incoming) is None

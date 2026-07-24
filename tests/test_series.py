from pathlib import Path

import pytest

from media_organizer.parser import parse_episode


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

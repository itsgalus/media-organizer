from pathlib import Path

import pytest

from media_organizer.parser import parse_movie


@pytest.mark.parametrize(
    ("filename", "title", "year", "tags"),
    [
        ("Interstellar.2014.mkv", "Interstellar", 2014, ()),
        (
            "The.Dark.Knight.2008.1080p.BluRay.x265.mkv",
            "The Dark Knight",
            2008,
            ("1080p", "BluRay", "x265"),
        ),
        (
            "Interstellar.2014.2160p.HDR.BluRay.REMUX.mkv",
            "Interstellar",
            2014,
            ("2160p", "HDR", "BluRay", "REMUX"),
        ),
        ("Blade.Runner.1982.Final.Cut.1080p.mkv", "Blade Runner", 1982, ("1080p", "Final Cut")),
    ],
)
def test_parse_movies(filename: str, title: str, year: int, tags: tuple[str, ...]) -> None:
    movie = parse_movie(Path(filename))
    assert movie is not None
    assert (movie.title, movie.year, movie.technical_tags) == (title, year, tags)


def test_preserves_extension() -> None:
    movie = parse_movie(Path("Arrival.2016.1080p.MP4"))
    assert movie is not None
    assert movie.extension == ".mp4"


@pytest.mark.parametrize("filename", ["video-final-novo.mkv", "2020.mkv", "bad-file.mp4"])
def test_malformed_or_unknown_movie(filename: str) -> None:
    assert parse_movie(Path(filename)) is None

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
            ("1080p", "x265", "BluRay"),
        ),
        (
            "Interstellar.2014.2160p.HDR.BluRay.REMUX.mkv",
            "Interstellar",
            2014,
            ("2160p", "HDR", "BluRay", "REMUX"),
        ),
        ("Blade.Runner.1982.Final.Cut.1080p.mkv", "Blade Runner", 1982, ("1080p", "Final Cut")),
        (
            "Spider.Man.No.Way.Home.2021.1080p.BluRay.x265.mkv",
            "Spider Man No Way Home",
            2021,
            ("1080p", "x265", "BluRay"),
        ),
        (
            "Dune.Part.Two.2024.2160p.WEB-DL.DV.HDR10+.mkv",
            "Dune Part Two",
            2024,
            ("2160p", "HDR10+", "Dolby Vision", "WEB-DL"),
        ),
        (
            "Blade.Runner.1982.Directors.Cut.1080p.mkv",
            "Blade Runner",
            1982,
            ("1080p", "Director's Cut"),
        ),
        (
            "Movie.Name.2020.DTS-HD.MA.TrueHD.Atmos.mkv",
            "Movie Name",
            2020,
            ("Atmos", "TrueHD", "DTS-HD MA"),
        ),
        (
            "Movie.Name.2020.IMAX.Enhanced.HDR.HEVC.mkv",
            "Movie Name",
            2020,
            ("HDR", "HEVC", "IMAX Enhanced"),
        ),
        (
            "Movie.Name.2020.UHD.BluRay.mkv",
            "Movie Name",
            2020,
            ("UHD BluRay",),
        ),
        (
            "Movie.Name.2020.AVC.WEBRip.mkv",
            "Movie Name",
            2020,
            ("AVC", "WEBRip"),
        ),
        (
            "Movie.Name.2020.SDR.H264.mkv",
            "Movie Name",
            2020,
            ("SDR", "H.264"),
        ),
        (
            "Spider.Man.No.Way.Home.2021.BluRay.1080p.x265.Atmos.HDR.mkv",
            "Spider Man No Way Home",
            2021,
            ("1080p", "HDR", "x265", "BluRay", "Atmos"),
        ),
        (
            "Spider-Man.No.Way.Home.2021.mkv",
            "Spider-Man No Way Home",
            2021,
            (),
        ),
        ("X-Men.2000.mkv", "X-Men", 2000, ()),
        ("Ant-Man.2015.mkv", "Ant-Man", 2015, ()),
        (
            "Spider-Man.Across.the.Spider-Verse.2023.mkv",
            "Spider-Man Across the Spider-Verse",
            2023,
            (),
        ),
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


@pytest.mark.parametrize(
    "filename",
    [
        "video-final-novo.mkv",
        "video-final.mkv",
        "teste.mp4",
        "arquivo.mkv",
        "torrent.mkv",
        "2020.mkv",
        "bad-file.mp4",
    ],
)
def test_malformed_or_unknown_movie(filename: str) -> None:
    assert parse_movie(Path(filename)) is None

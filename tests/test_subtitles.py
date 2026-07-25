from pathlib import Path

import pytest

from media_organizer.subtitles import identify_language, parse_subtitle


@pytest.mark.parametrize(
    ("filename", "language"),
    [
        ("Batman.The.Animated.Series.S01E01.Portuguese-Brazil.srt", "pt-BR"),
        ("Batman.The.Animated.Series.S01E01.Brazilian.ass", "pt-BR"),
        ("Batman.The.Animated.Series.S01E01.pt-BR.vtt", "pt-BR"),
        ("Batman.The.Animated.Series.S01E01.pt_BR.srt", "pt-BR"),
        ("Batman.The.Animated.Series.S01E01.ptbr.srt", "pt-BR"),
        ("Batman.The.Animated.Series.S01E01.ptb.srt", "pt-BR"),
        ("Batman.The.Animated.Series.S01E01.pob.srt", "pt-BR"),
        ("Batman.The.Animated.Series.S01E01.por.srt", "pt-BR"),
        ("Batman.The.Animated.Series.S01E01.brazil.srt", "pt-BR"),
        ("Batman.The.Animated.Series.S01E01.br.srt", "pt-BR"),
        ("Batman.The.Animated.Series.S01E01.en.srt", "en"),
        ("Batman.The.Animated.Series.S01E01.English.srt", "en"),
        ("Batman.The.Animated.Series.S01E01.eng.ssa", "en"),
        ("Batman.The.Animated.Series.S01E01.en-US.srt", "en"),
        ("Batman.The.Animated.Series.S01E01.enus.srt", "en"),
        ("Batman.The.Animated.Series.S01E01.en_US.srt", "en"),
        ("Batman.The.Animated.Series.S01E01.ger.srt", "de"),
        ("Batman.The.Animated.Series.S01E01.GERMAN.srt", "de"),
        ("Batman.The.Animated.Series.S01E01.Deu.srt", "de"),
        ("Batman.The.Animated.Series.S01E01.DE.srt", "de"),
    ],
)
def test_subtitle_languages(filename: str, language: str) -> None:
    subtitle = parse_subtitle(Path(filename))
    assert subtitle is not None
    assert subtitle.language == language
    assert subtitle.episode is not None


@pytest.mark.parametrize(
    ("filename", "flags"),
    [
        ("Show.S01E01.pt-BR.forced.srt", ("forced",)),
        ("Show.S01E01.en.sdh.srt", ("sdh",)),
        ("Show.S01E01.en.cc.srt", ("cc",)),
        ("Show.S01E01.en.sdh.cc.srt", ("sdh", "cc")),
        ("Show.S01E01.en.cc.forced.sdh.srt", ("cc", "forced", "sdh")),
        ("Show.S01E01.en.sdh.sdh.cc.srt", ("sdh", "cc")),
        ("Show.S01E01.en.FORCED.CC.srt", ("forced", "cc")),
    ],
)
def test_subtitle_flags(filename: str, flags: tuple[str, ...]) -> None:
    subtitle = parse_subtitle(Path(filename))
    assert subtitle is not None
    assert subtitle.flags == flags


def test_unknown_language_is_not_invented() -> None:
    subtitle = parse_subtitle(Path("Show.S01E01.unknown.srt"))
    assert subtitle is not None
    assert subtitle.language is None
    assert subtitle.flags == ()


@pytest.mark.parametrize("filename", ["subtitle.srt", "movie.sub.srt", "teste.ass", "random.vtt"])
def test_unidentified_subtitle_has_no_language_or_flags(filename: str) -> None:
    subtitle = parse_subtitle(Path(filename))
    assert subtitle is not None
    assert subtitle.language is None
    assert subtitle.flags == ()


def test_movie_subtitle() -> None:
    subtitle = parse_subtitle(Path("Movie.Name.2020.en.forced.srt"))
    assert subtitle is not None
    assert subtitle.language == "en"
    assert subtitle.flags == ("forced",)
    assert subtitle.movie is not None
    assert subtitle.movie.title == "Movie Name"


def test_episode_subtitle() -> None:
    subtitle = parse_subtitle(Path("Batman.The.Animated.Series.S01E01.ptbr.srt"))
    assert subtitle is not None
    assert subtitle.language == "pt-BR"
    assert subtitle.episode is not None
    assert subtitle.episode.series == "Batman The Animated Series"


def test_subtitle_extension_is_preserved_and_normalized() -> None:
    subtitle = parse_subtitle(Path("Movie.Name.2020.en.SRT"))
    assert subtitle is not None
    assert subtitle.extension == ".srt"


def test_german_alias_does_not_match_inside_word() -> None:
    assert identify_language("desfile") is None


@pytest.mark.parametrize("stem", ["movie.ger", "movie_GERMAN", "movie-deu", "movie DE"])
def test_german_aliases_accept_common_separators(stem: str) -> None:
    assert identify_language(stem) == "de"


@pytest.mark.parametrize(
    ("path", "language"),
    [
        ("Movie/Subs/German/subtitle.srt", "de"),
        ("Movie/Subtitles/English/subtitle.srt", "en"),
        ("Movie/Legendas/Portuguese/subtitle.srt", "pt-BR"),
    ],
)
def test_subtitle_language_can_come_from_directory(path: str, language: str) -> None:
    subtitle = parse_subtitle(Path(path))
    assert subtitle is not None
    assert subtitle.language == language


def test_filename_language_has_priority_over_directory() -> None:
    subtitle = parse_subtitle(Path("Movie/Subs/German/subtitle.en.srt"))
    assert subtitle is not None
    assert subtitle.language == "en"


def test_flags_can_come_from_file_and_directories_without_duplicates() -> None:
    subtitle = parse_subtitle(Path("Movie/Subs/German/Forced/subtitle.forced.sdh.cc.srt"))
    assert subtitle is not None
    assert subtitle.language == "de"
    assert subtitle.flags == ("forced", "sdh", "cc")


def test_unrecognized_directory_does_not_provide_language() -> None:
    subtitle = parse_subtitle(Path("Movie/Extras/German/subtitle.srt"))
    assert subtitle is not None
    assert subtitle.language is None

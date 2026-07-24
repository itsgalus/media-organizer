from pathlib import Path

import pytest

from media_organizer.subtitles import parse_subtitle


@pytest.mark.parametrize(
    ("filename", "language"),
    [
        ("Batman.The.Animated.Series.S01E01.Portuguese-Brazil.srt", "pt-BR"),
        ("Batman.The.Animated.Series.S01E01.Brazilian.ass", "pt-BR"),
        ("Batman.The.Animated.Series.S01E01.pt-BR.vtt", "pt-BR"),
        ("Batman.The.Animated.Series.S01E01.English.srt", "en"),
        ("Batman.The.Animated.Series.S01E01.eng.ssa", "en"),
    ],
)
def test_subtitle_languages(filename: str, language: str) -> None:
    subtitle = parse_subtitle(Path(filename))
    assert subtitle is not None
    assert subtitle.language == language
    assert subtitle.episode is not None


def test_unknown_language_is_not_invented() -> None:
    subtitle = parse_subtitle(Path("Show.S01E01.unknown.srt"))
    assert subtitle is not None
    assert subtitle.language is None

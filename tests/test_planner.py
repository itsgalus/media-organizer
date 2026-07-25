from pathlib import Path

import pytest

from media_organizer.cli import main
from media_organizer.config import Config
from media_organizer.models import FoundFile, MediaType, OperationStatus
from media_organizer.organizer import apply_plan
from media_organizer.planner import UnsafePathError, build_plan, ensure_within
from media_organizer.scanner import scan_files


def make_config(root: Path) -> Config:
    return Config(media_root=root)


def touch(root: Path, name: str, content: bytes = b"media") -> Path:
    path = root / "incoming" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_movie_and_episode_targets(tmp_path: Path) -> None:
    movie = touch(tmp_path, "Interstellar.2014.2160p.HDR.REMUX.mkv")
    episode = touch(tmp_path, "Batman.The.Animated.Series.S01E01.1080p.mkv")
    plan = build_plan(scan_files(make_config(tmp_path)), make_config(tmp_path))
    targets = {operation.source: operation.target for operation in plan}
    assert (
        targets[movie]
        == tmp_path / "movies/Interstellar (2014)/Interstellar (2014) [2160p HDR REMUX].mkv"
    )
    assert (
        targets[episode]
        == tmp_path
        / "series/Batman The Animated Series/Season 01/Batman The Animated Series S01E01.mkv"
    )


def test_subtitle_associated_with_episode(tmp_path: Path) -> None:
    touch(tmp_path, "Show.S01E01.mkv")
    subtitle = touch(tmp_path, "Show.S01E01.Portuguese-Brazil.srt")
    plan = build_plan(scan_files(make_config(tmp_path)), make_config(tmp_path))
    operation = next(item for item in plan if item.source == subtitle)
    assert operation.media_type is MediaType.SUBTITLE
    assert operation.target == tmp_path / "series/Show/Season 01/Show S01E01.pt-BR.srt"


@pytest.mark.parametrize(
    ("filename", "target_name"),
    [
        ("Show.S01E01.pt-BR.forced.srt", "Show S01E01.pt-BR.forced.srt"),
        ("Show.S01E01.en.sdh.srt", "Show S01E01.en.sdh.srt"),
        ("Show.S01E01.en.sdh.cc.srt", "Show S01E01.en.sdh.cc.srt"),
        ("Show.S01E01.forced.srt", "Show S01E01.forced.srt"),
    ],
)
def test_episode_subtitle_qualifiers(tmp_path: Path, filename: str, target_name: str) -> None:
    touch(tmp_path, "Show.S01E01.mkv")
    subtitle = touch(tmp_path, filename)
    config = make_config(tmp_path)
    plan = build_plan(scan_files(config), config)
    operation = next(item for item in plan if item.source == subtitle)
    assert operation.target == tmp_path / "series/Show/Season 01" / target_name


def test_subtitles_with_different_flags_have_different_targets(tmp_path: Path) -> None:
    touch(tmp_path, "Show.S01E01.mkv")
    first = touch(tmp_path, "Show.S01E01.en.sdh.srt")
    second = touch(tmp_path, "Show.S01E01.en.cc.srt")
    config = make_config(tmp_path)
    plan = build_plan(scan_files(config), config)
    subtitles = [item for item in plan if item.source in {first, second}]
    assert {item.target.name for item in subtitles if item.target} == {
        "Show S01E01.en.sdh.srt",
        "Show S01E01.en.cc.srt",
    }
    assert all(item.status is OperationStatus.PLANNED for item in subtitles)


def test_subtitles_with_same_normalized_target_are_conflicts(tmp_path: Path) -> None:
    touch(tmp_path, "Show.S01E01.mkv")
    first = touch(tmp_path, "Show.S01E01.en.sdh.srt")
    second = touch(tmp_path, "Show.S01E01.English.sdh.srt")
    config = make_config(tmp_path)
    plan = build_plan(scan_files(config), config)
    subtitles = [item for item in plan if item.source in {first, second}]
    assert len({item.target for item in subtitles}) == 1
    assert all(item.status is OperationStatus.CONFLICT for item in subtitles)


def test_movie_subtitle_with_language_and_flag(tmp_path: Path) -> None:
    touch(tmp_path, "Movie.Name.2020.mkv")
    subtitle = touch(tmp_path, "Movie.Name.2020.en.forced.srt")
    config = make_config(tmp_path)
    plan = build_plan(scan_files(config), config)
    operation = next(item for item in plan if item.source == subtitle)
    assert operation.target == (
        tmp_path / "movies/Movie Name (2020)/Movie Name (2020).en.forced.srt"
    )


def test_unknown_file(tmp_path: Path) -> None:
    unknown = touch(tmp_path, "video-final-novo.mkv")
    operation = build_plan(scan_files(make_config(tmp_path)), make_config(tmp_path))[0]
    assert operation.source == unknown
    assert operation.media_type is MediaType.UNKNOWN
    assert operation.target is None


def test_existing_destination_is_conflict(tmp_path: Path) -> None:
    touch(tmp_path, "Arrival.2016.mkv")
    destination = tmp_path / "movies/Arrival (2016)/Arrival (2016).mkv"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"existing")
    operation = build_plan(scan_files(make_config(tmp_path)), make_config(tmp_path))[0]
    assert operation.status is OperationStatus.CONFLICT
    assert operation.conflict is not None


def test_path_traversal_rejected(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        ensure_within(tmp_path / "../outside/file.mkv", tmp_path)
    with pytest.raises(ValueError):
        Config(media_root=tmp_path, movies_dir="../outside")


def test_scan_does_not_modify_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = touch(tmp_path, "Arrival.2016.mkv", b"unchanged")
    config_path = tmp_path / "config.toml"
    config_path.write_text(f'media_root = "{tmp_path}"\n', encoding="utf-8")
    assert main(["--config", str(config_path), "scan"]) == 0
    assert source.read_bytes() == b"unchanged"
    assert not (tmp_path / "movies").exists()
    assert "Video" in capsys.readouterr().out


def test_apply_moves_file(tmp_path: Path) -> None:
    source = touch(tmp_path, "Arrival.2016.1080p.mkv", b"movie")
    config = make_config(tmp_path)
    operations = build_plan(scan_files(config), config)
    result = apply_plan(operations, config)
    destination = tmp_path / "movies/Arrival (2016)/Arrival (2016) [1080p].mkv"
    assert result.moved == 1
    assert not source.exists()
    assert destination.read_bytes() == b"movie"


def test_scanner_ignores_symlinks(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    outside = tmp_path / "outside.mkv"
    outside.write_bytes(b"outside")
    (incoming / "linked.mkv").symlink_to(outside)
    assert list(scan_files(make_config(tmp_path))) == []


def test_manually_supplied_outside_source_is_conflict(tmp_path: Path) -> None:
    outside = tmp_path.parent / "Escape.2020.mkv"
    operation = build_plan([FoundFile(outside, ".mkv")], make_config(tmp_path))[0]
    assert operation.status is OperationStatus.CONFLICT


def test_legacy_local_sequence_uses_directory_context(tmp_path: Path) -> None:
    sources = [
        touch(tmp_path, f"Legacy Show/Temporada 1/{number:02d} Episode.divx")
        for number in range(1, 4)
    ]
    config = make_config(tmp_path)
    plan = build_plan(scan_files(config), config)
    targets = {operation.source: operation.target for operation in plan}
    assert [
        targets[source].name if targets[source] is not None else None for source in sources
    ] == [
        "Legacy Show S01E01.divx",
        "Legacy Show S01E02.divx",
        "Legacy Show S01E03.divx",
    ]


def test_legacy_local_numbering_preserves_episode_numbers_with_gaps(tmp_path: Path) -> None:
    sources = [
        touch(tmp_path, f"Legacy Show/Temporada 1/{number:02d} Episode.divx")
        for number in (1, 2, 28)
    ]
    config = make_config(tmp_path)
    plan = build_plan(scan_files(config), config)
    targets = {operation.source: operation.target for operation in plan}
    assert [
        targets[source].name if targets[source] is not None else None for source in sources
    ] == [
        "Legacy Show S01E01.divx",
        "Legacy Show S01E02.divx",
        "Legacy Show S01E28.divx",
    ]


def test_legacy_absolute_sequence_is_rebased_safely(tmp_path: Path) -> None:
    sources = [
        touch(tmp_path, f"Legacy Show/Temporada 3/{number} Episode.avi") for number in (57, 58, 59)
    ]
    config = make_config(tmp_path)
    plan = build_plan(scan_files(config), config)
    targets = {operation.source: operation.target for operation in plan}
    assert [
        targets[source].name if targets[source] is not None else None for source in sources
    ] == [
        "Legacy Show S03E01.avi",
        "Legacy Show S03E02.avi",
        "Legacy Show S03E03.avi",
    ]


def test_legacy_absolute_sequence_57_to_85_maps_to_29_episodes(tmp_path: Path) -> None:
    sources = [
        touch(tmp_path, f"Batman The Animated Series/Temporada 3/{number} Episode.avi")
        for number in range(57, 86)
    ]
    config = make_config(tmp_path)
    plan = build_plan(scan_files(config), config)
    targets = {operation.source: operation.target for operation in plan}
    assert len(plan) == 29
    assert targets[sources[0]] is not None
    assert targets[sources[0]].name == "Batman The Animated Series S03E01.avi"
    assert targets[sources[-1]] is not None
    assert targets[sources[-1]].name == "Batman The Animated Series S03E29.avi"


@pytest.mark.parametrize(
    "numbers",
    [
        (57, 59, 60),
        (57,),
    ],
)
def test_ambiguous_legacy_absolute_numbers_remain_unknown(
    tmp_path: Path, numbers: tuple[int, ...]
) -> None:
    for number in numbers:
        touch(tmp_path, f"Legacy Show/Temporada 3/{number} Episode {number}.avi")
    config = make_config(tmp_path)
    plan = build_plan(scan_files(config), config)
    assert all(operation.media_type is MediaType.UNKNOWN for operation in plan)


def test_duplicate_legacy_numbers_remain_unknown(tmp_path: Path) -> None:
    touch(tmp_path, "Legacy Show/Temporada 3/57 First.avi")
    touch(tmp_path, "Legacy Show/Temporada 3/57 Second.avi")
    touch(tmp_path, "Legacy Show/Temporada 3/58 Third.avi")
    config = make_config(tmp_path)
    plan = build_plan(scan_files(config), config)
    assert all(operation.media_type is MediaType.UNKNOWN for operation in plan)


def test_explicit_and_legacy_formats_are_not_mixed(tmp_path: Path) -> None:
    explicit = touch(tmp_path, "Legacy Show/Temporada 3/Show.S03E01.avi")
    legacy = touch(tmp_path, "Legacy Show/Temporada 3/57 Episode.avi")
    config = make_config(tmp_path)
    plan = build_plan(scan_files(config), config)
    operations = {operation.source: operation for operation in plan}
    assert operations[explicit].media_type is MediaType.EPISODE
    assert operations[legacy].media_type is MediaType.UNKNOWN


def test_legacy_planner_output_is_deterministic(tmp_path: Path) -> None:
    for number in (3, 1, 2):
        touch(tmp_path, f"Legacy Show/Season 1/{number:02d} Episode.divx")
    config = make_config(tmp_path)
    first = build_plan(scan_files(config), config)
    second = build_plan(scan_files(config), config)
    assert [(item.source, item.target) for item in first] == [
        (item.source, item.target) for item in second
    ]


def test_apply_moves_legacy_episode_to_correct_season(tmp_path: Path) -> None:
    source = touch(tmp_path, "Legacy Show/Temporada 1/01 Pilot.divx", b"episode")
    config = make_config(tmp_path)
    operations = build_plan(scan_files(config), config)
    result = apply_plan(operations, config)
    destination = tmp_path / "series/Legacy Show/Season 01/Legacy Show S01E01.divx"
    assert result.moved == 1
    assert not source.exists()
    assert destination.read_bytes() == b"episode"


@pytest.mark.parametrize(
    "label",
    ["Ep.", "Episode", "Episódio", "Capítulo"],
)
def test_named_legacy_sequence_becomes_season_one(tmp_path: Path, label: str) -> None:
    sources = [
        touch(tmp_path, f"Legacy Miniseries/Show - {label} {number:02d} - Name.mp4")
        for number in range(1, 4)
    ]
    config = make_config(tmp_path)
    operations = {
        operation.source: operation for operation in build_plan(scan_files(config), config)
    }
    assert [operations[source].media_type for source in sources] == [MediaType.EPISODE] * 3
    assert [operations[source].target.name for source in sources if operations[source].target] == [
        "Show S01E01.mp4",
        "Show S01E02.mp4",
        "Show S01E03.mp4",
    ]


@pytest.mark.parametrize("label", ["Parte", "Part"])
def test_ambiguous_part_requires_strong_context(tmp_path: Path, label: str) -> None:
    sources = [
        touch(tmp_path, f"Complete Miniseries/Show - {label} {number:02d}.mp4") for number in (1, 2)
    ]
    config = make_config(tmp_path)
    operations = {
        operation.source: operation for operation in build_plan(scan_files(config), config)
    }
    assert all(operations[source].media_type is MediaType.EPISODE for source in sources)


def test_corleone_legacy_miniseries_regression(tmp_path: Path) -> None:
    names = [
        "CORLEONE - Ep. 01 - Prima Puntata, 1943-1958 (576p - DVDRip).mp4",
        "CORLEONE - Ep. 05 - Quinta Puntata, 1982-1987 (576p - DVDRip).mp4",
        "CORLEONE - Ep. 06 - Sesta Puntata, 1988-1993 (576p - DVDRip).mp4",
    ]
    directory = (
        "CORLEONE aka IL CAPO dei CAPI (2007) - Complete ITALIAN Miniseries - 576p DVDRip x264"
    )
    sources = [touch(tmp_path, f"{directory}/{name}") for name in names]
    config = make_config(tmp_path)
    operations = {
        operation.source: operation for operation in build_plan(scan_files(config), config)
    }
    for number, source in zip((1, 5, 6), sources, strict=True):
        operation = operations[source]
        assert operation.media_type is MediaType.EPISODE
        assert operation.target == (
            tmp_path / "series/CORLEONE/Season 01" / f"CORLEONE S01E{number:02d}.mp4"
        )


def test_isolated_named_legacy_candidate_remains_unknown(tmp_path: Path) -> None:
    source = touch(tmp_path, "Show - Ep. 01 - Pilot.mp4")
    config = make_config(tmp_path)
    operation = build_plan(scan_files(config), config)[0]
    assert operation.source == source
    assert operation.media_type is MediaType.UNKNOWN


def test_movie_containing_episode_word_remains_movie(tmp_path: Path) -> None:
    sources = [
        touch(tmp_path, "The.Last.Episode.2020.mkv"),
        touch(tmp_path, "Movie.Episode.2021.mkv"),
        touch(tmp_path, "Episode.2020.mkv"),
    ]
    config = make_config(tmp_path)
    operations = {
        operation.source: operation for operation in build_plan(scan_files(config), config)
    }
    assert all(operations[source].media_type is MediaType.MOVIE for source in sources)


def test_ambiguous_named_legacy_files_remain_unknown(tmp_path: Path) -> None:
    sources = [
        touch(tmp_path, "Mixed/First Show Ep. 01.mp4"),
        touch(tmp_path, "Mixed/Second Show Ep. 02.mp4"),
        touch(tmp_path, "Gapped/Show Ep. 01.mp4"),
        touch(tmp_path, "Gapped/Show Ep. 03.mp4"),
    ]
    config = make_config(tmp_path)
    operations = {
        operation.source: operation for operation in build_plan(scan_files(config), config)
    }
    assert all(operations[source].media_type is MediaType.UNKNOWN for source in sources)


def test_generic_directory_is_not_strong_named_episode_context(tmp_path: Path) -> None:
    sources = [
        touch(tmp_path, "Misc/Movie Ep. 01.mp4"),
        touch(tmp_path, "Misc/Movie Ep. 02.mp4"),
    ]
    config = make_config(tmp_path)
    operations = {
        operation.source: operation for operation in build_plan(scan_files(config), config)
    }
    assert all(operations[source].media_type is MediaType.UNKNOWN for source in sources)


def test_directory_named_after_series_allows_incomplete_sequence(tmp_path: Path) -> None:
    sources = [
        touch(tmp_path, "Show/Show Ep. 01.mp4"),
        touch(tmp_path, "Show/Show Ep. 03.mp4"),
    ]
    config = make_config(tmp_path)
    operations = {
        operation.source: operation for operation in build_plan(scan_files(config), config)
    }
    assert [operations[source].target.name for source in sources if operations[source].target] == [
        "Show S01E01.mp4",
        "Show S01E03.mp4",
    ]


def test_duplicate_numbers_fail_even_with_strong_context(tmp_path: Path) -> None:
    sources = [
        touch(tmp_path, "Show/Show Ep. 01 First.mp4"),
        touch(tmp_path, "Show/Show Episode 01 Second.mp4"),
    ]
    config = make_config(tmp_path)
    operations = {
        operation.source: operation for operation in build_plan(scan_files(config), config)
    }
    assert all(operations[source].media_type is MediaType.UNKNOWN for source in sources)


def test_mixed_series_prefixes_fail_even_with_series_context(tmp_path: Path) -> None:
    sources = [
        touch(tmp_path, "Complete Miniseries/First Show Ep. 01.mp4"),
        touch(tmp_path, "Complete Miniseries/Second Show Ep. 02.mp4"),
    ]
    config = make_config(tmp_path)
    operations = {
        operation.source: operation for operation in build_plan(scan_files(config), config)
    }
    assert all(operations[source].media_type is MediaType.UNKNOWN for source in sources)


@pytest.mark.parametrize(
    ("subtitle_name", "target_name"),
    [
        ("Subs/ger.srt", "Movie (2020).de.srt"),
        ("Subtitles/eng.srt", "Movie (2020).en.srt"),
        ("Subs/German/forced.srt", "Movie (2020).de.forced.srt"),
        ("Subtitles/German/Forced/subtitle.sdh.srt", "Movie (2020).de.forced.sdh.srt"),
    ],
)
def test_generic_subtitle_is_associated_with_single_movie(
    tmp_path: Path, subtitle_name: str, target_name: str
) -> None:
    touch(tmp_path, "Movie Folder/Movie.2020.mkv")
    subtitle = touch(tmp_path, f"Movie Folder/{subtitle_name}")
    config = make_config(tmp_path)
    plan = build_plan(scan_files(config), config)
    operation = next(item for item in plan if item.source == subtitle)
    assert operation.media_type is MediaType.SUBTITLE
    assert operation.target == tmp_path / "movies/Movie (2020)" / target_name


@pytest.mark.parametrize(
    ("subtitle_name", "target_name"),
    [
        ("Subs/pt-BR.srt", "Show S01E01.pt-BR.srt"),
        ("Subs/German/forced.srt", "Show S01E01.de.forced.srt"),
    ],
)
def test_generic_subtitle_is_associated_with_single_episode(
    tmp_path: Path, subtitle_name: str, target_name: str
) -> None:
    touch(tmp_path, "Show Folder/Show.S01E01.mkv")
    subtitle = touch(tmp_path, f"Show Folder/{subtitle_name}")
    config = make_config(tmp_path)
    plan = build_plan(scan_files(config), config)
    operation = next(item for item in plan if item.source == subtitle)
    assert operation.media_type is MediaType.SUBTITLE
    assert operation.target == tmp_path / "series/Show/Season 01" / target_name


def test_nested_subtitle_directory_can_find_media_container(tmp_path: Path) -> None:
    touch(tmp_path, "Movie Folder/Movie.2020.mkv")
    subtitle = touch(tmp_path, "Movie Folder/Extras/Subs/German/subtitle.srt")
    config = make_config(tmp_path)
    operation = next(
        item for item in build_plan(scan_files(config), config) if item.source == subtitle
    )
    assert operation.target == tmp_path / "movies/Movie (2020)/Movie (2020).de.srt"


@pytest.mark.parametrize(
    "video_names",
    [
        (),
        ("Movie.One.2020.mkv", "Movie.Two.2021.mkv"),
        ("Show.S01E01.mkv", "Show.S01E02.mkv"),
        ("Movie.2020.mkv", "Show.S01E01.mkv"),
        ("video-final.mkv",),
    ],
)
def test_ambiguous_context_keeps_generic_subtitle_unknown(
    tmp_path: Path, video_names: tuple[str, ...]
) -> None:
    for name in video_names:
        touch(tmp_path, f"Container/{name}")
    subtitle = touch(tmp_path, "Container/Subs/ger.srt")
    config = make_config(tmp_path)
    operation = next(
        item for item in build_plan(scan_files(config), config) if item.source == subtitle
    )
    assert operation.media_type is MediaType.UNKNOWN
    assert operation.target is None


def test_explicit_subtitle_keeps_priority_over_context(tmp_path: Path) -> None:
    touch(tmp_path, "Container/Show.S01E01.mkv")
    subtitle = touch(tmp_path, "Container/Subs/Show.S01E01.en.srt")
    config = make_config(tmp_path)
    operation = next(
        item for item in build_plan(scan_files(config), config) if item.source == subtitle
    )
    assert operation.target == tmp_path / "series/Show/Season 01/Show S01E01.en.srt"


def test_incompatible_explicit_subtitle_does_not_fall_back_to_context(tmp_path: Path) -> None:
    touch(tmp_path, "Container/Movie.2020.mkv")
    subtitle = touch(tmp_path, "Container/Subs/Other.Movie.2021.en.srt")
    config = make_config(tmp_path)
    operation = next(
        item for item in build_plan(scan_files(config), config) if item.source == subtitle
    )
    assert operation.media_type is MediaType.UNKNOWN


def test_context_does_not_cross_to_sibling_directory(tmp_path: Path) -> None:
    touch(tmp_path, "Movie A/Movie.2020.mkv")
    subtitle = touch(tmp_path, "Movie B/Subs/ger.srt")
    config = make_config(tmp_path)
    operation = next(
        item for item in build_plan(scan_files(config), config) if item.source == subtitle
    )
    assert operation.media_type is MediaType.UNKNOWN


def test_context_does_not_cross_incoming_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside" / "Movie Folder" / "Subs" / "ger.srt"
    found = FoundFile(outside, ".srt")
    config = make_config(tmp_path)
    operation = build_plan([found], config)[0]
    assert operation.media_type is MediaType.UNKNOWN


def test_contextual_subtitles_with_same_target_are_conflicts(tmp_path: Path) -> None:
    touch(tmp_path, "Movie Folder/Movie.2020.mkv")
    first = touch(tmp_path, "Movie Folder/Subs/ger.srt")
    second = touch(tmp_path, "Movie Folder/Subtitles/German.srt")
    config = make_config(tmp_path)
    operations = [
        item for item in build_plan(scan_files(config), config) if item.source in {first, second}
    ]
    assert len({item.target for item in operations}) == 1
    assert all(item.status is OperationStatus.CONFLICT for item in operations)
    assert all(
        item.conflict is not None and "mesmo destino" in item.conflict.reason for item in operations
    )


def test_contextual_subtitle_plan_is_deterministic(tmp_path: Path) -> None:
    touch(tmp_path, "Movie Folder/Movie.2020.mkv")
    touch(tmp_path, "Movie Folder/Subs/en.sdh.srt")
    touch(tmp_path, "Movie Folder/Subs/ger.srt")
    config = make_config(tmp_path)
    first = build_plan(scan_files(config), config)
    second = build_plan(scan_files(config), config)
    assert [(item.source, item.target, item.status) for item in first] == [
        (item.source, item.target, item.status) for item in second
    ]


def test_contextual_subtitle_scan_is_read_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    video = touch(tmp_path, "Movie Folder/Movie.2020.mkv", b"video")
    subtitle = touch(tmp_path, "Movie Folder/Subs/ger.srt", b"subtitle")
    config_path = tmp_path / "config.toml"
    config_path.write_text(f'media_root = "{tmp_path}"\n', encoding="utf-8")
    assert main(["--config", str(config_path), "scan"]) == 0
    assert video.read_bytes() == b"video"
    assert subtitle.read_bytes() == b"subtitle"
    assert not (tmp_path / "movies").exists()
    assert "Subtitle: de" in capsys.readouterr().out

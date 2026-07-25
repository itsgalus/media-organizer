from __future__ import annotations

import ast
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from rich.tree import Tree

import media_organizer.presentation as presentation
from media_organizer.config import Config
from media_organizer.history import (
    HistoryEntry,
    HistoryOperation,
    HistoryRecord,
    UndoResult,
)
from media_organizer.models import (
    Conflict,
    Episode,
    MediaType,
    OperationStatus,
    PlannedOperation,
    Subtitle,
)
from media_organizer.presentation import (
    build_operations_tree,
    determined_progress,
    indeterminate_progress,
    render_doctor,
    render_error,
    render_history,
    render_operations,
    render_summary,
    render_undo_blockers,
    render_undo_preview,
    render_undo_summary,
)


def _label(node: Tree) -> str:
    label = node.label
    return label.plain if hasattr(label, "plain") else str(label)


def test_presentation_does_not_import_re() -> None:
    source = Path(presentation.__file__).read_text(encoding="utf-8")
    imports = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert not any(
        (isinstance(node, ast.Import) and any(alias.name == "re" for alias in node.names))
        or (isinstance(node, ast.ImportFrom) and node.module == "re")
        for node in imports
    )


def test_episode_code_comes_from_official_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Config(media_root=tmp_path)
    source = tmp_path / "incoming/release.mkv"
    calls: list[Path] = []

    def official_parser(path: Path) -> Episode:
        calls.append(path)
        return Episode("Show", 1, (1, 2, 3), ".mkv")

    monkeypatch.setattr(presentation, "parse_episode", official_parser)
    operation = PlannedOperation(
        source,
        MediaType.EPISODE,
        tmp_path / "series/Show/Season 01/release.mkv",
    )
    season = build_operations_tree([operation], config).children[0].children[0].children[0]
    episode = season.children[0]
    assert _label(episode) == "S01E01-E02-E03"
    assert calls == [source]


def test_series_subtitle_episode_comes_from_structured_subtitle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Config(media_root=tmp_path)
    source = tmp_path / "incoming/subtitle.srt"
    parsed = Subtitle(
        language="en",
        extension=".srt",
        episode=Episode("Show", 0, (1,), ".mkv"),
    )
    monkeypatch.setattr(presentation, "parse_subtitle", lambda path: parsed)
    operation = PlannedOperation(
        source,
        MediaType.SUBTITLE,
        tmp_path / "series/Show/Season 00/subtitle.srt",
    )
    season = build_operations_tree([operation], config).children[0].children[0].children[0]
    episode = season.children[0]
    assert _label(episode) == "S00E01"
    assert _label(episode.children[0]) == "Subtitle: en"


def test_operations_tree_is_readable_without_color(tmp_path: Path) -> None:
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None, width=140)
    config = Config(media_root=tmp_path)
    operations = [
        PlannedOperation(
            source=tmp_path / "incoming/Movie.2020.mkv",
            media_type=MediaType.MOVIE,
            target=tmp_path / "movies/Movie (2020)/Movie (2020).mkv",
        ),
        PlannedOperation(
            source=tmp_path / "incoming/unknown.mkv",
            media_type=MediaType.UNKNOWN,
            target=None,
            status=OperationStatus.SKIPPED,
            error="requires review",
        ),
    ]

    render_operations(operations, config, console=console)

    output = stream.getvalue()
    for heading in ("Organization Preview", "Movies", "Unknown", "Video"):
        assert heading in output
    assert "MOVIE" not in output
    assert "PLANNED" not in output
    assert "incoming/Movie.2020.mkv" not in output
    assert "incoming/unknown.mkv" in output
    assert "\x1b[" not in output


def test_tree_groups_movies_videos_and_subtitles(tmp_path: Path) -> None:
    config = Config(media_root=tmp_path)
    movie_dir = tmp_path / "movies/Movie (2020)"
    operations = [
        PlannedOperation(
            tmp_path / "incoming/Movie.2020.en.srt",
            MediaType.SUBTITLE,
            movie_dir / "Movie (2020).en.srt",
        ),
        PlannedOperation(
            tmp_path / "incoming/Movie.2020.mkv",
            MediaType.MOVIE,
            movie_dir / "Movie (2020).mkv",
        ),
    ]

    tree = build_operations_tree(operations, config)

    movies = tree.children[0]
    movie = movies.children[0]
    assert _label(movies) == "Movies"
    assert _label(movie) == "Movie (2020)"
    assert _label(movie.children[0]) == "Video"
    assert _label(movie.children[1]) == "Subtitle: en"


def test_tree_groups_series_by_season_episode_and_subtitle(tmp_path: Path) -> None:
    config = Config(media_root=tmp_path)
    season_dir = tmp_path / "series/Show/Season 01"
    operations = [
        PlannedOperation(
            tmp_path / "incoming/Show.S01E01.mkv",
            MediaType.EPISODE,
            season_dir / "Show S01E01.mkv",
        ),
        PlannedOperation(
            tmp_path / "incoming/Show.S01E01.en.srt",
            MediaType.SUBTITLE,
            season_dir / "Show S01E01.en.srt",
        ),
    ]

    tree = build_operations_tree(operations, config)

    series = tree.children[0]
    show = series.children[0]
    season = show.children[0]
    episode = season.children[0]
    assert [_label(node) for node in (series, show, season, episode)] == [
        "Series",
        "Show",
        "Season 01",
        "S01E01",
    ]
    assert [_label(node) for node in episode.children] == ["Video", "Subtitle: en"]


def test_tree_keeps_unknown_files_in_separate_branch(tmp_path: Path) -> None:
    config = Config(media_root=tmp_path)
    operation = PlannedOperation(
        tmp_path / "incoming/video-final.mkv",
        MediaType.UNKNOWN,
        None,
        OperationStatus.SKIPPED,
    )

    tree = build_operations_tree([operation], config)

    unknown = tree.children[0]
    assert _label(unknown) == "Unknown"
    assert _label(unknown.children[0]) == "video-final.mkv"
    assert _label(unknown.children[0].children[0]) == "source: incoming/video-final.mkv"


def test_tree_preserves_operation_order_within_group(tmp_path: Path) -> None:
    config = Config(media_root=tmp_path)
    movie_dir = tmp_path / "movies/Movie (2020)"
    operations = [
        PlannedOperation(
            tmp_path / f"incoming/Movie.2020.{language}.srt",
            MediaType.SUBTITLE,
            movie_dir / f"Movie (2020).{language}.srt",
        )
        for language in ("pt-BR", "en")
    ]

    tree = build_operations_tree(operations, config)
    rendered_items = [_label(node) for node in tree.children[0].children[0].children]
    assert rendered_items == ["Subtitle: pt-BR", "Subtitle: en"]


@pytest.mark.parametrize(
    ("source_name", "target_name", "expected"),
    [
        ("Movie.2020.pt-BR.srt", "Movie (2020).pt-BR.srt", "Subtitle: pt-BR"),
        ("Movie.2020.en.srt", "Movie (2020).en.srt", "Subtitle: en"),
        (
            "Movie.2020.en.forced.srt",
            "Movie (2020).en.forced.srt",
            "Subtitle: en · forced",
        ),
        (
            "Movie.2020.pt-BR.sdh.cc.srt",
            "Movie (2020).pt-BR.sdh.cc.srt",
            "Subtitle: pt-BR · sdh · cc",
        ),
        (
            "Movie.2020.forced.srt",
            "Movie (2020).forced.srt",
            "Subtitle: unknown · forced",
        ),
        ("Movie.2020.srt", "Movie (2020).srt", "Subtitle: unknown"),
        ("Movie.2020.ptbr.srt", "Movie (2020).pt-BR.srt", "Subtitle: pt-BR"),
        ("Movie.2020.Brazilian.srt", "Movie (2020).pt-BR.srt", "Subtitle: pt-BR"),
        ("Movie.2020.en-US.srt", "Movie (2020).en.srt", "Subtitle: en"),
    ],
)
def test_subtitle_qualifiers_are_human_readable(
    tmp_path: Path,
    source_name: str,
    target_name: str,
    expected: str,
) -> None:
    config = Config(media_root=tmp_path)
    operation = PlannedOperation(
        tmp_path / "incoming" / source_name,
        MediaType.SUBTITLE,
        tmp_path / "movies/Movie (2020)" / target_name,
    )
    tree = build_operations_tree([operation], config)
    assert _label(tree.children[0].children[0].children[0]) == expected


def test_movie_with_only_subtitle_has_no_video_node(tmp_path: Path) -> None:
    config = Config(media_root=tmp_path)
    operation = PlannedOperation(
        tmp_path / "incoming/Movie.2020.pt-BR.srt",
        MediaType.SUBTITLE,
        tmp_path / "movies/Movie (2020)/Movie (2020).pt-BR.srt",
    )
    movie = build_operations_tree([operation], config).children[0].children[0]
    assert [_label(node) for node in movie.children] == ["Subtitle: pt-BR"]


@pytest.mark.parametrize(
    ("season", "target_name", "expected_code"),
    [
        ("Season 00", "Show S00E01.pt-BR.srt", "S00E01"),
        ("Season 01", "Show S01E01-E02.pt-BR.srt", "S01E01-E02"),
        ("Season 01", "Show S01E01-E02-E03.pt-BR.srt", "S01E01-E02-E03"),
    ],
)
def test_series_with_only_subtitle_uses_season_and_complete_episode_code(
    tmp_path: Path,
    season: str,
    target_name: str,
    expected_code: str,
) -> None:
    config = Config(media_root=tmp_path)
    operation = PlannedOperation(
        tmp_path / "incoming" / target_name.replace(" ", "."),
        MediaType.SUBTITLE,
        tmp_path / "series/Show" / season / target_name,
    )
    series = build_operations_tree([operation], config).children[0]
    season_node = series.children[0].children[0]
    assert _label(season_node) == season
    assert _label(season_node.children[0]) == expected_code
    assert _label(season_node.children[0].children[0]) == "Subtitle: pt-BR"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (OperationStatus.MOVED, "Video [MOVED]"),
        (OperationStatus.SKIPPED, "Video [SKIPPED]"),
    ],
)
def test_non_planned_video_status_is_visible(
    tmp_path: Path,
    status: OperationStatus,
    expected: str,
) -> None:
    config = Config(media_root=tmp_path)
    operation = PlannedOperation(
        tmp_path / "incoming/Movie.2020.mkv",
        MediaType.MOVIE,
        tmp_path / "movies/Movie (2020)/Movie (2020).mkv",
        status,
    )
    video = build_operations_tree([operation], config).children[0].children[0].children[0]
    assert _label(video) == expected


def test_failed_operation_shows_error_and_paths(tmp_path: Path) -> None:
    config = Config(media_root=tmp_path)
    operation = PlannedOperation(
        tmp_path / "incoming/Movie.2020.mkv",
        MediaType.MOVIE,
        tmp_path / "movies/Movie (2020)/Movie (2020).mkv",
        OperationStatus.FAILED,
        error="permission denied",
    )
    video = build_operations_tree([operation], config).children[0].children[0].children[0]
    assert _label(video) == "Video [FAILED]"
    assert [_label(node) for node in video.children] == [
        "error: permission denied",
        "source: incoming/Movie.2020.mkv",
        "target: movies/Movie (2020)/Movie (2020).mkv",
    ]


def test_conflict_and_error_are_rendered_in_details(tmp_path: Path) -> None:
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None, width=160)
    config = Config(media_root=tmp_path)
    operation = PlannedOperation(
        source=tmp_path / "incoming/Movie.2020.mkv",
        media_type=MediaType.MOVIE,
        target=tmp_path / "movies/Movie (2020)/Movie (2020).mkv",
        status=OperationStatus.CONFLICT,
        conflict=Conflict("destino já existe"),
    )
    render_operations([operation], config, console=console)
    assert "CONFLICT" in stream.getvalue()
    assert "destino já existe" in stream.getvalue()
    assert "source: incoming/Movie.2020.mkv" in stream.getvalue()
    assert "target: movies/Movie (2020)/Movie (2020).mkv" in stream.getvalue()


def test_summary_handles_zero_elapsed_time(tmp_path: Path) -> None:
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    render_summary([], console=console, processed=0, elapsed=0.0, compact=True)
    assert "Elapsed: 0.00 s" in stream.getvalue()
    assert "Speed: 0.0 files/s" in stream.getvalue()


def test_execution_summary_contains_execution_counters() -> None:
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    operations = [
        PlannedOperation(Path("a"), MediaType.MOVIE, Path("b"), OperationStatus.MOVED),
        PlannedOperation(Path("c"), MediaType.MOVIE, Path("d"), OperationStatus.FAILED),
        PlannedOperation(Path("e"), MediaType.UNKNOWN, None, OperationStatus.SKIPPED),
    ]
    render_summary(operations, console=console, include_execution=True, compact=True)
    output = stream.getvalue()
    assert "Moved: 1" in output
    assert "Failed: 1" in output
    assert "Skipped: 1" in output


def test_doctor_table_contains_expected_columns() -> None:
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    render_doctor([("configuration", True, "valid")], console=console)
    output = stream.getvalue()
    assert "DOCTOR" in output
    assert "Check" in output
    assert "Status" in output
    assert "Detail" in output
    assert "OK" in output


def test_indeterminate_progress_is_disabled_for_redirected_output() -> None:
    console = Console(file=StringIO(), force_terminal=False, color_system=None)
    progress = indeterminate_progress("Scanning incoming...", console=console)
    assert progress.disable


def test_determined_progress_uses_real_total() -> None:
    stream = StringIO()
    console = Console(file=stream, force_terminal=True, color_system=None, width=80)
    with determined_progress(console=console) as progress:
        task = progress.add_task("Moving files", total=2)
        progress.advance(task)
        assert progress.tasks[0].total == 2
        assert progress.tasks[0].completed == 1


def test_filesystem_paths_with_markup_are_rendered_literally(tmp_path: Path) -> None:
    stream = StringIO()
    console = Console(file=stream, force_terminal=True, color_system="standard", width=160)
    config = Config(media_root=tmp_path)
    title = "Movie [red]Cut [bold] [not-a-style] (2020)"
    operation = PlannedOperation(
        source=tmp_path / "incoming/Movie.2020.mkv",
        media_type=MediaType.MOVIE,
        target=tmp_path / "movies" / title / f"{title}.mkv",
    )

    render_operations([operation], config, console=console)

    plain_output = console.export_text() if console.record else stream.getvalue()
    assert title in plain_output
    assert "[red]" in plain_output
    assert "[bold]" in plain_output
    assert "[not-a-style]" in plain_output


def test_conflict_and_error_markup_are_rendered_literally(tmp_path: Path) -> None:
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None, width=160)
    config = Config(media_root=tmp_path)
    markers = "[red]conflict[/red] [bold]error[/bold] [not-a-style]"
    operations = [
        PlannedOperation(
            source=tmp_path / "incoming/conflict.mkv",
            media_type=MediaType.MOVIE,
            target=tmp_path / "movies/conflict.mkv",
            status=OperationStatus.CONFLICT,
            conflict=Conflict(markers),
        ),
        PlannedOperation(
            source=tmp_path / "incoming/error.mkv",
            media_type=MediaType.MOVIE,
            target=tmp_path / "movies/error.mkv",
            status=OperationStatus.FAILED,
            error=markers,
        ),
    ]

    render_operations(operations, config, console=console)
    render_error(f"Erro: {markers}", console=console)

    output = stream.getvalue()
    assert output.count(markers) == 3


def test_history_and_undo_render_external_markup_literally(tmp_path: Path) -> None:
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None, width=160)
    operation = HistoryOperation(
        "incoming/Movie.[red]Cut[/red].2020.mkv",
        "movies/Movie [bold](2020)[/bold]/Movie.mkv",
        "MOVIE",
        "MOVED",
        5,
        1,
    )
    record = HistoryRecord(
        1,
        "2026-07-24T201530.123456Z",
        "2026-07-24T20:15:30.123456Z",
        str(tmp_path),
        "apply",
        1,
        0,
        (operation,),
    )
    render_history(
        [HistoryEntry(tmp_path / "[not-a-style].json", None, "erro [red]literal[/red]")],
        console=console,
        compact=False,
    )
    render_undo_preview(record, console=console)
    render_undo_blockers(("bloqueio [bold]literal[/bold]",), console=console)
    render_undo_summary(UndoResult(record, 0, ("erro",)), console=console, compact=True)
    output = stream.getvalue()
    for literal in (
        "[not-a-style]",
        "[red]literal[/red]",
        "Movie.[red]Cut[/red].2020.mkv",
        "Movie [bold](2020)[/bold]",
        "[bold]literal[/bold]",
    ):
        assert literal in output

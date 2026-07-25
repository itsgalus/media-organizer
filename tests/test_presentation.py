from __future__ import annotations

from io import StringIO
from pathlib import Path

from rich.console import Console

from media_organizer.config import Config
from media_organizer.models import Conflict, MediaType, OperationStatus, PlannedOperation
from media_organizer.presentation import (
    determined_progress,
    indeterminate_progress,
    render_doctor,
    render_error,
    render_operations,
    render_summary,
)


def test_operations_table_is_readable_without_color(tmp_path: Path) -> None:
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
    for heading in ("Type", "Status", "Source", "Target", "Details"):
        assert heading in output
    assert "MOVIE" in output
    assert "UNKNOWN" in output
    assert "incoming/Movie.2020.mkv" in output
    assert "requires review" in output
    assert "\x1b[" not in output


def test_conflict_and_error_are_rendered_in_details(tmp_path: Path) -> None:
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None, width=120)
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
    filename = "Movie.[red]Cut[/red].[bold].[not-a-style].2020.mkv"
    operation = PlannedOperation(
        source=tmp_path / "incoming" / filename,
        media_type=MediaType.MOVIE,
        target=tmp_path / "movies" / filename,
    )

    render_operations([operation], config, console=console)

    plain_output = console.export_text() if console.record else stream.getvalue()
    assert filename in plain_output
    assert "[red]" in plain_output
    assert "[/red]" in plain_output
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

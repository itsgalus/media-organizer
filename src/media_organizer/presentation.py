from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from media_organizer.config import Config
from media_organizer.history import HistoryEntry, HistoryRecord, UndoResult
from media_organizer.models import MediaType, OperationStatus, PlannedOperation
from media_organizer.parser import parse_episode
from media_organizer.subtitles import parse_subtitle


def create_console(*, stderr: bool = False) -> Console:
    return Console(stderr=stderr, highlight=False, width=160)


def display_path(path: Path, config: Config) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(config.media_root.resolve(strict=False)))
    except ValueError:
        return str(path)


def render_mode_banner(title: str, message: str, *, console: Console) -> None:
    console.print(Panel(Text(message), title=title, border_style="cyan", expand=False))


def render_operations(
    operations: list[PlannedOperation],
    config: Config,
    *,
    console: Console,
) -> None:
    console.print(build_operations_tree(operations, config))


def build_operations_tree(
    operations: list[PlannedOperation],
    config: Config,
) -> Tree:
    root = Tree(Text("Organization Preview", style="bold cyan"))
    movies: dict[str, list[PlannedOperation]] = {}
    series: dict[str, dict[str, list[PlannedOperation]]] = {}
    unknown: list[PlannedOperation] = []

    for operation in operations:
        category = _operation_category(operation, config)
        if category == "movies":
            movie = operation.target.parent.name if operation.target else operation.source.stem
            movies.setdefault(movie, []).append(operation)
        elif category == "series":
            series_name, season = _series_location(operation, config)
            series.setdefault(series_name, {}).setdefault(season, []).append(operation)
        else:
            unknown.append(operation)

    if movies:
        movies_node = root.add(Text("Movies", style="bold blue"))
        for movie, movie_operations in movies.items():
            movie_node = movies_node.add(Text(movie))
            for operation in _media_first(movie_operations):
                _add_operation(movie_node, operation, config)

    if series:
        series_root = root.add(Text("Series", style="bold blue"))
        for series_name, seasons in series.items():
            series_node = series_root.add(Text(series_name))
            for season, season_operations in seasons.items():
                season_node = series_node.add(Text(season))
                episodes: dict[str, list[PlannedOperation]] = {}
                for operation in season_operations:
                    episode = _episode_name(operation)
                    episodes.setdefault(episode, []).append(operation)
                for episode, episode_operations in episodes.items():
                    episode_node = season_node.add(Text(episode))
                    for operation in _media_first(episode_operations):
                        _add_operation(episode_node, operation, config)

    if unknown:
        unknown_root = root.add(Text("Unknown", style="bold yellow"))
        for operation in unknown:
            operation_node = unknown_root.add(Text(operation.source.name, style="yellow"))
            source = Text("source: ")
            source.append(display_path(operation.source, config))
            operation_node.add(source)
            _add_exception_details(operation_node, operation, config, include_paths=False)

    return root


def _operation_category(operation: PlannedOperation, config: Config) -> str:
    if operation.media_type is MediaType.MOVIE:
        return "movies"
    if operation.media_type is MediaType.EPISODE:
        return "series"
    if operation.media_type is MediaType.UNKNOWN or operation.target is None:
        return "unknown"
    if _is_relative_to(operation.target, config.movies_path):
        return "movies"
    if _is_relative_to(operation.target, config.series_path):
        return "series"
    return "unknown"


def _series_location(operation: PlannedOperation, config: Config) -> tuple[str, str]:
    if operation.target is None:
        return operation.source.stem, "Unknown Season"
    try:
        relative = operation.target.resolve(strict=False).relative_to(
            config.series_path.resolve(strict=False)
        )
    except ValueError:
        return operation.target.parent.parent.name, operation.target.parent.name
    if len(relative.parts) >= 3:
        return relative.parts[0], relative.parts[1]
    return operation.target.parent.parent.name, operation.target.parent.name


def _episode_name(operation: PlannedOperation) -> str:
    if operation.media_type is MediaType.EPISODE:
        episode = parse_episode(operation.source)
    else:
        subtitle = parse_subtitle(operation.source)
        episode = subtitle.episode if subtitle is not None else None
    if episode is not None:
        return episode.episode_code
    stem = operation.target.stem if operation.target else operation.source.stem
    return stem.split(".", maxsplit=1)[0].rsplit(" ", maxsplit=1)[-1]


def _add_operation(parent: Tree, operation: PlannedOperation, config: Config) -> None:
    if operation.media_type is MediaType.SUBTITLE:
        subtitle = parse_subtitle(operation.source)
        language = subtitle.language if subtitle is not None else None
        flags = subtitle.flags if subtitle is not None else ()
        text = Text("Subtitle: ")
        text.append(language or "unknown")
        for flag in flags:
            text.append(" · ")
            text.append(flag)
    else:
        text = Text("Video")
    if operation.status is not OperationStatus.PLANNED:
        text.append(" [")
        text.append(operation.status.value, style=_status_style(operation))
        text.append("]")
    node = parent.add(text)
    _add_exception_details(node, operation, config)


def _add_exception_details(
    node: Tree,
    operation: PlannedOperation,
    config: Config,
    *,
    include_paths: bool = True,
) -> None:
    if operation.conflict is not None:
        reason = Text("reason: ")
        reason.append(operation.conflict.reason)
        node.add(reason)
    if operation.error:
        error = Text("error: ")
        error.append(operation.error)
        node.add(error)
    if include_paths and operation.status in {OperationStatus.CONFLICT, OperationStatus.FAILED}:
        source = Text("source: ")
        source.append(display_path(operation.source, config))
        node.add(source)
        if operation.target is not None:
            target = Text("target: ")
            target.append(display_path(operation.target, config))
            node.add(target)


def _media_first(operations: list[PlannedOperation]) -> list[PlannedOperation]:
    return sorted(
        operations,
        key=lambda operation: operation.media_type is MediaType.SUBTITLE,
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def summary_counts(
    operations: list[PlannedOperation], *, include_execution: bool = False
) -> dict[str, int]:
    counts = {
        "Movies": sum(op.media_type is MediaType.MOVIE for op in operations),
        "Episodes": sum(op.media_type is MediaType.EPISODE for op in operations),
        "Subtitles": sum(op.media_type is MediaType.SUBTITLE for op in operations),
        "Unknown": sum(op.media_type is MediaType.UNKNOWN for op in operations),
        "Conflicts": sum(op.status is OperationStatus.CONFLICT for op in operations),
        "Planned": sum(op.status is OperationStatus.PLANNED for op in operations),
    }
    if include_execution:
        counts.update(
            {
                "Moved": sum(op.status is OperationStatus.MOVED for op in operations),
                "Failed": sum(op.status is OperationStatus.FAILED for op in operations),
                "Skipped": sum(
                    op.status in {OperationStatus.SKIPPED, OperationStatus.CONFLICT}
                    for op in operations
                ),
            }
        )
    return counts


def render_summary(
    operations: list[PlannedOperation],
    *,
    console: Console,
    include_execution: bool = False,
    processed: int | None = None,
    elapsed: float | None = None,
    compact: bool = False,
) -> None:
    values: dict[str, Any] = summary_counts(operations, include_execution=include_execution)
    if processed is not None:
        values["Processed"] = processed
    if elapsed is not None:
        values["Elapsed"] = f"{elapsed:.2f} s"
        values["Speed"] = f"{_speed(processed or 0, elapsed):.1f} files/s"
    _render_values("Summary:", values, console=console, compact=compact)


def render_audit_summary(
    counts: Mapping[str, int | float],
    *,
    report_path: Path,
    report_format: str,
    processed: int,
    elapsed: float,
    console: Console,
    compact: bool,
) -> None:
    values: dict[str, Any] = {
        "Report": report_path.absolute(),
        "Format": report_format,
        "Movies": counts["movies"],
        "Episodes": counts["episodes"],
        "Subtitles": counts["subtitles"],
        "Unknown": counts["unknown"],
        "Conflicts": counts["conflicts"],
        "Recognized": f"{counts['percentage']:.1f}%",
        "Processed": processed,
        "Elapsed": f"{elapsed:.2f} s",
        "Speed": f"{_speed(processed, elapsed):.1f} files/s",
    }
    title = "Audit Summary:" if compact else "Audit complete."
    _render_values(title, values, console=console, compact=compact)


def render_doctor(
    checks: list[tuple[str, bool, str]],
    *,
    console: Console,
) -> None:
    table = Table(title="DOCTOR")
    table.add_column("Check")
    table.add_column("Status", no_wrap=True)
    table.add_column("Detail", overflow="fold")
    for label, ok, detail in checks:
        table.add_row(
            Text(label),
            Text("OK" if ok else "FAIL", style="green" if ok else "red"),
            Text(detail),
        )
    console.print(table)


def render_confirmation(
    *,
    planned: int,
    ignored: int,
    conflicts: int,
    console: Console,
) -> None:
    message = "\n".join(
        (
            f"{planned} arquivo(s) serão movidos.",
            f"{ignored} arquivo(s) serão ignorados.",
            f"{conflicts} conflito(s) não será executado.",
        )
    )
    console.print(Panel(Text(message), title="Confirmation", border_style="yellow", expand=False))


def render_message(message: str, *, console: Console, style: str | None = None) -> None:
    console.print(Text(message, style=style))


def render_error(message: str, *, console: Console) -> None:
    console.print(Text(message, style="bold red"))


def render_history(
    entries: list[HistoryEntry],
    *,
    console: Console,
    compact: bool,
) -> None:
    if not entries:
        render_message("Nenhuma execução registrada.", console=console, style="yellow")
        return
    if compact:
        for entry in entries:
            if entry.record is None:
                line = Text("INVALID\t")
                line.append(entry.path.name)
                line.append("\t")
                line.append(entry.error or "histórico inválido")
            else:
                record = entry.record
                line = Text(record.id)
                line.append(f"\t{record.moved}\t{record.failed}\t{record.undo_status}")
            console.print(line)
        return

    table = Table(title="History")
    table.add_column("Timestamp")
    table.add_column("ID")
    table.add_column("Moved", justify="right")
    table.add_column("Failed", justify="right")
    table.add_column("Undo status")
    table.add_column("Detail", overflow="fold")
    for entry in entries:
        if entry.record is None:
            table.add_row(
                Text("INVALID", style="red"),
                Text(entry.path.stem),
                Text(""),
                Text(""),
                Text("invalid", style="red"),
                Text(entry.error or "histórico inválido"),
            )
            continue
        record = entry.record
        table.add_row(
            Text(record.timestamp),
            Text(record.id),
            Text(str(record.moved)),
            Text(str(record.failed)),
            Text(record.undo_status),
            Text(record.undo_error or ""),
        )
    console.print(table)


def render_undo_preview(record: HistoryRecord, *, console: Console) -> None:
    tree = Tree(Text("Undo Preview", style="bold cyan"))
    for operation in reversed(record.operations):
        node = tree.add(Text(operation.target))
        target = Text("-> ")
        target.append(operation.source)
        node.add(target)
    console.print(tree)


def render_undo_blockers(blockers: tuple[str, ...], *, console: Console) -> None:
    tree = Tree(Text("Undo blocked", style="bold red"))
    for blocker in blockers:
        tree.add(Text(blocker))
    console.print(tree)


def render_undo_summary(result: UndoResult, *, console: Console, compact: bool) -> None:
    values = {
        "Execution ID": result.record.id,
        "Status": result.record.undo_status,
        "Reverted": result.reverted,
        "Total": len(result.record.operations),
        "Errors": len(result.errors),
    }
    _render_values("Undo Summary:", values, console=console, compact=compact)


def indeterminate_progress(description: str, *, console: Console) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
        disable=not console.is_terminal,
    )


def determined_progress(*, console: Console) -> Progress:
    return Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed:.0f}/{task.total:.0f}"),
        console=console,
        transient=True,
        disable=not console.is_terminal,
    )


def _render_values(
    title: str,
    values: Mapping[str, Any],
    *,
    console: Console,
    compact: bool,
) -> None:
    content = Text()
    for index, (label, value) in enumerate(values.items()):
        if index:
            content.append("\n")
        content.append(f"{label}: ")
        content.append(str(value))
    if compact:
        output = Text(f"{title}\n")
        output.append_text(content)
        console.print(output)
    else:
        console.print(Panel(content, title=title, border_style="blue", expand=False))


def _status_style(operation: PlannedOperation) -> str:
    if operation.status is OperationStatus.FAILED:
        return "red"
    if operation.status in {OperationStatus.CONFLICT, OperationStatus.SKIPPED}:
        return "yellow"
    if operation.media_type is MediaType.UNKNOWN:
        return "yellow"
    return "green"


def _speed(processed: int, elapsed: float) -> float:
    return processed / elapsed if elapsed > 0 else 0.0

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from media_organizer.config import Config
from media_organizer.models import MediaType, OperationStatus, PlannedOperation


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
    table = Table(title="Operations", show_lines=False)
    table.add_column("Type", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Source", overflow="fold")
    table.add_column("Target", overflow="fold")
    table.add_column("Details", overflow="fold")
    for operation in operations:
        details = operation.error or (
            operation.conflict.reason if operation.conflict is not None else ""
        )
        table.add_row(
            Text(operation.media_type.value),
            Text(operation.status.value, style=_status_style(operation)),
            Text(display_path(operation.source, config)),
            Text(display_path(operation.target, config)) if operation.target else Text(),
            Text(details),
        )
    console.print(table)


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

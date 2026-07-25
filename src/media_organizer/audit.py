from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from media_organizer.config import Config
from media_organizer.models import MediaType, OperationStatus, PlannedOperation

LOGGER = logging.getLogger("media_organizer")


class AuditReportError(OSError):
    pass


def audit_counts(operations: list[PlannedOperation]) -> dict[str, int | float]:
    movies = sum(operation.media_type is MediaType.MOVIE for operation in operations)
    episodes = sum(operation.media_type is MediaType.EPISODE for operation in operations)
    subtitles = sum(operation.media_type is MediaType.SUBTITLE for operation in operations)
    unknown = sum(operation.media_type is MediaType.UNKNOWN for operation in operations)
    conflicts = sum(operation.status is OperationStatus.CONFLICT for operation in operations)
    planned = sum(operation.status is OperationStatus.PLANNED for operation in operations)
    recognized = movies + episodes + subtitles
    reviewed_total = recognized + unknown
    percentage = (recognized / reviewed_total * 100) if reviewed_total else 0.0
    return {
        "movies": movies,
        "episodes": episodes,
        "subtitles": subtitles,
        "unknown": unknown,
        "conflicts": conflicts,
        "planned": planned,
        "recognized": recognized,
        "reviewed_total": reviewed_total,
        "percentage": percentage,
    }


def build_audit_report(
    operations: list[PlannedOperation],
    config: Config,
    *,
    report_format: str,
    generated_at: datetime | None = None,
) -> str:
    ordered = sorted(operations, key=lambda operation: str(operation.source))
    if report_format == "tsv":
        return _build_tsv(ordered, config)
    if report_format != "text":
        raise ValueError(f"formato de relatório inválido: {report_format}")
    return _build_text(ordered, config, generated_at or datetime.now().astimezone())


def write_audit_report(path: Path, content: str) -> None:
    created = False
    try:
        with path.open("x", encoding="utf-8", newline="\n") as report_file:
            created = True
            report_file.write(content)
    except FileExistsError as exc:
        raise AuditReportError(
            f"o relatório já existe: {path}. Escolha outro caminho com --output."
        ) from exc
    except OSError as exc:
        if created:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                LOGGER.exception("Unable to remove partial audit report: %s", path)
        raise AuditReportError(f"não foi possível criar o relatório {path}: {exc}") from exc


def _build_text(operations: list[PlannedOperation], config: Config, generated_at: datetime) -> str:
    counts = audit_counts(operations)
    lines = [
        "Media Organizer Audit Report",
        "",
        f"Generated: {generated_at.isoformat(timespec='seconds')}",
        f"media_root: {config.media_root}",
        f"incoming: {config.incoming_path}",
        f"Scanned files: {len(operations)}",
        f"Operations: {len(operations)}",
        f"Movies: {counts['movies']}",
        f"Episodes: {counts['episodes']}",
        f"Subtitles: {counts['subtitles']}",
        f"Unknown: {counts['unknown']}",
        f"Conflicts: {counts['conflicts']}",
        f"Planned: {counts['planned']}",
        "",
    ]
    sections = (
        ("MOVIES", lambda operation: operation.media_type is MediaType.MOVIE),
        ("EPISODES", lambda operation: operation.media_type is MediaType.EPISODE),
        ("SUBTITLES", lambda operation: operation.media_type is MediaType.SUBTITLE),
        ("UNKNOWN", lambda operation: operation.media_type is MediaType.UNKNOWN),
        ("CONFLICTS", lambda operation: operation.status is OperationStatus.CONFLICT),
    )
    for heading, predicate in sections:
        lines.append(f"[{heading}]")
        for operation in operations:
            if predicate(operation):
                lines.extend(_text_operation(operation, config))
        lines.append("")

    manual_review = int(counts["unknown"]) + int(counts["conflicts"])
    lines.extend(
        [
            "Review Summary",
            f"Ready to organize: {counts['planned']}",
            f"Manual review: {manual_review}",
            f"Conflicts: {counts['conflicts']}",
            f"Unknown: {counts['unknown']}",
            f"Recognized: {counts['percentage']:.1f}%",
            "",
        ]
    )
    return "\n".join(lines)


def _text_operation(operation: PlannedOperation, config: Config) -> list[str]:
    lines = [_relative(operation.source, config), f"status: {operation.status.value}"]
    if operation.target is not None:
        lines.insert(1, f"-> {_relative(operation.target, config)}")
    if operation.conflict is not None:
        lines.append(f"reason: {operation.conflict.reason}")
    if operation.error:
        lines.append(f"error: {operation.error}")
    lines.append("")
    return lines


def _build_tsv(operations: list[PlannedOperation], config: Config) -> str:
    lines = ["type\tstatus\tsource\ttarget\treason\terror"]
    for operation in operations:
        fields = (
            operation.media_type.value,
            operation.status.value,
            _relative(operation.source, config),
            _relative(operation.target, config) if operation.target else "",
            operation.conflict.reason if operation.conflict else "",
            operation.error or "",
        )
        lines.append("\t".join(_sanitize_tsv(field) for field in fields))
    return "\n".join(lines) + "\n"


def _relative(path: Path, config: Config) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(config.media_root.resolve(strict=False)))
    except ValueError:
        return str(path)


def _sanitize_tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")

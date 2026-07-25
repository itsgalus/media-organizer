from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
from collections.abc import Iterator
from pathlib import Path

from media_organizer.audit import (
    AuditReportError,
    audit_counts,
    build_audit_report,
    write_audit_report,
)
from media_organizer.config import Config, ConfigurationError, load_config
from media_organizer.models import FoundFile, OperationStatus, PlannedOperation
from media_organizer.organizer import apply_plan
from media_organizer.planner import build_plan, ensure_within
from media_organizer.presentation import (
    create_console,
    determined_progress,
    indeterminate_progress,
    render_audit_summary,
    render_confirmation,
    render_doctor,
    render_error,
    render_message,
    render_mode_banner,
    render_operations,
    render_summary,
)
from media_organizer.scanner import scan_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="media-organizer",
        description=(
            "Organiza mídia local com segurança: scan apenas planeja, apply move arquivos, "
            "audit gera um relatório e doctor diagnostica configuração e filesystem."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="arquivo TOML de configuração (padrão: config.toml)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="mostra logs detalhados no stderr",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="omite operações individuais, mas mantém o resumo",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "scan",
        help="analisa incoming e mostra o plano sem mover arquivos",
        description="Analisa incoming e exibe o plano proposto. Nenhum arquivo é alterado.",
    )
    apply_parser = commands.add_parser(
        "apply",
        help="mostra o plano e move operações autorizadas",
        description="Analisa, mostra o plano, confirma e move apenas operações sem conflito.",
    )
    apply_parser.add_argument(
        "--yes",
        action="store_true",
        help="executa sem pedir confirmação interativa",
    )
    commands.add_parser(
        "doctor",
        help="diagnostica configuração, diretórios e filesystem",
        description="Verifica configuração, diretórios, permissões, espaço e filesystem.",
    )
    audit_parser = commands.add_parser(
        "audit",
        help="analisa a biblioteca sem mover e gera relatório",
        description="Analisa a biblioteca, não move arquivos e gera relatório de validação.",
    )
    audit_parser.add_argument(
        "--output",
        type=Path,
        default=Path("media-organizer-audit.txt"),
        help="caminho do relatório (padrão: media-organizer-audit.txt)",
    )
    audit_parser.add_argument(
        "--format",
        choices=("text", "tsv"),
        default="text",
        help="formato do relatório (padrão: text)",
    )
    return parser


def _configure_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s level=%(levelname)s logger=%(name)s message=%(message)s",
        )
    else:
        root_logger.setLevel(level)


def _doctor(config: Config, *, quiet: bool) -> int:
    console = create_console()
    if not quiet:
        render_mode_banner(
            "DOCTOR",
            "Checking configuration and filesystem.",
            console=console,
        )
    checks: list[tuple[str, bool, str]] = []
    root = config.media_root
    checks.append(("configuração válida", True, str(root)))
    checks.append(("raiz existente", root.is_dir(), str(root)))
    checks.append(("incoming existente", config.incoming_path.is_dir(), str(config.incoming_path)))
    checks.append(("raiz legível", os.access(root, os.R_OK), str(root)))
    checks.append(("raiz gravável", os.access(root, os.W_OK), str(root)))
    checks.append(
        ("incoming legível", os.access(config.incoming_path, os.R_OK), str(config.incoming_path))
    )
    for name, destination in (("movies", config.movies_path), ("series", config.series_path)):
        try:
            ensure_within(destination, root)
            valid = True
        except ValueError:
            valid = False
        checks.append((f"destino {name} válido", valid, str(destination)))

    if root.exists():
        usage = shutil.disk_usage(root)
        checks.append(("espaço livre", usage.free > 0, f"{usage.free / 1024**3:.2f} GiB"))
        try:
            filesystem = str(root.stat().st_dev)
        except OSError as exc:
            filesystem = str(exc)
        checks.append(("filesystem acessível", root.is_dir(), f"device={filesystem}"))

    suspicious = _suspicious_links(config)
    checks.append(
        ("links simbólicos suspeitos", not suspicious, ", ".join(map(str, suspicious)) or "nenhum")
    )
    render_doctor(checks, console=console)
    return 0 if all(ok for _, ok, _ in checks) else 3


def _suspicious_links(config: Config) -> list[Path]:
    suspicious: list[Path] = []
    if not config.incoming_path.is_dir():
        return suspicious
    for directory, dirnames, filenames in os.walk(config.incoming_path, followlinks=False):
        base = Path(directory)
        for name in [*dirnames, *filenames]:
            path = base / name
            if path.is_symlink():
                try:
                    ensure_within(path.resolve(strict=False), config.media_root)
                except ValueError:
                    suspicious.append(path)
    return suspicious


def _confirm_apply(operations: list[PlannedOperation]) -> bool:
    planned = sum(op.status is OperationStatus.PLANNED for op in operations)
    conflicts = sum(op.status is OperationStatus.CONFLICT for op in operations)
    ignored = sum(op.status is OperationStatus.SKIPPED for op in operations)
    render_confirmation(
        planned=planned,
        ignored=ignored,
        conflicts=conflicts,
        console=create_console(),
    )
    try:
        answer = input("Continuar? [y/N] ")
    except EOFError:
        answer = ""
    return answer.strip().casefold() in {"y", "yes", "s", "sim"}


def _count_files(files: Iterator[FoundFile], counter: list[int]) -> Iterator[FoundFile]:
    for found_file in files:
        counter[0] += 1
        yield found_file


def _build_measured_plan(
    config: Config,
    *,
    quiet: bool,
    description: str,
) -> tuple[list[PlannedOperation], int, float]:
    console = create_console()
    counter = [0]
    started = time.perf_counter()
    files = _count_files(iter(scan_files(config)), counter)
    if quiet:
        operations = build_plan(files, config)
    else:
        with indeterminate_progress(description, console=console) as progress:
            progress.add_task(description, total=None)
            operations = build_plan(files, config)
    return operations, counter[0], time.perf_counter() - started


def _run_audit(args: argparse.Namespace, config: Config) -> int:
    console = create_console()
    if not args.quiet:
        render_mode_banner(
            "AUDIT MODE",
            "No media files will be modified.",
            console=console,
        )
    operations, processed, elapsed = _build_measured_plan(
        config,
        quiet=args.quiet,
        description="Scanning incoming and planning operations...",
    )
    report = build_audit_report(operations, config, report_format=args.format)
    write_audit_report(args.output, report)
    counts = audit_counts(operations)
    render_audit_summary(
        counts,
        report_path=args.output,
        report_format=args.format,
        processed=processed,
        elapsed=elapsed,
        console=console,
        compact=args.quiet,
    )
    return 0


def _run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    config = load_config(args.config)
    if args.command == "doctor":
        return _doctor(config, quiet=args.quiet)
    if args.command == "audit":
        return _run_audit(args, config)

    console = create_console()
    if not args.quiet:
        if args.command == "scan":
            render_mode_banner("DRY RUN", "No files will be modified.", console=console)
        else:
            render_mode_banner(
                "APPLY MODE",
                "Files may be moved after confirmation.",
                console=console,
            )
    operations, processed, elapsed = _build_measured_plan(
        config,
        quiet=args.quiet,
        description="Scanning incoming and planning operations...",
    )
    if not args.quiet:
        render_operations(operations, config, console=console)
    render_summary(
        operations,
        console=console,
        processed=processed,
        elapsed=elapsed,
        compact=args.quiet,
    )
    if args.command == "scan":
        return 0

    runnable = sum(op.status is OperationStatus.PLANNED for op in operations)
    if not runnable:
        if not args.quiet:
            render_message(
                "Nenhuma operação segura para executar.", console=console, style="yellow"
            )
        render_summary(
            operations,
            console=console,
            include_execution=True,
            compact=args.quiet,
        )
        return 0

    if not args.yes and not _confirm_apply(operations):
        if not args.quiet:
            render_message("Operação cancelada.", console=console, style="yellow")
        return 0

    apply_started = time.perf_counter()
    if args.quiet or not console.is_terminal:
        result = apply_plan(operations, config)
    else:
        with determined_progress(console=console) as progress:
            task = progress.add_task("Moving files", total=runnable)
            result = apply_plan(
                operations,
                config,
                progress_callback=lambda _operation: progress.advance(task),
            )
    apply_elapsed = time.perf_counter() - apply_started
    if not args.quiet:
        render_operations(result.operations, config, console=console)
    render_summary(
        result.operations,
        console=console,
        include_execution=True,
        processed=runnable,
        elapsed=apply_elapsed,
        compact=args.quiet,
    )
    return 1 if result.failed else 0


def main(argv: list[str] | None = None) -> int:
    error_console = create_console(stderr=True)
    try:
        return _run(argv)
    except ConfigurationError as exc:
        render_error(f"Erro de configuração: {exc}", console=error_console)
        return 2
    except AuditReportError as exc:
        render_error(f"Erro de relatório: {exc}", console=error_console)
        return 2
    except KeyboardInterrupt:
        render_error("Operação interrompida pelo usuário.", console=error_console)
        return 130


if __name__ == "__main__":
    sys.exit(main())

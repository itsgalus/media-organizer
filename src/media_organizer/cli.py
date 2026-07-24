from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

from media_organizer.config import Config, ConfigurationError, load_config
from media_organizer.models import MediaType, OperationStatus, PlannedOperation
from media_organizer.organizer import apply_plan
from media_organizer.planner import build_plan, ensure_within
from media_organizer.scanner import scan_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="media-organizer",
        description=(
            "Organiza mídia local com segurança: scan apenas planeja, apply move arquivos "
            "e doctor diagnostica configuração e filesystem."
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


def _display_path(path: Path, config: Config) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(config.media_root.resolve(strict=False)))
    except ValueError:
        return str(path)


def _render_plan(operations: list[PlannedOperation], config: Config) -> None:
    for operation in operations:
        label = (
            "CONFLICT"
            if operation.status is OperationStatus.CONFLICT
            else operation.media_type.value
        )
        print(f"{label:<10} {_display_path(operation.source, config)}")
        if operation.target:
            target = _display_path(operation.target, config)
            suffix = f" | {operation.conflict.reason}" if operation.conflict else ""
            print(f"{'':<10} -> {target}{suffix}")
        if operation.conflict and operation.target is None:
            print(f"{'':<10} | {operation.conflict.reason}")
        if operation.error:
            print(f"{'':<10} | {operation.error}")


def _render_summary(operations: list[PlannedOperation], *, include_execution: bool = False) -> None:
    counts = {kind: sum(op.media_type is kind for op in operations) for kind in MediaType}
    conflicts = sum(op.status is OperationStatus.CONFLICT for op in operations)
    planned = sum(op.status is OperationStatus.PLANNED for op in operations)
    print("Summary:")
    print(f"  Movies: {counts[MediaType.MOVIE]}")
    print(f"  Episodes: {counts[MediaType.EPISODE]}")
    print(f"  Subtitles: {counts[MediaType.SUBTITLE]}")
    print(f"  Unknown: {counts[MediaType.UNKNOWN]}")
    print(f"  Conflicts: {conflicts}")
    print(f"  Planned: {planned}")
    if include_execution:
        moved = sum(op.status is OperationStatus.MOVED for op in operations)
        failed = sum(op.status is OperationStatus.FAILED for op in operations)
        skipped = sum(
            op.status in {OperationStatus.SKIPPED, OperationStatus.CONFLICT} for op in operations
        )
        print(f"  Moved: {moved}")
        print(f"  Failed: {failed}")
        print(f"  Skipped: {skipped}")


def _doctor(config: Config) -> int:
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
    for label, ok, detail in checks:
        print(f"{'OK' if ok else 'FAIL'}  {label}: {detail}")
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
    print(f"{planned} arquivo(s) serão movidos.")
    print(f"{ignored} arquivo(s) serão ignorados.")
    print(f"{conflicts} conflito(s) não será executado.")
    try:
        answer = input("Continuar? [y/N] ")
    except EOFError:
        answer = ""
    return answer.strip().casefold() in {"y", "yes", "s", "sim"}


def _run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    config = load_config(args.config)
    if args.command == "doctor":
        return _doctor(config)

    operations = build_plan(scan_files(config), config)
    if not args.quiet:
        _render_plan(operations, config)
    _render_summary(operations)
    if args.command == "scan":
        return 0

    runnable = sum(op.status is OperationStatus.PLANNED for op in operations)
    if not runnable:
        if not args.quiet:
            print("Nenhuma operação segura para executar.")
        _render_summary(operations, include_execution=True)
        return 0

    if not args.yes and not _confirm_apply(operations):
        if not args.quiet:
            print("Operação cancelada.")
        return 0

    result = apply_plan(operations, config)
    _render_summary(result.operations, include_execution=True)
    return 1 if result.failed else 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(argv)
    except ConfigurationError as exc:
        print(f"Erro de configuração: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Operação interrompida pelo usuário.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())

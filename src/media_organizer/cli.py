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
    parser = argparse.ArgumentParser(prog="media-organizer")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scan", help="mostra o plano sem alterar arquivos")
    apply_parser = commands.add_parser("apply", help="executa operações seguras")
    apply_parser.add_argument("--yes", action="store_true", help="não pede confirmação")
    commands.add_parser("doctor", help="diagnostica configuração e filesystem")
    return parser


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s level=%(levelname)s logger=%(name)s message=%(message)s",
    )


def _load(path: Path) -> Config:
    try:
        return load_config(path)
    except ConfigurationError as exc:
        raise SystemExit(f"Erro de configuração: {exc}") from exc


def _render_plan(operations: list[PlannedOperation]) -> None:
    for operation in operations:
        print(operation.media_type.value)
        print(f"  Source: {operation.source}")
        if operation.target:
            print(f"  Target: {operation.target}")
        if operation.conflict:
            print(f"  Conflict: {operation.conflict.reason}")
        if operation.error:
            print(f"  Error: {operation.error}")
        print()
    counts = {kind: sum(op.media_type is kind for op in operations) for kind in MediaType}
    conflicts = sum(op.status is OperationStatus.CONFLICT for op in operations)
    print("Summary:")
    print(f"  Movies: {counts[MediaType.MOVIE]}")
    print(f"  Episodes: {counts[MediaType.EPISODE]}")
    print(f"  Subtitles: {counts[MediaType.SUBTITLE]}")
    print(f"  Unknown: {counts[MediaType.UNKNOWN]}")
    print(f"  Conflicts: {conflicts}")


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
    return 0 if all(ok for _, ok, _ in checks) else 1


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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    config = _load(args.config)
    if args.command == "doctor":
        return _doctor(config)

    operations = build_plan(scan_files(config), config)
    _render_plan(operations)
    if args.command == "scan":
        return 0
    runnable = sum(op.status is OperationStatus.PLANNED for op in operations)
    if not runnable:
        print("\nNenhuma operação segura para executar.")
        return 0
    if not args.yes:
        try:
            answer = input(f"\nMover {runnable} arquivo(s)? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().casefold() not in {"y", "yes", "s", "sim"}:
            print("Operação cancelada.")
            return 0
    result = apply_plan(operations, config)
    print(f"\nApply: moved={result.moved} failed={result.failed} skipped={result.skipped}")
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())

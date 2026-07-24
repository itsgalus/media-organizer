from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from media_organizer.config import Config
from media_organizer.models import ExecutionResult, OperationStatus, PlannedOperation
from media_organizer.planner import UnsafePathError, ensure_within

LOGGER = logging.getLogger("media_organizer")


def apply_plan(operations: list[PlannedOperation], config: Config) -> ExecutionResult:
    result = ExecutionResult(operations=operations)
    for operation in operations:
        if operation.status is not OperationStatus.PLANNED or operation.target is None:
            continue
        try:
            _move(operation.source, operation.target, config)
        except (OSError, UnsafePathError) as exc:
            operation.status = OperationStatus.FAILED
            operation.error = str(exc)
            LOGGER.error(
                "move_failed source=%s target=%s error=%s",
                operation.source,
                operation.target,
                exc,
            )
        else:
            operation.status = OperationStatus.MOVED
            LOGGER.info("moved source=%s target=%s", operation.source, operation.target)
    return result


def _move(source: Path, target: Path, config: Config) -> None:
    root = config.media_root.resolve(strict=True)
    incoming = config.incoming_path.resolve(strict=True)
    source_resolved = source.resolve(strict=True)
    target_resolved = ensure_within(target, root)
    ensure_within(source_resolved, incoming)
    if source.is_symlink() or not source_resolved.is_file():
        raise UnsafePathError(f"origem inválida ou link simbólico: {source}")
    if target.exists():
        raise FileExistsError(f"destino já existe: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    ensure_within(target.parent, root)
    if target.parent.is_symlink():
        raise UnsafePathError(f"diretório de destino é link simbólico: {target.parent}")

    try:
        os.rename(source_resolved, target_resolved)
    except OSError as exc:
        if exc.errno != getattr(os, "EXDEV", 18):
            raise
        _copy_without_overwrite(source_resolved, target_resolved)


def _copy_without_overwrite(source: Path, target: Path) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(target, flags, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as destination, source.open("rb") as origin:
            shutil.copyfileobj(origin, destination)
            destination.flush()
            os.fsync(destination.fileno())
        shutil.copystat(source, target, follow_symlinks=False)
        source.unlink()
    except BaseException:
        target.unlink(missing_ok=True)
        raise

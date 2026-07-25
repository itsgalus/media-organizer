from __future__ import annotations

import errno
import logging
import os
import shutil
import stat
from collections.abc import Callable
from pathlib import Path

from media_organizer.config import Config
from media_organizer.models import ExecutionResult, OperationStatus, PlannedOperation
from media_organizer.planner import UnsafePathError, ensure_within

LOGGER = logging.getLogger("media_organizer")


def apply_plan(
    operations: list[PlannedOperation],
    config: Config,
    progress_callback: Callable[[PlannedOperation], None] | None = None,
) -> ExecutionResult:
    result = ExecutionResult(operations=operations)
    for operation in operations:
        if operation.status is not OperationStatus.PLANNED or operation.target is None:
            LOGGER.info("Skipping: source=%s status=%s", operation.source, operation.status.value)
            continue
        try:
            move_file(operation.source, operation.target, config)
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
        finally:
            if progress_callback is not None:
                progress_callback(operation)
    return result


def move_file(source: Path, target: Path, config: Config, *, apply: bool = True) -> None:
    if not apply:
        LOGGER.info("Skipping: dry-run source=%s target=%s", source, target)
        return

    root = config.media_root.resolve(strict=True)
    incoming = config.incoming_path.resolve(strict=True)
    if source.is_symlink():
        raise UnsafePathError(f"origem é um link simbólico: {source}")
    if not source.exists():
        raise FileNotFoundError(f"origem não existe: {source}")

    source_resolved = source.resolve(strict=True)
    target_resolved = ensure_within(target, root)
    ensure_within(source_resolved, incoming)
    if not source_resolved.is_file():
        raise UnsafePathError(f"origem não é um arquivo regular: {source}")
    if target.exists():
        raise FileExistsError(f"destino já existe: {target}")

    _validate_destination_components(root, target.parent)
    target.parent.mkdir(parents=True, exist_ok=True)
    _validate_destination_components(root, target.parent)
    if not source_resolved.exists():
        raise FileNotFoundError(f"origem desapareceu antes da movimentação: {source}")

    LOGGER.info("Moving: %s -> %s", source_resolved, target_resolved)
    try:
        os.link(source_resolved, target_resolved, follow_symlinks=False)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        LOGGER.info("Cross-device copy: %s -> %s", source_resolved, target_resolved)
        _copy_without_overwrite(source_resolved, target_resolved)
        return

    try:
        _fsync_directory(target_resolved.parent)
        source_resolved.unlink()
    except Exception:
        _remove_partial_target(target_resolved)
        raise


def _validate_destination_components(root: Path, parent: Path) -> None:
    root_resolved = root.resolve(strict=True)
    parent_absolute = parent.absolute()
    try:
        relative = parent_absolute.relative_to(root_resolved)
    except ValueError as exc:
        raise UnsafePathError(f"diretório de destino fora da raiz configurada: {parent}") from exc

    current = root_resolved
    for component in relative.parts:
        current /= component
        if current.is_symlink():
            raise UnsafePathError(f"componente de destino é link simbólico: {current}")
    ensure_within(parent, root_resolved)


def _copy_without_overwrite(source: Path, target: Path) -> None:
    source_metadata = source.stat()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(target, flags, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as destination, source.open("rb") as origin:
            shutil.copyfileobj(origin, destination)
            destination.flush()
            os.fsync(destination.fileno())
            os.fchmod(destination.fileno(), stat.S_IMODE(source_metadata.st_mode))
            os.utime(
                destination.fileno(),
                ns=(source_metadata.st_atime_ns, source_metadata.st_mtime_ns),
            )
            os.fsync(destination.fileno())
        _fsync_directory(target.parent)
    except Exception:
        _remove_partial_target(target)
        raise

    try:
        source.unlink()
    except Exception:
        _remove_partial_target(target)
        raise


def _remove_partial_target(target: Path) -> None:
    try:
        target.unlink(missing_ok=True)
    except Exception:
        LOGGER.exception("Failed to remove partial destination: %s", target)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    except OSError as exc:
        unsupported = {errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}
        if exc.errno not in unsupported:
            raise
        LOGGER.debug("Directory fsync unsupported for %s: %s", path, exc)
    finally:
        os.close(descriptor)

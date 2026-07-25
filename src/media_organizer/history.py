from __future__ import annotations

import errno
import json
import os
import re
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Any

from media_organizer.config import Config
from media_organizer.models import MediaType, OperationStatus, PlannedOperation
from media_organizer.organizer import restore_file, validate_restore

HISTORY_VERSION = 1
HISTORY_DIRECTORY = Path(".media-organizer/history")
LOCK_PATH = Path(".media-organizer/lock")
EXECUTION_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{6}\.\d{6}Z$")


class HistoryError(Exception):
    pass


class HistoryValidationError(HistoryError):
    pass


class HistoryWriteError(HistoryError):
    pass


class HistoryLockError(HistoryError):
    pass


@dataclass(frozen=True, slots=True)
class HistoryOperation:
    source: str
    target: str
    media_type: str
    status: str
    size: int | None
    mtime_ns: int | None


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    version: int
    id: str
    timestamp: str
    media_root: str
    command: str
    moved: int
    failed: int
    operations: tuple[HistoryOperation, ...]
    undone_at: str | None = None
    undo_status: str = "not_undone"
    undone_count: int = 0
    undo_error: str | None = None


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    path: Path
    record: HistoryRecord | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class UndoResult:
    record: HistoryRecord
    reverted: int
    errors: tuple[str, ...] = ()

    @property
    def succeeded(self) -> bool:
        return not self.errors and self.reverted == len(self.record.operations)


class HistoryLock(AbstractContextManager["HistoryLock"]):
    def __init__(self, config: Config) -> None:
        self.config = config
        self.path = config.media_root / LOCK_PATH
        self._acquired = False

    def __enter__(self) -> HistoryLock:
        try:
            _metadata_directory(self.config, create=True)
        except HistoryValidationError as exc:
            raise HistoryLockError(str(exc)) from exc
        try:
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise HistoryLockError(
                f"outra operação apply/undo está em andamento: {self.path}"
            ) from exc
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as lock_file:
                lock_file.write(f"{os.getpid()}\n")
                lock_file.flush()
                os.fsync(lock_file.fileno())
        except Exception:
            self.path.unlink(missing_ok=True)
            raise
        self._acquired = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._acquired:
            try:
                self.path.unlink()
            except OSError as exc:
                raise HistoryLockError(
                    f"não foi possível remover o lock {self.path}: {exc}"
                ) from exc
            finally:
                self._acquired = False


def create_history_record(
    operations: list[PlannedOperation],
    config: Config,
    *,
    command: str = "apply",
    now: datetime | None = None,
) -> HistoryRecord | None:
    moved_operations = [
        operation for operation in operations if operation.status is OperationStatus.MOVED
    ]
    if not moved_operations:
        return None
    instant = (now or datetime.now(UTC)).astimezone(UTC)
    timestamp = instant.isoformat(timespec="microseconds").replace("+00:00", "Z")
    execution_id = instant.strftime("%Y-%m-%dT%H%M%S.%fZ")
    history_operations = tuple(
        _history_operation(operation, config) for operation in moved_operations
    )
    return HistoryRecord(
        version=HISTORY_VERSION,
        id=execution_id,
        timestamp=timestamp,
        media_root=str(config.media_root),
        command=command,
        moved=len(history_operations),
        failed=sum(operation.status is OperationStatus.FAILED for operation in operations),
        operations=history_operations,
    )


def write_history(record: HistoryRecord, config: Config, *, update: bool = False) -> Path:
    try:
        history_directory = _history_directory(config, create=True)
    except HistoryValidationError as exc:
        raise HistoryWriteError(str(exc)) from exc
    final_path = history_directory / f"{record.id}.json"
    temporary_path = history_directory / f".{record.id}.{os.getpid()}.tmp"
    if not update and final_path.exists():
        raise HistoryWriteError(f"o histórico já existe e não será sobrescrito: {final_path}")
    try:
        with temporary_path.open("x", encoding="utf-8", newline="\n") as history_file:
            json.dump(asdict(record), history_file, ensure_ascii=False, indent=2)
            history_file.write("\n")
            history_file.flush()
            os.fsync(history_file.fileno())
        if not update and final_path.exists():
            raise HistoryWriteError(f"o histórico já existe e não será sobrescrito: {final_path}")
        if update:
            os.replace(temporary_path, final_path)
        else:
            os.rename(temporary_path, final_path)
        _fsync_directory(history_directory)
    except HistoryWriteError:
        temporary_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        raise HistoryWriteError(f"não foi possível gravar o histórico {final_path}: {exc}") from exc
    return final_path


def list_history(config: Config) -> list[HistoryEntry]:
    history_directory = _history_directory(config, create=False)
    if not history_directory.exists():
        return []
    entries: list[HistoryEntry] = []
    for path in sorted(history_directory.glob("*.json"), reverse=True):
        try:
            record = load_history(path, config)
        except HistoryValidationError as exc:
            entries.append(HistoryEntry(path, None, str(exc)))
        else:
            entries.append(HistoryEntry(path, record))
    return entries


def select_history(config: Config, execution_id: str | None = None) -> HistoryRecord | None:
    entries = list_history(config)
    if execution_id is not None:
        if not EXECUTION_ID_RE.fullmatch(execution_id):
            raise HistoryValidationError(f"ID de execução inválido: {execution_id}")
        matching = [entry for entry in entries if entry.path.stem == execution_id]
        if not matching:
            raise HistoryValidationError(f"execução não encontrada: {execution_id}")
        entry = matching[0]
        if entry.record is None:
            raise HistoryValidationError(entry.error or f"histórico inválido: {entry.path}")
        return entry.record
    for entry in entries:
        record = entry.record
        if record is not None and record.operations and record.undo_status != "undone":
            return record
    invalid = next((entry for entry in entries if entry.record is None), None)
    if invalid is not None:
        raise HistoryValidationError(invalid.error or f"histórico inválido: {invalid.path}")
    return None


def load_history(path: Path, config: Config) -> HistoryRecord:
    try:
        with path.open("r", encoding="utf-8") as history_file:
            raw = json.load(history_file)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HistoryValidationError(f"histórico inválido {path.name}: {exc}") from exc
    try:
        return _parse_record(raw, config)
    except (KeyError, TypeError, ValueError) as exc:
        raise HistoryValidationError(f"histórico inválido {path.name}: {exc}") from exc


def validate_undo(record: HistoryRecord, config: Config) -> tuple[str, ...]:
    blockers: list[str] = []
    for operation in reversed(record.operations):
        current = config.media_root / operation.target
        original = config.media_root / operation.source
        try:
            validate_restore(current, original, config)
        except (OSError, ValueError) as exc:
            blockers.append(f"{operation.target} -> {operation.source}: {exc}")
    return tuple(blockers)


def execute_undo(record: HistoryRecord, config: Config) -> UndoResult:
    """Execute a previously validated undo.

    The caller must hold HistoryLock, have called validate_undo successfully,
    and execute this function immediately after validation. This function does
    not perform collective undo validation.
    """
    reverted = 0
    error: str | None = None
    for operation in reversed(record.operations):
        current = config.media_root / operation.target
        original = config.media_root / operation.source
        try:
            restore_file(current, original, config)
        except (OSError, ValueError) as exc:
            error = f"{operation.target} -> {operation.source}: {exc}"
            break
        reverted += 1

    now = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if error is None:
        updated = replace(
            record,
            undone_at=now,
            undo_status="undone",
            undone_count=reverted,
            undo_error=None,
        )
        errors: tuple[str, ...] = ()
    else:
        updated = replace(
            record,
            undone_at=now,
            undo_status="partially_undone" if reverted else "undo_failed",
            undone_count=reverted,
            undo_error=error,
        )
        errors = (error,)
    write_history(updated, config, update=True)
    return UndoResult(updated, reverted, errors)


def _history_operation(operation: PlannedOperation, config: Config) -> HistoryOperation:
    if operation.target is None:
        raise HistoryWriteError(f"operação MOVED sem destino: {operation.source}")
    source = _relative_path(operation.source, config.media_root)
    target = _relative_path(operation.target, config.media_root)
    try:
        metadata = operation.target.stat()
    except OSError:
        size = None
        mtime_ns = None
    else:
        size = metadata.st_size
        mtime_ns = metadata.st_mtime_ns
    return HistoryOperation(
        source=source,
        target=target,
        media_type=operation.media_type.value,
        status=operation.status.value,
        size=size,
        mtime_ns=mtime_ns,
    )


def _relative_path(path: Path, root: Path) -> str:
    try:
        relative = path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise HistoryWriteError(f"caminho fora de media_root: {path}") from exc
    return relative.as_posix()


def _parse_record(raw: Any, config: Config) -> HistoryRecord:
    if not isinstance(raw, dict):
        raise TypeError("registro deve ser um objeto JSON")
    version = _required_int(raw, "version")
    if version != HISTORY_VERSION:
        raise ValueError(f"version não suportada: {version}")
    execution_id = _required_string(raw, "id")
    if not EXECUTION_ID_RE.fullmatch(execution_id):
        raise ValueError("id inválido")
    timestamp = _required_string(raw, "timestamp")
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp inválido") from exc
    media_root = _required_string(raw, "media_root")
    if Path(media_root).resolve(strict=False) != config.media_root.resolve(strict=False):
        raise ValueError("media_root divergente")
    command = _required_string(raw, "command")
    moved = _required_int(raw, "moved")
    failed = _required_int(raw, "failed")
    raw_operations = raw["operations"]
    if not isinstance(raw_operations, list):
        raise TypeError("operations deve ser uma lista")
    operations = tuple(_parse_operation(item) for item in raw_operations)
    if moved != len(operations):
        raise ValueError("moved diverge da quantidade de operações")
    undo_status = raw.get("undo_status", "not_undone")
    if undo_status not in {"not_undone", "undone", "partially_undone", "undo_failed"}:
        raise ValueError("undo_status inválido")
    undone_at = raw.get("undone_at")
    undo_error = raw.get("undo_error")
    if undone_at is not None and not isinstance(undone_at, str):
        raise TypeError("undone_at deve ser string ou null")
    if undo_error is not None and not isinstance(undo_error, str):
        raise TypeError("undo_error deve ser string ou null")
    undone_count = raw.get("undone_count", 0)
    if not isinstance(undone_count, int) or isinstance(undone_count, bool):
        raise TypeError("undone_count deve ser inteiro")
    if undone_count < 0 or undone_count > moved:
        raise ValueError("undone_count inválido")
    return HistoryRecord(
        version,
        execution_id,
        timestamp,
        media_root,
        command,
        moved,
        failed,
        operations,
        undone_at,
        undo_status,
        undone_count,
        undo_error,
    )


def _parse_operation(raw: Any) -> HistoryOperation:
    if not isinstance(raw, dict):
        raise TypeError("operação deve ser um objeto")
    source = _safe_relative(_required_string(raw, "source"), "source")
    target = _safe_relative(_required_string(raw, "target"), "target")
    media_type = _required_string(raw, "media_type")
    if media_type not in {item.value for item in MediaType}:
        raise ValueError("media_type inválido")
    status = _required_string(raw, "status")
    if status != OperationStatus.MOVED.value:
        raise ValueError("histórico contém operação não MOVED")
    size = raw.get("size")
    mtime_ns = raw.get("mtime_ns")
    for field_name, value in (("size", size), ("mtime_ns", mtime_ns)):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            raise TypeError(f"{field_name} deve ser inteiro ou null")
        if value is not None and value < 0:
            raise ValueError(f"{field_name} não pode ser negativo")
    return HistoryOperation(source, target, media_type, status, size, mtime_ns)


def _safe_relative(value: str, field_name: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError(f"{field_name} não pode ser absoluto")
    if not path.parts or any(part == ".." for part in path.parts):
        raise ValueError(f"{field_name} contém caminho inseguro")
    return path.as_posix()


def _required_string(raw: dict[str, Any], field_name: str) -> str:
    value = raw[field_name]
    if not isinstance(value, str) or not value:
        raise TypeError(f"{field_name} deve ser string não vazia")
    return value


def _required_int(raw: dict[str, Any], field_name: str) -> int:
    value = raw[field_name]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TypeError(f"{field_name} deve ser inteiro não negativo")
    return value


def _metadata_directory(config: Config, *, create: bool) -> Path:
    root = config.media_root.resolve(strict=True)
    directory = config.media_root / ".media-organizer"
    if directory.is_symlink():
        raise HistoryValidationError(f"diretório de metadados é link simbólico: {directory}")
    if create:
        directory.mkdir(exist_ok=True)
    if directory.exists():
        if not directory.is_dir():
            raise HistoryValidationError(f"caminho de metadados não é diretório: {directory}")
        try:
            directory.resolve(strict=True).relative_to(root)
        except ValueError as exc:
            raise HistoryValidationError(
                f"diretório de metadados fora de media_root: {directory}"
            ) from exc
    return directory


def _history_directory(config: Config, *, create: bool) -> Path:
    metadata = _metadata_directory(config, create=create)
    directory = metadata / "history"
    if directory.is_symlink():
        raise HistoryValidationError(f"diretório de histórico é link simbólico: {directory}")
    if create:
        directory.mkdir(exist_ok=True)
    if directory.exists() and not directory.is_dir():
        raise HistoryValidationError(f"caminho de histórico não é diretório: {directory}")
    return directory


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    except OSError as exc:
        if exc.errno not in {errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
            raise
    finally:
        os.close(descriptor)

from __future__ import annotations

import errno
import logging
import os
import shutil
import stat
from pathlib import Path

import pytest

from media_organizer.config import Config
from media_organizer.models import MediaType, OperationStatus, PlannedOperation
from media_organizer.organizer import apply_plan, move_file
from media_organizer.planner import UnsafePathError


def make_library(tmp_path: Path) -> tuple[Config, Path, Path]:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    source = incoming / "Movie.2020.mkv"
    source.write_bytes(b"media-content")
    target = tmp_path / "movies/Movie (2020)/Movie (2020).mkv"
    return Config(media_root=tmp_path), source, target


def exdev_link(
    source: Path,
    target: Path,
    *,
    src_dir_fd: int | None = None,
    dst_dir_fd: int | None = None,
    follow_symlinks: bool = True,
) -> None:
    raise OSError(errno.EXDEV, "cross-device", target)


def test_normal_move_uses_hard_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, source, target = make_library(tmp_path)
    original_link = os.link
    calls: list[tuple[Path, Path, bool]] = []

    def tracked_link(
        origin: Path,
        destination: Path,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        calls.append((origin, destination, follow_symlinks))
        original_link(origin, destination, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(os, "link", tracked_link)
    move_file(source, target, config)
    assert calls == [(source.resolve(strict=False), target.resolve(strict=False), False)]
    assert target.read_bytes() == b"media-content"


def test_normal_move_does_not_use_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, source, target = make_library(tmp_path)

    def forbidden_replace(*args: object, **kwargs: object) -> None:
        pytest.fail("Path.replace não deve ser usado")

    monkeypatch.setattr(Path, "replace", forbidden_replace)
    move_file(source, target, config)
    assert target.exists()


def test_normal_move_does_not_copy_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, source, target = make_library(tmp_path)

    def forbidden_copy(*args: object, **kwargs: object) -> None:
        pytest.fail("cópia não deve ocorrer no mesmo filesystem")

    monkeypatch.setattr(shutil, "copyfileobj", forbidden_copy)
    move_file(source, target, config)
    assert target.exists()


def test_destination_race_does_not_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, source, target = make_library(tmp_path)

    def racing_link(
        origin: Path,
        destination: Path,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        destination.write_bytes(b"racing-winner")
        raise FileExistsError(errno.EEXIST, "exists", destination)

    monkeypatch.setattr(os, "link", racing_link)
    with pytest.raises(FileExistsError):
        move_file(source, target, config)
    assert source.read_bytes() == b"media-content"
    assert target.read_bytes() == b"racing-winner"


def test_link_file_exists_preserves_both_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, source, target = make_library(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        move_file(source, target, config)
    assert source.read_bytes() == b"media-content"
    assert target.read_bytes() == b"existing"


def test_source_unlink_failure_after_link_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, source, target = make_library(tmp_path)
    original_unlink = Path.unlink

    def selective_unlink(self: Path, missing_ok: bool = False) -> None:
        if self == source.resolve(strict=False):
            raise PermissionError("source unlink failed")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", selective_unlink)
    with pytest.raises(PermissionError, match="source unlink failed"):
        move_file(source, target, config)
    assert source.exists()
    assert not target.exists()


def test_exdev_from_link_uses_cross_filesystem_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, source, target = make_library(tmp_path)
    monkeypatch.setattr(os, "link", exdev_link)
    move_file(source, target, config)
    assert not source.exists()
    assert target.read_bytes() == b"media-content"


def test_cross_device_destination_is_opened_exclusively(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, source, target = make_library(tmp_path)
    original_open = os.open
    target_flags: list[int] = []

    def tracked_open(path: os.PathLike[str], flags: int, mode: int = 0o777) -> int:
        if Path(path) == target.resolve(strict=False):
            target_flags.append(flags)
        return original_open(path, flags, mode)

    monkeypatch.setattr(os, "link", exdev_link)
    monkeypatch.setattr(os, "open", tracked_open)
    move_file(source, target, config)
    assert len(target_flags) == 1
    assert target_flags[0] & os.O_EXCL
    assert target_flags[0] & os.O_CREAT


def test_cross_device_does_not_use_copy2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, source, target = make_library(tmp_path)

    def forbidden_copy2(*args: object, **kwargs: object) -> None:
        pytest.fail("copy2 não deve ser usado")

    monkeypatch.setattr(os, "link", exdev_link)
    monkeypatch.setattr(shutil, "copy2", forbidden_copy2)
    move_file(source, target, config)
    assert target.exists()


def test_cross_device_uses_copyfileobj(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, source, target = make_library(tmp_path)
    original_copy = shutil.copyfileobj
    calls = 0

    def tracked_copy(origin: object, destination: object, length: int = 0) -> None:
        nonlocal calls
        calls += 1
        original_copy(origin, destination, length)

    monkeypatch.setattr(os, "link", exdev_link)
    monkeypatch.setattr(shutil, "copyfileobj", tracked_copy)
    move_file(source, target, config)
    assert calls == 1


def test_existing_cross_device_destination_is_never_opened_or_truncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, source, target = make_library(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing")
    monkeypatch.setattr(os, "link", exdev_link)
    with pytest.raises(FileExistsError):
        move_file(source, target, config)
    assert target.read_bytes() == b"existing"
    assert source.exists()


def test_copyfileobj_failure_removes_partial_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, source, target = make_library(tmp_path)

    def failing_copy(origin: object, destination: object, length: int = 0) -> None:
        destination.write(b"partial")  # type: ignore[attr-defined]
        raise OSError("copy failed")

    monkeypatch.setattr(os, "link", exdev_link)
    monkeypatch.setattr(shutil, "copyfileobj", failing_copy)
    with pytest.raises(OSError, match="copy failed"):
        move_file(source, target, config)
    assert source.exists()
    assert not target.exists()


def test_flush_failure_removes_partial_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, source, target = make_library(tmp_path)
    original_fdopen = os.fdopen

    class FlushFailure:
        def __init__(self, wrapped: object) -> None:
            self.wrapped = wrapped

        def __enter__(self) -> FlushFailure:
            self.wrapped.__enter__()  # type: ignore[attr-defined]
            return self

        def __exit__(self, *args: object) -> object:
            return self.wrapped.__exit__(*args)  # type: ignore[attr-defined]

        def write(self, data: bytes) -> int:
            return self.wrapped.write(data)  # type: ignore[attr-defined,no-any-return]

        def flush(self) -> None:
            raise OSError("flush failed")

        def fileno(self) -> int:
            return self.wrapped.fileno()  # type: ignore[attr-defined,no-any-return]

    def failing_fdopen(descriptor: int, mode: str) -> FlushFailure:
        return FlushFailure(original_fdopen(descriptor, mode))

    monkeypatch.setattr(os, "link", exdev_link)
    monkeypatch.setattr(os, "fdopen", failing_fdopen)
    with pytest.raises(OSError, match="flush failed"):
        move_file(source, target, config)
    assert source.exists()
    assert not target.exists()


def test_file_fsync_failure_removes_partial_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, source, target = make_library(tmp_path)

    def failing_fsync(descriptor: int) -> None:
        raise OSError(errno.EIO, "fsync failed")

    monkeypatch.setattr(os, "link", exdev_link)
    monkeypatch.setattr(os, "fsync", failing_fsync)
    with pytest.raises(OSError, match="fsync failed"):
        move_file(source, target, config)
    assert source.exists()
    assert not target.exists()


def test_fchmod_failure_removes_partial_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, source, target = make_library(tmp_path)
    monkeypatch.setattr(os, "link", exdev_link)
    monkeypatch.setattr(os, "fchmod", lambda fd, mode: (_ for _ in ()).throw(OSError("fchmod")))
    with pytest.raises(OSError, match="fchmod"):
        move_file(source, target, config)
    assert source.exists()
    assert not target.exists()


def test_timestamp_failure_removes_partial_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, source, target = make_library(tmp_path)

    def failing_utime(*args: object, **kwargs: object) -> None:
        raise OSError("utime")

    monkeypatch.setattr(os, "link", exdev_link)
    monkeypatch.setattr(os, "utime", failing_utime)
    with pytest.raises(OSError, match="utime"):
        move_file(source, target, config)
    assert source.exists()
    assert not target.exists()


def test_source_unlink_failure_after_copy_removes_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, source, target = make_library(tmp_path)
    original_unlink = Path.unlink

    def selective_unlink(self: Path, missing_ok: bool = False) -> None:
        if self == source.resolve(strict=False):
            raise PermissionError("unlink failed")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(os, "link", exdev_link)
    monkeypatch.setattr(Path, "unlink", selective_unlink)
    with pytest.raises(PermissionError, match="unlink failed"):
        move_file(source, target, config)
    assert source.exists()
    assert not target.exists()


@pytest.mark.parametrize("exception", [KeyboardInterrupt(), SystemExit()])
def test_base_exceptions_are_not_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exception: BaseException
) -> None:
    config, source, target = make_library(tmp_path)

    def interrupted_copy(origin: object, destination: object, length: int = 0) -> None:
        raise exception

    monkeypatch.setattr(os, "link", exdev_link)
    monkeypatch.setattr(shutil, "copyfileobj", interrupted_copy)
    with pytest.raises(type(exception)):
        move_file(source, target, config)


def test_cleanup_failure_does_not_replace_original_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    config, source, target = make_library(tmp_path)
    original_unlink = Path.unlink

    def failing_copy(origin: object, destination: object, length: int = 0) -> None:
        raise OSError("original copy error")

    def failing_cleanup(self: Path, missing_ok: bool = False) -> None:
        if self == target.resolve(strict=False):
            raise PermissionError("cleanup error")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(os, "link", exdev_link)
    monkeypatch.setattr(shutil, "copyfileobj", failing_copy)
    monkeypatch.setattr(Path, "unlink", failing_cleanup)
    with (
        caplog.at_level(logging.ERROR, logger="media_organizer"),
        pytest.raises(OSError, match="original copy error"),
    ):
        move_file(source, target, config)
    assert "Failed to remove partial destination" in caplog.text


def test_cross_device_preserves_basic_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, source, target = make_library(tmp_path)
    source.chmod(0o640)
    timestamp_ns = 1_700_000_000_000_000_000
    os.utime(source, ns=(timestamp_ns, timestamp_ns))
    monkeypatch.setattr(os, "link", exdev_link)
    move_file(source, target, config)
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert target.stat().st_mtime_ns == timestamp_ns


def test_intermediate_symlink_is_rejected(tmp_path: Path) -> None:
    config, source, _ = make_library(tmp_path)
    real_directory = tmp_path / "real"
    real_directory.mkdir()
    (tmp_path / "movies").symlink_to(real_directory, target_is_directory=True)
    target = tmp_path / "movies/nested/movie.mkv"
    with pytest.raises(UnsafePathError, match="link simbólico"):
        move_file(source, target, config)
    assert source.exists()


def test_move_creates_destination_directories(tmp_path: Path) -> None:
    config, source, target = make_library(tmp_path)
    move_file(source, target, config)
    assert target.parent.is_dir()


def test_dry_run_has_no_side_effects(tmp_path: Path) -> None:
    config, source, target = make_library(tmp_path)
    source.chmod(0o640)
    before = source.stat()
    move_file(source, target, config, apply=False)
    after = source.stat()
    assert source.read_bytes() == b"media-content"
    assert not target.parent.exists()
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode)
    assert after.st_mtime_ns == before.st_mtime_ns


def test_missing_source_has_specific_error(tmp_path: Path) -> None:
    config, source, target = make_library(tmp_path)
    source.unlink()
    with pytest.raises(FileNotFoundError, match="origem não existe"):
        move_file(source, target, config)


def test_symlink_source_is_rejected(tmp_path: Path) -> None:
    config, source, target = make_library(tmp_path)
    link = source.with_name("link.mkv")
    link.symlink_to(source)
    with pytest.raises(UnsafePathError, match="link simbólico"):
        move_file(link, target, config)


def test_apply_plan_continues_after_safe_failure(tmp_path: Path) -> None:
    config, source, target = make_library(tmp_path)
    missing = source.with_name("missing.mkv")
    second_target = target.with_name("second.mkv")
    operations = [
        PlannedOperation(missing, MediaType.MOVIE, target),
        PlannedOperation(source, MediaType.MOVIE, second_target),
    ]
    result = apply_plan(operations, config)
    assert result.failed == 1
    assert result.moved == 1
    assert operations[0].status is OperationStatus.FAILED
    assert second_target.exists()


def test_apply_plan_progress_callback_preserves_result(tmp_path: Path) -> None:
    config, source, target = make_library(tmp_path)
    operation = PlannedOperation(source, MediaType.MOVIE, target)
    processed: list[PlannedOperation] = []

    result = apply_plan([operation], config, progress_callback=processed.append)

    assert result.moved == 1
    assert processed == [operation]
    assert processed[0].status is OperationStatus.MOVED


def test_apply_plan_progress_callback_runs_after_each_eligible_operation(tmp_path: Path) -> None:
    config, source, target = make_library(tmp_path)
    missing = source.with_name("missing.mkv")
    operations = [
        PlannedOperation(missing, MediaType.MOVIE, target),
        PlannedOperation(source, MediaType.MOVIE, target.with_name("second.mkv")),
        PlannedOperation(source.with_name("ignored.mkv"), MediaType.UNKNOWN, None),
    ]
    processed: list[PlannedOperation] = []

    apply_plan(operations, config, progress_callback=processed.append)

    assert processed == operations[:2]
    assert [operation.status for operation in processed] == [
        OperationStatus.FAILED,
        OperationStatus.MOVED,
    ]


def test_directory_fsync_unsupported_is_tolerated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, source, target = make_library(tmp_path)
    original_fsync = os.fsync

    def unsupported_for_directory(descriptor: int) -> None:
        mode = os.fstat(descriptor).st_mode
        if stat.S_ISDIR(mode):
            raise OSError(errno.EINVAL, "unsupported")
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", unsupported_for_directory)
    move_file(source, target, config)
    assert target.exists()


def test_arbitrary_directory_fsync_error_rolls_back_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, source, target = make_library(tmp_path)

    def failing_fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError(errno.EIO, "directory fsync failed")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    with pytest.raises(OSError, match="directory fsync failed"):
        move_file(source, target, config)
    assert source.exists()
    assert not target.exists()

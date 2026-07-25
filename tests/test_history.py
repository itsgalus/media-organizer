from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import media_organizer.history as history
from media_organizer.config import Config
from media_organizer.history import (
    HISTORY_VERSION,
    HistoryLock,
    HistoryLockError,
    HistoryRecord,
    HistoryValidationError,
    create_history_record,
    execute_undo,
    list_history,
    load_history,
    select_history,
    validate_undo,
    write_history,
)
from media_organizer.models import MediaType, OperationStatus, PlannedOperation


def make_config(tmp_path: Path) -> Config:
    (tmp_path / "incoming").mkdir(exist_ok=True)
    return Config(media_root=tmp_path)


def moved_operation(config: Config, name: str = "Movie.2020.mkv") -> PlannedOperation:
    source = config.incoming_path / name
    target = config.movies_path / "Movie (2020)" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"media")
    return PlannedOperation(source, MediaType.MOVIE, target, OperationStatus.MOVED)


def make_record(
    config: Config,
    *,
    instant: datetime | None = None,
    operations: list[PlannedOperation] | None = None,
) -> HistoryRecord:
    record = create_history_record(
        operations or [moved_operation(config)],
        config,
        now=instant or datetime(2026, 7, 24, 20, 15, 30, 123456, tzinfo=UTC),
    )
    assert record is not None
    return record


def prepare_undo(config: Config, *, count: int = 1) -> HistoryRecord:
    operations: list[PlannedOperation] = []
    for index in range(count):
        name = f"Movie.{2020 + index}.mkv"
        source = config.incoming_path / name
        target = config.movies_path / f"Movie {index}" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"content-{index}".encode())
        operations.append(PlannedOperation(source, MediaType.MOVIE, target, OperationStatus.MOVED))
    record = make_record(config, operations=operations)
    write_history(record, config)
    return record


def test_history_directory_and_json_are_created(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    path = write_history(make_record(config), config)
    assert path.parent == tmp_path / ".media-organizer/history"
    assert path.is_file()


def test_history_json_contains_required_fields_and_relative_paths(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    record = make_record(config)
    path = write_history(record, config)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == HISTORY_VERSION
    assert payload["timestamp"].endswith("Z")
    assert payload["moved"] == 1
    assert payload["failed"] == 0
    assert payload["operations"][0]["source"] == "incoming/Movie.2020.mkv"
    assert payload["operations"][0]["target"] == "movies/Movie (2020)/Movie.2020.mkv"
    assert payload["operations"][0]["size"] == 5
    assert isinstance(payload["operations"][0]["mtime_ns"], int)


def test_only_moved_operations_are_recorded(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    moved = moved_operation(config)
    failed = PlannedOperation(
        config.incoming_path / "Failed.mkv",
        MediaType.MOVIE,
        config.movies_path / "Failed/Failed.mkv",
        OperationStatus.FAILED,
    )
    skipped = PlannedOperation(
        config.incoming_path / "Unknown.mkv",
        MediaType.UNKNOWN,
        None,
        OperationStatus.SKIPPED,
    )
    record = create_history_record([moved, failed, skipped], config)
    assert record is not None
    assert record.moved == 1
    assert record.failed == 1
    assert len(record.operations) == 1


def test_no_moved_operations_produce_no_record(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    operation = PlannedOperation(
        config.incoming_path / "Failed.mkv",
        MediaType.MOVIE,
        config.movies_path / "Failed/Failed.mkv",
        OperationStatus.FAILED,
    )
    assert create_history_record([operation], config) is None
    assert not (tmp_path / ".media-organizer/history").exists()


def test_history_write_uses_temporary_file_and_atomic_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config(tmp_path)
    calls: list[tuple[Path, Path]] = []
    original_rename = history.os.rename

    def tracked_rename(source: Path, target: Path) -> None:
        calls.append((Path(source), Path(target)))
        original_rename(source, target)

    monkeypatch.setattr(history.os, "rename", tracked_rename)
    final = write_history(make_record(config), config)
    assert calls == [(calls[0][0], final)]
    assert calls[0][0].parent == final.parent
    assert calls[0][0].suffix == ".tmp"


def test_history_does_not_overwrite_existing_record(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    record = make_record(config)
    path = write_history(record, config)
    before = path.read_bytes()
    with pytest.raises(history.HistoryWriteError, match="will not be overwritten"):
        write_history(record, config)
    assert path.read_bytes() == before


def test_history_listing_is_newest_first_and_respects_valid_records(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    first = make_record(config)
    second = make_record(
        config,
        instant=datetime(2026, 7, 24, 21, 15, 30, 123456, tzinfo=UTC),
    )
    write_history(first, config)
    write_history(second, config)
    assert [entry.record.id for entry in list_history(config) if entry.record] == [
        second.id,
        first.id,
    ]


def test_empty_history_and_default_selection(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    assert list_history(config) == []
    assert select_history(config) is None


def test_corrupt_history_is_reported_without_hiding_valid_records(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    valid = make_record(config)
    write_history(valid, config)
    corrupt = tmp_path / ".media-organizer/history/9999-01-01T000000.000000Z.json"
    corrupt.write_text("{broken", encoding="utf-8")
    entries = list_history(config)
    assert entries[0].record is None
    assert entries[0].error is not None
    assert entries[1].record == valid
    assert select_history(config) == valid


@pytest.mark.parametrize(
    ("field", "value", "keyword"),
    [
        ("source", "../escape.mkv", "unsafe"),
        ("target", "/absolute.mkv", "absolute"),
    ],
)
def test_history_rejects_unsafe_paths(tmp_path: Path, field: str, value: str, keyword: str) -> None:
    config = make_config(tmp_path)
    record = make_record(config)
    path = write_history(record, config)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["operations"][0][field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HistoryValidationError, match=keyword):
        load_history(path, config)


def test_history_rejects_divergent_media_root_and_version(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    path = write_history(make_record(config), config)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["media_root"] = str(tmp_path / "other")
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HistoryValidationError, match="media_root"):
        load_history(path, config)
    payload["media_root"] = str(tmp_path)
    payload["version"] = 999
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HistoryValidationError, match="version"):
        load_history(path, config)


def test_undo_restores_source_removes_target_and_preserves_content(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    record = prepare_undo(config)
    operation = record.operations[0]
    assert validate_undo(record, config) == ()
    result = execute_undo(record, config)
    source = config.media_root / operation.source
    target = config.media_root / operation.target
    assert result.succeeded
    assert source.read_bytes() == b"content-0"
    assert not target.exists()
    assert result.record.undo_status == "undone"
    assert result.record.undone_count == 1
    assert (
        load_history(
            tmp_path / ".media-organizer/history" / f"{record.id}.json", config
        ).undo_status
        == "undone"
    )


def test_execute_undo_does_not_validate_internally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config(tmp_path)
    record = prepare_undo(config)

    def unexpected_validation(*args: object) -> tuple[str, ...]:
        raise AssertionError("execute_undo must not call validate_undo")

    monkeypatch.setattr(history, "validate_undo", unexpected_validation)
    result = execute_undo(record, config)
    assert result.succeeded


@pytest.mark.parametrize("condition", ["source_exists", "target_missing", "target_symlink"])
def test_undo_validation_blocks_unsafe_state(tmp_path: Path, condition: str) -> None:
    config = make_config(tmp_path)
    record = prepare_undo(config)
    operation = record.operations[0]
    source = config.media_root / operation.source
    target = config.media_root / operation.target
    if condition == "source_exists":
        source.write_bytes(b"existing")
    elif condition == "target_missing":
        target.unlink()
    else:
        target.unlink()
        target.symlink_to(tmp_path / "elsewhere")
    blockers = validate_undo(record, config)
    assert blockers


def test_undo_runs_in_reverse_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(tmp_path)
    record = prepare_undo(config, count=3)
    calls: list[str] = []
    original_restore = history.restore_file

    def tracked_restore(source: Path, target: Path, current_config: Config) -> None:
        calls.append(source.name)
        original_restore(source, target, current_config)

    monkeypatch.setattr(history, "restore_file", tracked_restore)
    assert validate_undo(record, config) == ()
    assert execute_undo(record, config).succeeded
    assert calls == ["Movie.2022.mkv", "Movie.2021.mkv", "Movie.2020.mkv"]


def test_partial_undo_is_persisted_and_stops_immediately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config(tmp_path)
    record = prepare_undo(config, count=3)
    original_restore = history.restore_file
    calls = 0

    def failing_second(source: Path, target: Path, current_config: Config) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("controlled undo failure")
        original_restore(source, target, current_config)

    monkeypatch.setattr(history, "restore_file", failing_second)
    assert validate_undo(record, config) == ()
    result = execute_undo(record, config)
    assert not result.succeeded
    assert result.reverted == 1
    assert result.record.undo_status == "partially_undone"
    assert "controlled undo failure" in (result.record.undo_error or "")
    assert calls == 2


def test_failure_before_first_restore_is_persisted_as_undo_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config(tmp_path)
    record = prepare_undo(config)

    def failing_restore(*args: object) -> None:
        raise PermissionError("first restore failed")

    monkeypatch.setattr(history, "restore_file", failing_restore)
    assert validate_undo(record, config) == ()
    result = execute_undo(record, config)
    assert result.reverted == 0
    assert result.record.undo_status == "undo_failed"
    assert "first restore failed" in (result.record.undo_error or "")
    persisted = load_history(tmp_path / ".media-organizer/history" / f"{record.id}.json", config)
    assert persisted.undo_status == "undo_failed"


def test_undone_execution_is_not_selected_again(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    record = prepare_undo(config)
    assert validate_undo(record, config) == ()
    assert execute_undo(record, config).succeeded
    assert select_history(config) is None


def test_select_history_by_id_and_missing_id(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    record = prepare_undo(config)
    assert select_history(config, record.id) == record
    with pytest.raises(HistoryValidationError, match="not found"):
        select_history(config, "2026-07-24T000000.000000Z")


def test_lock_blocks_concurrent_operation_and_is_removed(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    lock_path = tmp_path / ".media-organizer/lock"
    with HistoryLock(config):
        assert lock_path.exists()
        with pytest.raises(HistoryLockError, match="another apply/undo"), HistoryLock(config):
            pass
    assert not lock_path.exists()


def test_lock_is_removed_after_error(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    with pytest.raises(RuntimeError, match="controlled"), HistoryLock(config):
        raise RuntimeError("controlled")
    assert not (tmp_path / ".media-organizer/lock").exists()


def test_history_update_preserves_original_file(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    record = make_record(config)
    path = write_history(record, config)
    updated = replace(
        record,
        undone_at=(datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
        undo_status="undo_failed",
        undo_error="failure",
    )
    assert write_history(updated, config, update=True) == path
    assert load_history(path, config).undo_status == "undo_failed"


def test_history_rejects_symbolic_metadata_directory(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".media-organizer").symlink_to(outside, target_is_directory=True)
    with pytest.raises(history.HistoryWriteError, match="symbolic link"):
        write_history(make_record(config), config)
    assert list(outside.iterdir()) == []

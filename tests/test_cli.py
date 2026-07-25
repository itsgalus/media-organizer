from __future__ import annotations

import json
import logging
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import media_organizer.cli as cli
from media_organizer.models import ExecutionResult, OperationStatus


def make_library(tmp_path: Path, *, incoming: bool = True) -> Path:
    if incoming:
        (tmp_path / "incoming").mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(f'media_root = "{tmp_path}"\n', encoding="utf-8")
    return config_path


def create_file(tmp_path: Path, name: str, content: bytes = b"media") -> Path:
    path = tmp_path / "incoming" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def run_cli(config_path: Path, *arguments: str) -> int:
    return cli.main(["--config", str(config_path), *arguments])


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["--help"], "scan apenas planeja"),
        (["scan", "--help"], "Nenhum arquivo é alterado"),
        (["apply", "--help"], "move apenas operações sem conflito"),
        (["doctor", "--help"], "permissões, espaço e filesystem"),
    ],
)
def test_help(
    arguments: list[str],
    expected: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(arguments)
    assert raised.value.code == 0
    assert expected in capsys.readouterr().out


def test_scan_without_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = make_library(tmp_path)
    assert run_cli(config_path, "scan") == 0
    output = capsys.readouterr().out
    assert "Summary:" in output
    assert "Planned: 0" in output


def test_scan_with_movie(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    assert run_cli(config_path, "scan") == 0
    output = capsys.readouterr().out
    assert "Video" in output
    assert "Movies: 1" in output


def test_scan_with_episode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Show.S01E01.mkv")
    run_cli(config_path, "scan")
    output = capsys.readouterr().out
    assert "S01E01" in output
    assert "Episodes: 1" in output


def test_scan_with_subtitle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Show.S01E01.mkv")
    create_file(tmp_path, "Show.S01E01.en.srt")
    run_cli(config_path, "scan")
    output = capsys.readouterr().out
    assert "Subtitle: en" in output
    assert "Subtitles: 1" in output


def test_scan_with_unknown(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "unknown.mkv")
    assert run_cli(config_path, "scan") == 0
    output = capsys.readouterr().out
    assert "incoming/unknown.mkv" in output
    assert "Unknown: 1" in output
    assert "Planned: 0" in output


def test_scan_with_conflict(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    destination = tmp_path / "movies/Movie (2020)/Movie (2020).mkv"
    destination.parent.mkdir(parents=True)
    destination.touch()
    assert run_cli(config_path, "scan") == 0
    output = capsys.readouterr().out
    assert "CONFLICT" in output
    assert "destino já existe" in output


def test_normal_preview_omits_paths(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    run_cli(config_path, "scan")
    output = capsys.readouterr().out
    assert "incoming/Movie.2020.mkv" not in output
    assert "movies/Movie (2020)/Movie (2020).mkv" not in output
    assert "Movie (2020)" in output
    assert str(tmp_path) not in output


def test_summary_counters_are_consistent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    create_file(tmp_path, "Show.S01E01.mkv")
    create_file(tmp_path, "Show.S01E01.en.srt")
    create_file(tmp_path, "unknown.mkv")
    run_cli(config_path, "scan")
    output = capsys.readouterr().out
    for line in (
        "Movies: 1",
        "Episodes: 1",
        "Subtitles: 1",
        "Unknown: 1",
        "Conflicts: 0",
        "Planned: 3",
    ):
        assert line in output


def test_planned_does_not_include_conflict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    destination = tmp_path / "movies/Movie (2020)/Movie (2020).mkv"
    destination.parent.mkdir(parents=True)
    destination.touch()
    run_cli(config_path, "scan")
    output = capsys.readouterr().out
    assert "Conflicts: 1" in output
    assert "Planned: 0" in output


@pytest.mark.parametrize("answer", ["y", "sim"])
def test_apply_accepts_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = make_library(tmp_path)
    source = create_file(tmp_path, "Movie.2020.mkv")
    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    assert run_cli(config_path, "apply") == 0
    assert not source.exists()
    assert (tmp_path / "movies/Movie (2020)/Movie (2020).mkv").exists()
    assert "Moved: 1" in capsys.readouterr().out


def test_apply_cancelled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = make_library(tmp_path)
    source = create_file(tmp_path, "Movie.2020.mkv")
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert run_cli(config_path, "apply") == 0
    assert source.exists()


def test_apply_yes_does_not_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = make_library(tmp_path)
    source = create_file(tmp_path, "Movie.2020.mkv")
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: pytest.fail("input não deve ser chamado com --yes"),
    )
    assert run_cli(config_path, "apply", "--yes") == 0
    assert not source.exists()


def test_apply_does_not_move_unknown(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    source = create_file(tmp_path, "unknown.mkv")
    assert run_cli(config_path, "apply", "--yes") == 0
    assert source.exists()


def test_apply_does_not_move_conflict(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    source = create_file(tmp_path, "Movie.2020.mkv")
    destination = tmp_path / "movies/Movie (2020)/Movie (2020).mkv"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"existing")
    assert run_cli(config_path, "apply", "--yes") == 0
    assert source.exists()
    assert destination.read_bytes() == b"existing"


def test_apply_returns_one_when_operation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")

    def failing_apply(operations: list[object], config: object) -> ExecutionResult:
        operation = operations[0]  # type: ignore[index]
        operation.status = OperationStatus.FAILED  # type: ignore[attr-defined]
        operation.error = "controlled failure"  # type: ignore[attr-defined]
        return ExecutionResult(operations=operations)  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "apply_plan", failing_apply)
    assert run_cli(config_path, "apply", "--yes") == 1
    assert "Failed: 1" in capsys.readouterr().out


def test_apply_continues_after_safe_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "First.2020.mkv")
    create_file(tmp_path, "Second.2021.mkv")

    def mixed_apply(operations: list[object], config: object) -> ExecutionResult:
        operations[0].status = OperationStatus.FAILED  # type: ignore[attr-defined,index]
        operations[1].status = OperationStatus.MOVED  # type: ignore[attr-defined,index]
        return ExecutionResult(operations=operations)  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "apply_plan", mixed_apply)
    assert run_cli(config_path, "apply", "--yes") == 1
    output = capsys.readouterr().out
    assert "Moved: 1" in output
    assert "Failed: 1" in output


def test_configuration_error_returns_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.toml"
    assert run_cli(missing, "scan") == 2
    captured = capsys.readouterr()
    assert "Erro de configuração" in captured.err
    assert "Traceback" not in captured.err


def test_doctor_valid_returns_zero(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    assert run_cli(config_path, "doctor") == 0


def test_doctor_failure_returns_three(tmp_path: Path) -> None:
    config_path = make_library(tmp_path, incoming=False)
    assert run_cli(config_path, "doctor") == 3


def test_keyboard_interrupt_returns_130(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = make_library(tmp_path)

    def interrupted_scan(config: object) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "scan_files", interrupted_scan)
    assert run_cli(config_path, "scan") == 130
    assert "Operação interrompida pelo usuário." in capsys.readouterr().err


def test_quiet_omits_operations_but_keeps_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    assert cli.main(["--config", str(config_path), "--quiet", "scan"]) == 0
    output = capsys.readouterr().out
    assert "MOVIE" not in output
    assert "Summary:" in output
    assert "Movies: 1" in output


def test_verbose_activates_info_logging(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    assert cli.main(["--config", str(config_path), "--verbose", "scan"]) == 0
    assert logging.getLogger().level == logging.INFO


def test_default_logging_is_warning(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    assert run_cli(config_path, "scan") == 0
    assert logging.getLogger().level == logging.WARNING


def test_normal_output_is_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = make_library(tmp_path)
    run_cli(config_path, "scan")
    captured = capsys.readouterr()
    assert "Summary:" in captured.out
    assert "Summary:" not in captured.err


def test_errors_are_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_cli(tmp_path / "missing.toml", "scan")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Erro de configuração" in captured.err


def test_python_module_entry_point_still_works() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "media_organizer", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "media-organizer" in completed.stdout


def test_configured_entry_point() -> None:
    with Path("pyproject.toml").open("rb") as project_file:
        project = tomllib.load(project_file)
    assert project["project"]["scripts"]["media-organizer"] == "media_organizer.cli:main"


@pytest.mark.parametrize("answer", ["", "maybe"])
def test_default_or_invalid_confirmation_cancels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: str
) -> None:
    config_path = make_library(tmp_path)
    source = create_file(tmp_path, "Movie.2020.mkv")
    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    assert run_cli(config_path, "apply") == 0
    assert source.exists()


def test_confirmation_explains_operation_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    create_file(tmp_path, "unknown.mkv")
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    run_cli(config_path, "apply")
    output = capsys.readouterr().out
    assert "1 arquivo(s) serão movidos." in output
    assert "1 arquivo(s) serão ignorados." in output
    assert "0 conflito(s) não será executado." in output


def test_apply_with_zero_operations_does_not_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = make_library(tmp_path)
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: pytest.fail("não deve pedir confirmação sem operações"),
    )
    assert run_cli(config_path, "apply") == 0


def test_rich_is_a_runtime_dependency() -> None:
    with Path("pyproject.toml").open("rb") as project_file:
        project = tomllib.load(project_file)
    assert any(dependency.startswith("rich") for dependency in project["project"]["dependencies"])


@pytest.mark.parametrize(
    ("command", "title", "message"),
    [
        ("scan", "DRY RUN", "No files will be modified."),
        ("apply", "APPLY MODE", "Files may be moved after confirmation."),
        ("audit", "AUDIT MODE", "No media files will be modified."),
        ("doctor", "DOCTOR", "Checking configuration and filesystem."),
    ],
)
def test_mode_banners(
    tmp_path: Path,
    command: str,
    title: str,
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = make_library(tmp_path)
    arguments = [command]
    if command == "audit":
        arguments.extend(["--output", str(tmp_path / "audit.txt")])
    assert run_cli(config_path, *arguments) in {0, 3}
    output = capsys.readouterr().out
    assert title in output
    assert message in output


def test_scan_tree_and_metrics(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    assert run_cli(config_path, "scan") == 0
    output = capsys.readouterr().out
    for value in ("Organization Preview", "Movies", "Video", "Elapsed", "Processed", "Speed"):
        assert value in output


def test_quiet_has_no_banner_table_or_spinner(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    assert cli.main(["--config", str(config_path), "--quiet", "scan"]) == 0
    output = capsys.readouterr().out
    assert "DRY RUN" not in output
    assert "Operations" not in output
    assert "Scanning incoming" not in output
    assert "Summary:" in output


def test_apply_speed_uses_processed_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    timestamps = iter((0.0, 1.0, 10.0, 12.0))
    monkeypatch.setattr(cli.time, "perf_counter", lambda: next(timestamps))

    assert run_cli(config_path, "apply", "--yes") == 0

    output = capsys.readouterr().out
    assert "Processed: 1" in output
    assert "Speed: 0.5 files/s" in output
    assert "Speed: 0.0 files/s" not in output


def test_apply_with_moved_file_creates_history_json(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv", b"history-content")
    assert run_cli(config_path, "apply", "--yes") == 0
    records = list((tmp_path / ".media-organizer/history").glob("*.json"))
    assert len(records) == 1
    payload = json.loads(records[0].read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["moved"] == 1
    assert payload["operations"][0]["source"] == "incoming/Movie.2020.mkv"


def test_apply_without_moved_file_does_not_create_history(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "unknown.mkv")
    assert run_cli(config_path, "apply", "--yes") == 0
    assert not (tmp_path / ".media-organizer/history").exists()


def test_cancelled_apply_does_not_create_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert run_cli(config_path, "apply") == 0
    assert not (tmp_path / ".media-organizer/history").exists()


def test_history_write_failure_after_move_returns_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    monkeypatch.setattr(
        cli,
        "write_history",
        lambda *args, **kwargs: (_ for _ in ()).throw(cli.HistoryWriteError("disk full")),
    )
    assert run_cli(config_path, "apply", "--yes") == 1
    assert (tmp_path / "movies/Movie (2020)/Movie (2020).mkv").exists()
    assert "arquivos foram movidos" in capsys.readouterr().err


def test_history_empty_and_limit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = make_library(tmp_path)
    assert run_cli(config_path, "history") == 0
    assert "Nenhuma execução registrada" in capsys.readouterr().out
    for year in (2020, 2021):
        create_file(tmp_path, f"Movie.{year}.mkv")
        assert run_cli(config_path, "apply", "--yes") == 0
    assert run_cli(config_path, "history", "--limit", "1") == 0
    output = capsys.readouterr().out
    assert output.count("not_undone") == 1


def test_invalid_history_limit_exits_with_two() -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["history", "--limit", "0"])
    assert raised.value.code == 2


def test_history_quiet_is_compact_and_literal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    assert run_cli(config_path, "apply", "--yes") == 0
    capsys.readouterr()
    assert cli.main(["--config", str(config_path), "--quiet", "history"]) == 0
    output = capsys.readouterr().out
    assert "not_undone" in output
    assert "History" not in output


def test_undo_without_history_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = make_library(tmp_path)
    assert run_cli(config_path, "undo", "--yes") == 0
    assert "Nenhuma execução elegível" in capsys.readouterr().out


def test_undo_preview_and_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = make_library(tmp_path)
    source = create_file(tmp_path, "Movie.2020.mkv")
    assert run_cli(config_path, "apply", "--yes") == 0
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert run_cli(config_path, "undo") == 0
    output = capsys.readouterr().out
    assert "Undo Preview" in output
    assert "movies/Movie (2020)/Movie (2020).mkv" in output
    assert "incoming/Movie.2020.mkv" in output
    assert not source.exists()


def test_undo_yes_restores_file_and_persists_status(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    source = create_file(tmp_path, "Movie.2020.mkv", b"undo-content")
    assert run_cli(config_path, "apply", "--yes") == 0
    target = tmp_path / "movies/Movie (2020)/Movie (2020).mkv"
    record_path = next((tmp_path / ".media-organizer/history").glob("*.json"))
    assert run_cli(config_path, "undo", "--yes") == 0
    assert source.read_bytes() == b"undo-content"
    assert not target.exists()
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    assert payload["undo_status"] == "undone"
    assert payload["undone_count"] == 1


def test_undo_by_id_and_missing_id(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    assert run_cli(config_path, "apply", "--yes") == 0
    record_path = next((tmp_path / ".media-organizer/history").glob("*.json"))
    assert run_cli(config_path, "undo", "--id", record_path.stem, "--yes") == 0
    assert run_cli(config_path, "undo", "--id", "2026-07-24T000000.000000Z", "--yes") == 2


def test_corrupt_history_returns_two_for_undo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = make_library(tmp_path)
    directory = tmp_path / ".media-organizer/history"
    directory.mkdir(parents=True)
    (directory / "2026-07-24T000000.000000Z.json").write_text("{broken", encoding="utf-8")
    assert run_cli(config_path, "undo", "--yes") == 2
    assert "Erro de histórico" in capsys.readouterr().err


def test_lock_blocks_apply_and_is_preserved(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    source = create_file(tmp_path, "Movie.2020.mkv")
    lock = tmp_path / ".media-organizer/lock"
    lock.parent.mkdir()
    lock.write_text("other\n", encoding="utf-8")
    assert run_cli(config_path, "apply", "--yes") == 1
    assert source.exists()
    assert lock.exists()


def test_lock_blocks_undo(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    assert run_cli(config_path, "apply", "--yes") == 0
    lock = tmp_path / ".media-organizer/lock"
    lock.write_text("other\n", encoding="utf-8")
    assert run_cli(config_path, "undo", "--yes") == 1


def test_undo_revalidates_filesystem_inside_lock_after_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = make_library(tmp_path)
    source = create_file(tmp_path, "Movie.2020.mkv", b"original")
    assert run_cli(config_path, "apply", "--yes") == 0
    target = tmp_path / "movies/Movie (2020)/Movie (2020).mkv"

    def change_filesystem_before_lock(prompt: str) -> str:
        source.write_bytes(b"racing-file")
        return "y"

    monkeypatch.setattr("builtins.input", change_filesystem_before_lock)
    assert run_cli(config_path, "undo") == 1
    assert source.read_bytes() == b"racing-file"
    assert target.read_bytes() == b"original"
    assert not (tmp_path / ".media-organizer/lock").exists()
    assert "Undo blocked" in capsys.readouterr().err


def test_undo_validates_before_confirmation_and_again_inside_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    assert run_cli(config_path, "apply", "--yes") == 0
    lock_path = tmp_path / ".media-organizer/lock"
    validation_lock_states: list[bool] = []
    events: list[str] = []
    original_validate = cli.validate_undo
    original_execute = cli.execute_undo

    def tracked_validate(record: object, config: object) -> tuple[str, ...]:
        validation_lock_states.append(lock_path.exists())
        events.append("validate")
        return original_validate(record, config)

    def tracked_execute(record: object, config: object) -> object:
        assert lock_path.exists()
        events.append("execute")
        return original_execute(record, config)

    monkeypatch.setattr(cli, "validate_undo", tracked_validate)
    monkeypatch.setattr(cli, "execute_undo", tracked_execute)
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    assert run_cli(config_path, "undo") == 0
    assert validation_lock_states == [False, True]
    assert events == ["validate", "validate", "execute"]
    assert not lock_path.exists()


def test_undo_keyboard_interrupt_returns_130(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = make_library(tmp_path)
    monkeypatch.setattr(
        cli,
        "select_history",
        lambda *args: (_ for _ in ()).throw(KeyboardInterrupt),
    )
    assert run_cli(config_path, "undo", "--yes") == 130

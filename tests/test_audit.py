from __future__ import annotations

import os
import stat
from datetime import datetime
from pathlib import Path

import pytest

import media_organizer.cli as cli
from media_organizer.audit import build_audit_report
from media_organizer.config import Config
from media_organizer.models import MediaType, OperationStatus, PlannedOperation

REALISTIC_NAMES = (
    "Interstellar.2014.2160p.HDR.BluRay.REMUX.mkv",
    "Dune.Part.Two.2024.2160p.WEB-DL.DV.HDR10+.mkv",
    "Batman.The.Animated.Series.S01E01.1080p.BluRay.x265.mkv",
    "Batman.The.Animated.Series.S01E01.pt-BR.srt",
    "Show.S00E01.mkv",
    "Show.S01E01E02.mkv",
    "Movie.Name.2020.en.forced.srt",
    "video-final-novo.mkv",
    "arquivo-sem-ano.mkv",
    "poster.jpg",
    "sample.nfo",
    "partial.part",
)


def make_library(tmp_path: Path) -> Path:
    (tmp_path / "incoming").mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(f'media_root = "{tmp_path}"\n', encoding="utf-8")
    return config_path


def create_file(tmp_path: Path, name: str, content: bytes = b"media") -> Path:
    path = tmp_path / "incoming" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def run_audit(config_path: Path, output: Path, *arguments: str) -> int:
    return cli.main(
        [
            "--config",
            str(config_path),
            "audit",
            "--output",
            str(output),
            *arguments,
        ]
    )


def test_audit_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["audit", "--help"])
    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "não move arquivos" in output
    assert "--output" in output
    assert "--format" in output


def test_audit_empty_library(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    report = tmp_path / "empty.txt"
    assert run_audit(config_path, report) == 0
    assert report.exists()


def test_audit_lists_contextually_associated_subtitle(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie Folder/Movie.2020.mkv")
    create_file(tmp_path, "Movie Folder/Subs/ger.srt")
    report = tmp_path / "contextual.txt"
    assert run_audit(config_path, report) == 0
    content = report.read_text(encoding="utf-8")
    assert "Subtitles: 1" in content
    assert "movies/Movie (2020)/Movie (2020).de.srt" in content


def test_default_report_is_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = make_library(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--config", str(config_path), "audit"]) == 0
    assert (tmp_path / "media-organizer-audit.txt").exists()


def test_custom_report_is_created(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    report = tmp_path / "custom-report.txt"
    assert run_audit(config_path, report) == 0
    assert report.is_file()


def test_audit_does_not_move_files(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    source = create_file(tmp_path, "Movie.2020.mkv")
    report = tmp_path / "audit.txt"
    assert run_audit(config_path, report) == 0
    assert source.exists()
    assert not (tmp_path / "movies/Movie (2020)/Movie (2020).mkv").exists()


@pytest.mark.parametrize("directory", ["movies", "series"])
def test_audit_does_not_create_library_destinations(tmp_path: Path, directory: str) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    assert run_audit(config_path, tmp_path / "audit.txt") == 0
    assert not (tmp_path / directory).exists()


def test_existing_report_returns_two_without_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = make_library(tmp_path)
    report = tmp_path / "audit.txt"
    report.write_text("keep me", encoding="utf-8")
    assert run_audit(config_path, report) == 2
    assert report.read_text(encoding="utf-8") == "keep me"
    assert "Escolha outro caminho" in capsys.readouterr().err


def test_text_report_header(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    report = tmp_path / "audit.txt"
    run_audit(config_path, report)
    assert report.read_text(encoding="utf-8").startswith("Media Organizer Audit Report")


def test_text_report_has_iso_timestamp(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    report = tmp_path / "audit.txt"
    run_audit(config_path, report)
    generated_line = next(
        line
        for line in report.read_text(encoding="utf-8").splitlines()
        if line.startswith("Generated:")
    )
    datetime.fromisoformat(generated_line.removeprefix("Generated:").strip())


def test_report_contains_media_root_and_incoming(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    report = tmp_path / "audit.txt"
    run_audit(config_path, report)
    content = report.read_text(encoding="utf-8")
    assert f"media_root: {tmp_path}" in content
    assert f"incoming: {tmp_path / 'incoming'}" in content


def test_report_contains_counters(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    report = tmp_path / "audit.txt"
    run_audit(config_path, report)
    content = report.read_text(encoding="utf-8")
    assert "Scanned files: 1" in content
    assert "Operations: 1" in content
    assert "Movies: 1" in content
    assert "Planned: 1" in content


@pytest.mark.parametrize("section", ["[UNKNOWN]", "[CONFLICTS]"])
def test_report_contains_review_sections(tmp_path: Path, section: str) -> None:
    config_path = make_library(tmp_path)
    report = tmp_path / "audit.txt"
    run_audit(config_path, report)
    assert section in report.read_text(encoding="utf-8")


def test_report_lists_movie(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Interstellar.2014.mkv")
    report = tmp_path / "audit.txt"
    run_audit(config_path, report)
    content = report.read_text(encoding="utf-8")
    assert "[MOVIES]" in content
    assert "incoming/Interstellar.2014.mkv" in content


def test_report_lists_episode(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Show.S01E01.mkv")
    report = tmp_path / "audit.txt"
    run_audit(config_path, report)
    content = report.read_text(encoding="utf-8")
    assert "[EPISODES]" in content
    assert "incoming/Show.S01E01.mkv" in content


def test_report_lists_subtitle(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Show.S01E01.mkv")
    create_file(tmp_path, "Show.S01E01.pt-BR.srt")
    report = tmp_path / "audit.txt"
    run_audit(config_path, report)
    content = report.read_text(encoding="utf-8")
    assert "[SUBTITLES]" in content
    assert "incoming/Show.S01E01.pt-BR.srt" in content


def test_report_paths_are_relative(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    report = tmp_path / "audit.txt"
    run_audit(config_path, report)
    operation_lines = report.read_text(encoding="utf-8").split("[MOVIES]", maxsplit=1)[1]
    assert "incoming/Movie.2020.mkv" in operation_lines
    assert "-> movies/Movie (2020)/Movie (2020).mkv" in operation_lines


def test_report_order_is_deterministic(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Zulu.2020.mkv")
    create_file(tmp_path, "Alpha.2021.mkv")
    report = tmp_path / "audit.txt"
    run_audit(config_path, report)
    content = report.read_text(encoding="utf-8")
    assert content.index("incoming/Alpha.2021.mkv") < content.index("incoming/Zulu.2020.mkv")


def test_recognized_percentage(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    create_file(tmp_path, "Show.S01E01.mkv")
    create_file(tmp_path, "unknown.mkv")
    report = tmp_path / "audit.txt"
    run_audit(config_path, report)
    assert "Recognized: 66.7%" in report.read_text(encoding="utf-8")


def test_zero_percentage_for_empty_library(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    report = tmp_path / "audit.txt"
    run_audit(config_path, report)
    assert "Recognized: 0.0%" in report.read_text(encoding="utf-8")


def test_unknown_does_not_fail_audit(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "unknown.mkv")
    assert run_audit(config_path, tmp_path / "audit.txt") == 0


def test_conflict_does_not_fail_audit(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    destination = tmp_path / "movies/Movie (2020)/Movie (2020).mkv"
    destination.parent.mkdir(parents=True)
    destination.touch()
    report = tmp_path / "audit.txt"
    assert run_audit(config_path, report) == 0
    assert "reason: destino já existe" in report.read_text(encoding="utf-8")


def test_tsv_header_and_one_line_per_operation(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    create_file(tmp_path, "unknown.mkv")
    report = tmp_path / "audit.tsv"
    assert run_audit(config_path, report, "--format", "tsv") == 0
    lines = report.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "type\tstatus\tsource\ttarget\treason\terror"
    assert len(lines) == 3


def test_tsv_sanitizes_tabs_and_newlines(tmp_path: Path) -> None:
    config = Config(media_root=tmp_path)
    operation = PlannedOperation(
        source=tmp_path / "incoming/name\twith\ncontrols.mkv",
        media_type=MediaType.UNKNOWN,
        target=None,
        status=OperationStatus.SKIPPED,
        error="bad\tvalue\ncontinued",
    )
    report = build_audit_report([operation], config, report_format="tsv")
    data_line = report.splitlines()[1]
    assert len(data_line.split("\t")) == 6
    assert "\n" not in data_line
    assert "bad value continued" in data_line


def test_realistic_ignored_extensions_do_not_appear(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    for name in REALISTIC_NAMES:
        create_file(tmp_path, name)
    report = tmp_path / "audit.txt"
    run_audit(config_path, report)
    content = report.read_text(encoding="utf-8")
    for ignored in ("poster.jpg", "sample.nfo", "partial.part"):
        assert ignored not in content
    for unknown in ("video-final-novo.mkv", "arquivo-sem-ano.mkv"):
        assert unknown in content


def test_quiet_output_is_reduced(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    report = tmp_path / "audit.txt"
    assert (
        cli.main(
            [
                "--config",
                str(config_path),
                "--quiet",
                "audit",
                "--output",
                str(report),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Audit complete." not in output
    assert f"Report: {report}" in output
    assert "Movies: 1" in output


def test_report_write_error_returns_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = make_library(tmp_path)
    report = tmp_path / "missing-parent/audit.txt"
    assert run_audit(config_path, report) == 2
    assert "Erro de relatório" in capsys.readouterr().err


def test_audit_keyboard_interrupt_returns_130(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = make_library(tmp_path)

    def interrupted_scan(config: object) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "scan_files", interrupted_scan)
    assert run_audit(config_path, tmp_path / "audit.txt") == 130


def test_report_is_utf8(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    create_file(tmp_path, "Filmé.2020.mkv")
    report = tmp_path / "audit.txt"
    run_audit(config_path, report)
    assert "Filmé" in report.read_bytes().decode("utf-8")


def test_audit_uses_scanner_and_planner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = make_library(tmp_path)
    original_scan = cli.scan_files
    original_plan = cli.build_plan
    calls: list[str] = []

    def tracked_scan(config: Config) -> object:
        calls.append("scanner")
        return original_scan(config)

    def tracked_plan(files: object, config: Config) -> list[PlannedOperation]:
        calls.append("planner")
        return original_plan(files, config)  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "scan_files", tracked_scan)
    monkeypatch.setattr(cli, "build_plan", tracked_plan)
    assert run_audit(config_path, tmp_path / "audit.txt") == 0
    assert calls == ["scanner", "planner"]


def test_audit_never_calls_apply_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = make_library(tmp_path)
    monkeypatch.setattr(
        cli,
        "apply_plan",
        lambda *args, **kwargs: pytest.fail("audit não pode chamar apply_plan"),
    )
    assert run_audit(config_path, tmp_path / "audit.txt") == 0


def test_hundreds_of_small_files(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    total = 300
    for index in range(total):
        create_file(tmp_path, f"Movie.{1900 + index % 126}.part-{index:03d}.mkv")
    report = tmp_path / "audit.tsv"
    assert run_audit(config_path, report, "--format", "tsv") == 0
    assert len(report.read_text(encoding="utf-8").splitlines()) == total + 1


def test_audit_preserves_media_content_permissions_and_timestamps(tmp_path: Path) -> None:
    config_path = make_library(tmp_path)
    source = create_file(tmp_path, "Movie.2020.mkv", b"unchanged")
    source.chmod(0o640)
    timestamp_ns = 1_700_000_000_000_000_000
    os.utime(source, ns=(timestamp_ns, timestamp_ns))
    before = source.stat()
    assert run_audit(config_path, tmp_path / "audit.txt") == 0
    after = source.stat()
    assert source.read_bytes() == b"unchanged"
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode)
    assert after.st_mtime_ns == before.st_mtime_ns

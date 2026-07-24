from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from media_organizer.cli import main
from media_organizer.config import Config
from media_organizer.models import MediaType
from media_organizer.planner import build_plan
from media_organizer.scanner import scan_files


def make_config(tmp_path: Path, *, create_incoming: bool = True) -> Config:
    if create_incoming:
        (tmp_path / "incoming").mkdir()
    return Config(media_root=tmp_path)


def create_file(tmp_path: Path, relative: str) -> Path:
    path = tmp_path / "incoming" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def relative_results(config: Config) -> list[str]:
    return [str(item.path.relative_to(config.incoming_path)) for item in scan_files(config)]


def test_missing_incoming_returns_empty_iterator(tmp_path: Path) -> None:
    config = make_config(tmp_path, create_incoming=False)
    result = scan_files(config)
    assert isinstance(result, Iterator)
    assert list(result) == []


def test_empty_incoming(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    assert list(scan_files(config)) == []


def test_video_at_incoming_root(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    movie = create_file(tmp_path, "Movie.2020.mkv")
    result = list(scan_files(config))
    assert [item.path for item in result] == [movie]


def test_subtitle_at_incoming_root(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    subtitle = create_file(tmp_path, "Movie.2020.en.srt")
    assert [item.path for item in scan_files(config)] == [subtitle]


def test_recursive_scan(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    nested = create_file(tmp_path, "visible/nested/Show.S01E01.mkv")
    assert [item.path for item in scan_files(config)] == [nested]


def test_uppercase_video_extension(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    movie = create_file(tmp_path, "Movie.2020.MKV")
    result = list(scan_files(config))
    assert result[0].path == movie
    assert result[0].extension == ".mkv"


def test_uppercase_subtitle_extension(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    subtitle = create_file(tmp_path, "Movie.2020.en.SRT")
    result = list(scan_files(config))
    assert result[0].path == subtitle
    assert result[0].extension == ".srt"


@pytest.mark.parametrize("filename", ["README.txt", "poster.jpg", "sample.nfo", "archive.zip"])
def test_unsupported_extension_is_ignored(tmp_path: Path, filename: str) -> None:
    config = make_config(tmp_path)
    create_file(tmp_path, filename)
    assert list(scan_files(config)) == []


def test_hidden_file_is_ignored(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    create_file(tmp_path, ".hidden.mkv")
    assert list(scan_files(config)) == []


@pytest.mark.parametrize("directory", [".cache", ".Trash-1000", ".partial"])
def test_hidden_directory_and_content_are_ignored(tmp_path: Path, directory: str) -> None:
    config = make_config(tmp_path)
    create_file(tmp_path, f"{directory}/Movie.2020.mkv")
    assert list(scan_files(config)) == []


def test_hidden_nested_directory_is_ignored(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    create_file(tmp_path, "series/.metadata/Show.S01E01.mkv")
    assert list(scan_files(config)) == []


def test_file_symlink_is_ignored(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    target = create_file(tmp_path, "Movie.2020.mkv")
    (config.incoming_path / "Linked.2020.mkv").symlink_to(target)
    assert relative_results(config) == ["Movie.2020.mkv"]


def test_broken_symlink_is_ignored(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    (config.incoming_path / "Broken.2020.mkv").symlink_to(tmp_path / "missing.mkv")
    assert list(scan_files(config)) == []


def test_internal_directory_symlink_is_ignored(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    target = config.incoming_path / "real"
    target.mkdir()
    (target / "Movie.2020.mkv").touch()
    (config.incoming_path / "linked").symlink_to(target, target_is_directory=True)
    assert relative_results(config) == ["real/Movie.2020.mkv"]


def test_external_directory_symlink_is_ignored(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "Movie.2020.mkv").touch()
    (config.incoming_path / "linked").symlink_to(outside, target_is_directory=True)
    assert list(scan_files(config)) == []


def test_deterministic_order_between_directories(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    create_file(tmp_path, "z-dir/Movie.2020.mkv")
    create_file(tmp_path, "a-dir/Show.S01E01.mkv")
    assert relative_results(config) == [
        "a-dir/Show.S01E01.mkv",
        "z-dir/Movie.2020.mkv",
    ]


def test_deterministic_order_between_files(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    for filename in ("z.2020.mkv", "a.2020.mkv", "m.2020.mkv"):
        create_file(tmp_path, filename)
    assert relative_results(config) == ["a.2020.mkv", "m.2020.mkv", "z.2020.mkv"]


def test_order_is_lexicographic_by_relative_path(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    create_file(tmp_path, "z.2020.mkv")
    create_file(tmp_path, "a-dir/Movie.2020.mkv")
    assert relative_results(config) == ["a-dir/Movie.2020.mkv", "z.2020.mkv"]


def test_extension_is_normalized_to_lowercase(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    create_file(tmp_path, "Movie.2020.Mp4")
    assert next(scan_files(config)).extension == ".mp4"


def test_result_is_incremental_iterator_not_list(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    result = scan_files(config)
    assert isinstance(result, Iterator)
    assert not isinstance(result, list)
    assert iter(result) is result


def test_directory_oserror_does_not_stop_independent_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = make_config(tmp_path)
    (config.incoming_path / "bad").mkdir()
    good = create_file(tmp_path, "good.2020.mkv")
    original_scandir = os.scandir

    def selective_scandir(path: os.PathLike[str]) -> os.ScandirIterator[str]:
        if Path(path) == config.incoming_path / "bad":
            raise PermissionError("denied")
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", selective_scandir)
    with caplog.at_level(logging.WARNING, logger="media_organizer"):
        result = list(scan_files(config))
    assert [item.path for item in result] == [good]
    assert "Unable to read directory" in caplog.text


def test_disappearing_file_is_skipped_with_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = make_config(tmp_path)
    disappearing = create_file(tmp_path, "a.2020.mkv")
    surviving = create_file(tmp_path, "b.2020.mkv")
    original_stat = Path.stat
    removed = False

    def disappearing_stat(self: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        nonlocal removed
        if self == disappearing and not removed:
            removed = True
            self.unlink()
        return original_stat(self, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", disappearing_stat)
    with caplog.at_level(logging.WARNING, logger="media_organizer"):
        result = list(scan_files(config))
    assert [item.path for item in result] == [surviving]
    assert "Unable to inspect" in caplog.text


def test_supported_files_reach_planner(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    create_file(tmp_path, "Movie.2020.mkv")
    create_file(tmp_path, "Show.S01E01.mkv")
    plan = build_plan(scan_files(config), config)
    assert {operation.media_type for operation in plan} == {
        MediaType.MOVIE,
        MediaType.EPISODE,
    }


def test_unsupported_files_do_not_become_unknown(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    create_file(tmp_path, "README.txt")
    create_file(tmp_path, "unrecognized.mkv")
    plan = build_plan(scan_files(config), config)
    assert len(plan) == 1
    assert plan[0].media_type is MediaType.UNKNOWN
    assert plan[0].source.name == "unrecognized.mkv"


def test_cli_scan_does_not_change_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_config(tmp_path)
    movie = create_file(tmp_path, "Movie.2020.mkv")
    config_path = tmp_path / "config.toml"
    config_path.write_text(f'media_root = "{tmp_path}"\n', encoding="utf-8")
    before = movie.stat()
    assert main(["--config", str(config_path), "scan"]) == 0
    after = movie.stat()
    assert movie.exists()
    assert before.st_mtime_ns == after.st_mtime_ns
    assert "MOVIE" in capsys.readouterr().out


def test_large_library_is_processed(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    expected = 1_000
    for index in range(expected):
        create_file(tmp_path, f"group-{index % 10:02d}/Movie.{index:04d}.mkv")
    assert sum(1 for _ in scan_files(config)) == expected


def test_first_yield_does_not_traverse_later_subtree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = make_config(tmp_path)
    first = create_file(tmp_path, "a.2020.mkv")
    (config.incoming_path / "z-later").mkdir()
    original_scandir = os.scandir
    accessed_later = False

    def controlled_scandir(path: os.PathLike[str]) -> os.ScandirIterator[str]:
        nonlocal accessed_later
        if Path(path) == config.incoming_path / "z-later":
            accessed_later = True
            raise PermissionError("controlled failure")
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", controlled_scandir)
    result = scan_files(config)
    assert next(result).path == first
    assert not accessed_later
    with caplog.at_level(logging.WARNING, logger="media_organizer"):
        assert list(result) == []
    assert accessed_later


def test_ignored_items_do_not_log_warnings(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config = make_config(tmp_path)
    create_file(tmp_path, ".hidden.mkv")
    create_file(tmp_path, "poster.jpg")
    target = create_file(tmp_path, "Movie.2020.mkv")
    (config.incoming_path / "link.mkv").symlink_to(target)
    with caplog.at_level(logging.WARNING, logger="media_organizer"):
        list(scan_files(config))
    assert not caplog.records


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO não suportado")
def test_fifo_is_ignored(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    fifo = config.incoming_path / "stream.mkv"
    os.mkfifo(fifo)
    assert list(scan_files(config)) == []

from pathlib import Path

import pytest

from media_organizer.cli import main
from media_organizer.config import Config
from media_organizer.models import FoundFile, MediaType, OperationStatus
from media_organizer.organizer import apply_plan
from media_organizer.planner import UnsafePathError, build_plan, ensure_within
from media_organizer.scanner import scan_files


def make_config(root: Path) -> Config:
    return Config(media_root=root)


def touch(root: Path, name: str, content: bytes = b"media") -> Path:
    path = root / "incoming" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_movie_and_episode_targets(tmp_path: Path) -> None:
    movie = touch(tmp_path, "Interstellar.2014.2160p.HDR.REMUX.mkv")
    episode = touch(tmp_path, "Batman.The.Animated.Series.S01E01.1080p.mkv")
    plan = build_plan(scan_files(make_config(tmp_path)), make_config(tmp_path))
    targets = {operation.source: operation.target for operation in plan}
    assert (
        targets[movie]
        == tmp_path / "movies/Interstellar (2014)/Interstellar (2014) [2160p HDR REMUX].mkv"
    )
    assert (
        targets[episode]
        == tmp_path
        / "series/Batman The Animated Series/Season 01/Batman The Animated Series S01E01.mkv"
    )


def test_subtitle_associated_with_episode(tmp_path: Path) -> None:
    touch(tmp_path, "Show.S01E01.mkv")
    subtitle = touch(tmp_path, "Show.S01E01.Portuguese-Brazil.srt")
    plan = build_plan(scan_files(make_config(tmp_path)), make_config(tmp_path))
    operation = next(item for item in plan if item.source == subtitle)
    assert operation.media_type is MediaType.SUBTITLE
    assert operation.target == tmp_path / "series/Show/Season 01/Show S01E01.pt-BR.srt"


@pytest.mark.parametrize(
    ("filename", "target_name"),
    [
        ("Show.S01E01.pt-BR.forced.srt", "Show S01E01.pt-BR.forced.srt"),
        ("Show.S01E01.en.sdh.srt", "Show S01E01.en.sdh.srt"),
        ("Show.S01E01.en.sdh.cc.srt", "Show S01E01.en.sdh.cc.srt"),
        ("Show.S01E01.forced.srt", "Show S01E01.forced.srt"),
    ],
)
def test_episode_subtitle_qualifiers(tmp_path: Path, filename: str, target_name: str) -> None:
    touch(tmp_path, "Show.S01E01.mkv")
    subtitle = touch(tmp_path, filename)
    config = make_config(tmp_path)
    plan = build_plan(scan_files(config), config)
    operation = next(item for item in plan if item.source == subtitle)
    assert operation.target == tmp_path / "series/Show/Season 01" / target_name


def test_subtitles_with_different_flags_have_different_targets(tmp_path: Path) -> None:
    touch(tmp_path, "Show.S01E01.mkv")
    first = touch(tmp_path, "Show.S01E01.en.sdh.srt")
    second = touch(tmp_path, "Show.S01E01.en.cc.srt")
    config = make_config(tmp_path)
    plan = build_plan(scan_files(config), config)
    subtitles = [item for item in plan if item.source in {first, second}]
    assert {item.target.name for item in subtitles if item.target} == {
        "Show S01E01.en.sdh.srt",
        "Show S01E01.en.cc.srt",
    }
    assert all(item.status is OperationStatus.PLANNED for item in subtitles)


def test_subtitles_with_same_normalized_target_are_conflicts(tmp_path: Path) -> None:
    touch(tmp_path, "Show.S01E01.mkv")
    first = touch(tmp_path, "Show.S01E01.en.sdh.srt")
    second = touch(tmp_path, "Show.S01E01.English.sdh.srt")
    config = make_config(tmp_path)
    plan = build_plan(scan_files(config), config)
    subtitles = [item for item in plan if item.source in {first, second}]
    assert len({item.target for item in subtitles}) == 1
    assert all(item.status is OperationStatus.CONFLICT for item in subtitles)


def test_movie_subtitle_with_language_and_flag(tmp_path: Path) -> None:
    touch(tmp_path, "Movie.Name.2020.mkv")
    subtitle = touch(tmp_path, "Movie.Name.2020.en.forced.srt")
    config = make_config(tmp_path)
    plan = build_plan(scan_files(config), config)
    operation = next(item for item in plan if item.source == subtitle)
    assert operation.target == (
        tmp_path / "movies/Movie Name (2020)/Movie Name (2020).en.forced.srt"
    )


def test_unknown_file(tmp_path: Path) -> None:
    unknown = touch(tmp_path, "video-final-novo.mkv")
    operation = build_plan(scan_files(make_config(tmp_path)), make_config(tmp_path))[0]
    assert operation.source == unknown
    assert operation.media_type is MediaType.UNKNOWN
    assert operation.target is None


def test_existing_destination_is_conflict(tmp_path: Path) -> None:
    touch(tmp_path, "Arrival.2016.mkv")
    destination = tmp_path / "movies/Arrival (2016)/Arrival (2016).mkv"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"existing")
    operation = build_plan(scan_files(make_config(tmp_path)), make_config(tmp_path))[0]
    assert operation.status is OperationStatus.CONFLICT
    assert operation.conflict is not None


def test_path_traversal_rejected(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        ensure_within(tmp_path / "../outside/file.mkv", tmp_path)
    with pytest.raises(ValueError):
        Config(media_root=tmp_path, movies_dir="../outside")


def test_scan_does_not_modify_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = touch(tmp_path, "Arrival.2016.mkv", b"unchanged")
    config_path = tmp_path / "config.toml"
    config_path.write_text(f'media_root = "{tmp_path}"\n', encoding="utf-8")
    assert main(["--config", str(config_path), "scan"]) == 0
    assert source.read_bytes() == b"unchanged"
    assert not (tmp_path / "movies").exists()
    assert "MOVIE" in capsys.readouterr().out


def test_apply_moves_file(tmp_path: Path) -> None:
    source = touch(tmp_path, "Arrival.2016.1080p.mkv", b"movie")
    config = make_config(tmp_path)
    operations = build_plan(scan_files(config), config)
    result = apply_plan(operations, config)
    destination = tmp_path / "movies/Arrival (2016)/Arrival (2016) [1080p].mkv"
    assert result.moved == 1
    assert not source.exists()
    assert destination.read_bytes() == b"movie"


def test_scanner_ignores_symlinks(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    outside = tmp_path / "outside.mkv"
    outside.write_bytes(b"outside")
    (incoming / "linked.mkv").symlink_to(outside)
    assert scan_files(make_config(tmp_path)) == []


def test_manually_supplied_outside_source_is_conflict(tmp_path: Path) -> None:
    outside = tmp_path.parent / "Escape.2020.mkv"
    operation = build_plan([FoundFile(outside, ".mkv")], make_config(tmp_path))[0]
    assert operation.status is OperationStatus.CONFLICT

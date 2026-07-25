from pathlib import Path

import pytest

from media_organizer.config import (
    DEFAULT_VIDEO_EXTENSIONS,
    Config,
    ConfigurationError,
    load_config,
)


def test_default_config_is_valid(tmp_path: Path) -> None:
    config = Config(media_root=tmp_path)
    assert (config.incoming_dir, config.movies_dir, config.series_dir) == (
        "incoming",
        "movies",
        "series",
    )


def test_divx_is_a_default_video_extension() -> None:
    assert ".divx" in DEFAULT_VIDEO_EXTENSIONS


def test_media_root_becomes_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = Config(media_root=Path("media"))
    assert config.media_root == tmp_path / "media"
    assert config.media_root.is_absolute()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("./movies/", "movies"),
        ("./library/./movies/", "library/movies"),
    ],
)
def test_directory_normalization(tmp_path: Path, value: str, expected: str) -> None:
    config = Config(media_root=tmp_path, movies_dir=value)
    assert config.movies_dir == expected


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_directory_rejected(tmp_path: Path, value: str) -> None:
    with pytest.raises(ConfigurationError, match=r"movies_dir.*vazia"):
        Config(media_root=tmp_path, movies_dir=value)


def test_absolute_directory_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match=r"movies_dir.*absoluto"):
        Config(media_root=tmp_path, movies_dir="/movies")


@pytest.mark.parametrize("value", ["../incoming", "media/../movies"])
def test_parent_component_rejected(tmp_path: Path, value: str) -> None:
    with pytest.raises(ConfigurationError, match=r"movies_dir.*\.\."):
        Config(media_root=tmp_path, movies_dir=value)


@pytest.mark.parametrize("value", [".", "./", "././"])
def test_root_directory_rejected(tmp_path: Path, value: str) -> None:
    with pytest.raises(ConfigurationError, match=r"movies_dir.*raiz"):
        Config(media_root=tmp_path, movies_dir=value)


def test_equal_directories_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match=r"iguais.*incoming_dir.*movies_dir"):
        Config(media_root=tmp_path, incoming_dir="data", movies_dir="data")


def test_incoming_equal_to_series_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match=r"iguais.*incoming_dir.*series_dir"):
        Config(media_root=tmp_path, incoming_dir="data", series_dir="data")


def test_normalized_equivalent_directories_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match=r"iguais.*movies_dir.*series_dir"):
        Config(media_root=tmp_path, movies_dir="movies", series_dir="./movies/")


def test_incoming_parent_of_movies_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match=r"aninhados.*incoming_dir.*movies_dir"):
        Config(media_root=tmp_path, incoming_dir="media", movies_dir="media/movies")


def test_movies_child_of_series_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match=r"aninhados.*movies_dir.*series_dir"):
        Config(media_root=tmp_path, movies_dir="library/movies", series_dir="library")


def test_sibling_directories_are_valid(tmp_path: Path) -> None:
    config = Config(
        media_root=tmp_path,
        incoming_dir="library/incoming",
        movies_dir="library/movies",
        series_dir="library/series",
    )
    assert config.movies_dir == "library/movies"


def test_textual_prefix_is_not_parent(tmp_path: Path) -> None:
    config = Config(
        media_root=tmp_path,
        incoming_dir="media",
        movies_dir="media-old",
        series_dir="series",
    )
    assert config.incoming_dir == "media"
    assert config.movies_dir == "media-old"


@pytest.mark.parametrize(
    ("field_name", "value", "type_name"),
    [
        ("movies_dir", None, "NoneType"),
        ("series_dir", 123, "int"),
        ("incoming_dir", Path("incoming"), "PosixPath"),
    ],
)
def test_invalid_directory_type_rejected(
    tmp_path: Path, field_name: str, value: object, type_name: str
) -> None:
    with pytest.raises(ConfigurationError, match=rf"{field_name}.*tipo inválido.*{type_name}"):
        Config(media_root=tmp_path, **{field_name: value})  # type: ignore[arg-type]


def test_extension_without_dot_is_normalized(tmp_path: Path) -> None:
    config = Config(media_root=tmp_path, video_extensions=("mkv",))
    assert config.video_extensions == (".mkv",)


def test_extension_is_lowercase(tmp_path: Path) -> None:
    config = Config(media_root=tmp_path, subtitle_extensions=(".SRT",))
    assert config.subtitle_extensions == (".srt",)


@pytest.mark.parametrize("field_name", ["video_extensions", "subtitle_extensions"])
def test_empty_extension_list_rejected(tmp_path: Path, field_name: str) -> None:
    with pytest.raises(ConfigurationError, match=rf"{field_name}.*vazio"):
        Config(media_root=tmp_path, **{field_name: ()})  # type: ignore[arg-type]


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_config_valid(tmp_path: Path) -> None:
    path = write_config(tmp_path, f'media_root = "{tmp_path}"\nmovies_dir = "./library/movies/"\n')
    config = load_config(path)
    assert config.media_root == tmp_path
    assert config.movies_dir == "library/movies"


def test_load_config_requires_media_root(tmp_path: Path) -> None:
    path = write_config(tmp_path, 'movies_dir = "movies"\n')
    with pytest.raises(ConfigurationError, match=r"media_root.*obrigatório"):
        load_config(path)


def test_load_config_requires_string_media_root(tmp_path: Path) -> None:
    path = write_config(tmp_path, "media_root = 123\n")
    with pytest.raises(ConfigurationError, match=r"media_root.*string"):
        load_config(path)


def test_load_config_rejects_unknown_key(tmp_path: Path) -> None:
    path = write_config(tmp_path, f'media_root = "{tmp_path}"\nunknown = true\n')
    with pytest.raises(ConfigurationError, match=r"chaves desconhecidas.*unknown"):
        load_config(path)


def test_load_config_converts_type_error(tmp_path: Path) -> None:
    path = write_config(tmp_path, f'media_root = "{tmp_path}"\nvideo_extensions = 42\n')
    with pytest.raises(ConfigurationError, match="configuração inválida"):
        load_config(path)

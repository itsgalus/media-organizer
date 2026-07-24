from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi", ".mov", ".m4v")
DEFAULT_SUBTITLE_EXTENSIONS = (".srt", ".ass", ".ssa", ".vtt", ".sub")
DIRECTORY_FIELDS = ("incoming_dir", "movies_dir", "series_dir")


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Config:
    media_root: Path
    incoming_dir: str = "incoming"
    movies_dir: str = "movies"
    series_dir: str = "series"
    video_extensions: tuple[str, ...] = DEFAULT_VIDEO_EXTENSIONS
    subtitle_extensions: tuple[str, ...] = DEFAULT_SUBTITLE_EXTENSIONS
    preserve_technical_tags_for_movies: bool = True
    preserve_technical_tags_for_series: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "media_root", self.media_root.expanduser().absolute())
        directories = {
            field_name: _normalize_relative_directory(field_name, getattr(self, field_name))
            for field_name in DIRECTORY_FIELDS
        }
        _validate_directory_layout(directories)
        for field_name, value in directories.items():
            object.__setattr__(self, field_name, value)

        for name in ("video_extensions", "subtitle_extensions"):
            values = getattr(self, name)
            if not values:
                raise ConfigurationError(f"{name} não pode estar vazio")
            normalized = tuple(_normalize_extension(value) for value in values)
            object.__setattr__(self, name, normalized)

    @property
    def incoming_path(self) -> Path:
        return self.media_root / self.incoming_dir

    @property
    def movies_path(self) -> Path:
        return self.media_root / self.movies_dir

    @property
    def series_path(self) -> Path:
        return self.media_root / self.series_dir


def _normalize_relative_directory(field_name: str, value: object) -> str:
    if not isinstance(value, str):
        raise ConfigurationError(
            f"{field_name} possui tipo inválido: esperado string, recebido {type(value).__name__}"
        )
    if not value.strip():
        raise ConfigurationError(f"{field_name} não pode ser uma string vazia")

    path = Path(value)
    if path.is_absolute():
        raise ConfigurationError(f"{field_name} não pode ser um caminho absoluto")
    if ".." in path.parts:
        raise ConfigurationError(f"{field_name} não pode conter o componente '..'")

    normalized = Path(*path.parts).as_posix()
    if normalized == ".":
        raise ConfigurationError(f"{field_name} não pode ser igual ao diretório raiz")
    return normalized


def _validate_directory_layout(directories: dict[str, str]) -> None:
    items = list(directories.items())
    for index, (first_name, first_value) in enumerate(items):
        first_parts = Path(first_value).parts
        for second_name, second_value in items[index + 1 :]:
            second_parts = Path(second_value).parts
            if first_parts == second_parts:
                raise ConfigurationError(
                    f"diretórios iguais: {first_name} e {second_name} apontam para {first_value}"
                )
            if _is_parent(first_parts, second_parts) or _is_parent(second_parts, first_parts):
                raise ConfigurationError(
                    f"diretórios aninhados: {first_name}={first_value} e "
                    f"{second_name}={second_value}"
                )


def _is_parent(parent: tuple[str, ...], child: tuple[str, ...]) -> bool:
    return len(parent) < len(child) and child[: len(parent)] == parent


def _normalize_extension(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError("extensões devem ser strings não vazias")
    extension = value.strip().lower()
    return extension if extension.startswith(".") else f".{extension}"


def load_config(path: Path) -> Config:
    try:
        with path.open("rb") as config_file:
            raw = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError(f"não foi possível ler {path}: {exc}") from exc

    allowed = {field for field in Config.__dataclass_fields__ if field != "media_root"}
    unknown = set(raw) - allowed - {"media_root"}
    if unknown:
        raise ConfigurationError(f"chaves desconhecidas: {', '.join(sorted(unknown))}")
    media_root = raw.pop("media_root", None)
    if not isinstance(media_root, str) or not media_root:
        raise ConfigurationError("media_root é obrigatório e deve ser uma string")
    try:
        return Config(media_root=Path(media_root), **raw)
    except TypeError as exc:
        raise ConfigurationError(f"configuração inválida: {exc}") from exc

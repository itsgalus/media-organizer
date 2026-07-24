from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi", ".mov", ".m4v")
DEFAULT_SUBTITLE_EXTENSIONS = (".srt", ".ass", ".ssa", ".vtt", ".sub")


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
        for name in ("incoming_dir", "movies_dir", "series_dir"):
            value = getattr(self, name)
            path = Path(value)
            if not value or path.is_absolute() or ".." in path.parts:
                raise ConfigurationError(f"{name} deve ser um caminho relativo seguro")
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

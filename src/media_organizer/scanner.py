from __future__ import annotations

import logging
import os
import stat
from collections.abc import Iterator
from pathlib import Path

from media_organizer.config import Config
from media_organizer.models import FoundFile

LOGGER = logging.getLogger("media_organizer")


def scan_files(config: Config) -> Iterator[FoundFile]:
    """Yield supported regular files without following symbolic links."""
    incoming = config.incoming_path
    try:
        metadata = incoming.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        LOGGER.warning("Unable to access incoming directory %s: %s", incoming, exc)
        return

    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        return

    supported_extensions = frozenset((*config.video_extensions, *config.subtitle_extensions))
    root = incoming.resolve(strict=False)
    yield from _scan_directory(incoming, root, supported_extensions)


def _scan_directory(
    directory: Path, root: Path, supported_extensions: frozenset[str]
) -> Iterator[FoundFile]:
    try:
        with os.scandir(directory) as entries:
            ordered_entries = sorted(entries, key=lambda entry: entry.name)
    except OSError as exc:
        LOGGER.warning("Unable to read directory %s: %s", directory, exc)
        return

    for entry in ordered_entries:
        if entry.name.startswith("."):
            continue
        path = Path(entry.path)
        try:
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                yield from _scan_directory(path, root, supported_extensions)
                continue

            extension = path.suffix.lower()
            if extension not in supported_extensions:
                continue
            metadata = path.stat(follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode):
                continue
            resolved = path.resolve(strict=False)
            resolved.relative_to(root)
        except ValueError:
            LOGGER.warning("Skipping path outside incoming directory: %s", path)
            continue
        except OSError as exc:
            LOGGER.warning("Unable to inspect %s: %s", path, exc)
            continue
        yield FoundFile(path=path, extension=extension)

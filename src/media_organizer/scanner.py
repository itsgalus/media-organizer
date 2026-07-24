from __future__ import annotations

import os
from pathlib import Path

from media_organizer.config import Config
from media_organizer.models import FoundFile


def scan_files(config: Config) -> list[FoundFile]:
    """List regular files without following directory symlinks."""
    found: list[FoundFile] = []
    if not config.incoming_path.is_dir():
        return found

    for directory, dirnames, filenames in os.walk(config.incoming_path, followlinks=False):
        base = Path(directory)
        dirnames[:] = sorted(name for name in dirnames if not (base / name).is_symlink())
        for name in sorted(filenames):
            path = base / name
            if path.is_symlink() or not path.is_file():
                continue
            found.append(FoundFile(path=path, extension=path.suffix.lower()))
    return found

"""Filesystem helpers."""

import os
from pathlib import Path


def write_private_text(path: Path, text: str) -> None:
    """Write text readable by the owner only.

    Permissions are set at creation via os.open, and tightened with fchmod
    BEFORE any content is written — a pre-existing world-readable file must
    not spend the duration of the write exposing its fresh contents.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
    except OSError:
        pass  # some filesystems refuse; creation mode still applied
    with os.fdopen(fd, "w") as f:
        f.write(text)

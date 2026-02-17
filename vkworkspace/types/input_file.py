from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import BinaryIO


class InputFile:
    def __init__(
        self,
        file: str | Path | BinaryIO | bytes,
        filename: str | None = None,
    ) -> None:
        self.file = file
        self.filename = filename

    def read(self) -> tuple[str | None, BinaryIO | bytes]:
        if isinstance(self.file, (str, Path)):
            path = Path(self.file)
            return self.filename or path.name, open(path, "rb")
        if isinstance(self.file, bytes):
            return self.filename, BytesIO(self.file)
        return self.filename, self.file

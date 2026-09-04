from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol


class TransferError(RuntimeError):
    pass


ProgressCb = Callable[[int, int], None]  # (bytes_done, bytes_total)


@dataclass
class SendItem:
    local: Path
    name: str            # target file name
    ok: bool = False
    detail: str = ""


def md5_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


class TransferBackend(Protocol):
    def connect(self) -> None: ...
    def ensure_dir(self) -> None: ...
    def put(self, local: Path, name: str, progress: ProgressCb | None = None) -> None: ...
    def verify(self, local: Path, name: str, mode: str) -> tuple[bool, str]: ...
    def run_hook(self) -> str: ...
    def close(self) -> None: ...

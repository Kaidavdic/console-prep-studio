from __future__ import annotations

import shutil
from pathlib import Path

from ..profiles import Transfer
from .base import ProgressCb, TransferError, md5_file


class LocalDirBackend:
    """Copy to a mounted path — an SD card reader, a USB stick, a network drive."""

    def __init__(self, tr: Transfer):
        self.tr = tr
        self.root = Path(tr.local_path or tr.remote_dir)

    def connect(self) -> None:
        if not self.root.parent.exists() and not self.root.exists():
            raise TransferError(f"target path not available: {self.root}")

    def ensure_dir(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, local: Path, name: str, progress: ProgressCb | None = None) -> None:
        dst = self.root / name
        total = local.stat().st_size
        done = 0
        with open(local, "rb") as fsrc, open(dst, "wb") as fdst:
            for chunk in iter(lambda: fsrc.read(1 << 20), b""):
                fdst.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)

    def verify(self, local: Path, name: str, mode: str) -> tuple[bool, str]:
        dst = self.root / name
        if mode == "none":
            return True, "skipped"
        if not dst.exists():
            return False, "missing at destination"
        if mode == "size":
            return (dst.stat().st_size == local.stat().st_size,
                    f"{dst.stat().st_size} vs {local.stat().st_size} bytes")
        a, b = md5_file(dst), md5_file(local)
        return (a == b), f"{a} vs {b}"

    def run_hook(self) -> str:
        return ""

    def close(self) -> None:
        pass

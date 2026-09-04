from __future__ import annotations

from ..profiles import Transfer
from .base import TransferBackend, TransferError


def make_backend(tr: Transfer) -> TransferBackend:
    if tr.kind == "ssh":
        from .ssh_scp import SshBackend
        return SshBackend(tr)
    if tr.kind == "smb":
        from .smb import SmbBackend
        return SmbBackend(tr)
    if tr.kind == "localdir":
        from .localdir import LocalDirBackend
        return LocalDirBackend(tr)
    raise TransferError(f"unknown transfer kind: {tr.kind!r}")


__all__ = ["TransferBackend", "TransferError", "make_backend"]

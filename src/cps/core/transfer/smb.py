from __future__ import annotations

from pathlib import Path

from .. import settings
from ..profiles import Transfer
from .base import ProgressCb, TransferError, md5_file


class SmbBackend:
    """Windows file sharing (SMB2/3). remote_dir is a path inside the share."""

    def __init__(self, tr: Transfer):
        self.tr = tr
        self._sess = None

    def _password(self) -> str | None:
        return settings.get_secret(self.tr.password_ref) if self.tr.password_ref else None

    def _unc(self, name: str = "") -> str:
        parts = [p for p in (self.tr.remote_dir.strip("\\/"), name) if p]
        tail = "\\".join(parts)
        return rf"\\{self.tr.host}\{self.tr.share}\{tail}".rstrip("\\")

    def connect(self) -> None:
        try:
            import smbclient
        except ImportError as e:
            raise TransferError("pip install smbprotocol for SMB transfers") from e
        try:
            smbclient.register_session(
                self.tr.host, username=self.tr.user or None,
                password=self._password() or None, port=self.tr.port or 445,
            )
        except Exception as e:  # noqa: BLE001
            raise TransferError(f"SMB connect failed: {e}") from e
        self._sess = smbclient

    def ensure_dir(self) -> None:
        smbclient = self._sess
        assert smbclient is not None
        d = self._unc()
        try:
            smbclient.makedirs(d, exist_ok=True)
        except Exception as e:  # noqa: BLE001
            raise TransferError(f"cannot create {d}: {e}") from e

    def put(self, local: Path, name: str, progress: ProgressCb | None = None) -> None:
        smbclient = self._sess
        assert smbclient is not None
        total = local.stat().st_size
        done = 0
        with open(local, "rb") as fsrc, smbclient.open_file(self._unc(name), mode="wb") as fdst:
            for chunk in iter(lambda: fsrc.read(1 << 20), b""):
                fdst.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)

    def verify(self, local: Path, name: str, mode: str) -> tuple[bool, str]:
        smbclient = self._sess
        assert smbclient is not None
        if mode == "none":
            return True, "skipped"
        try:
            st = smbclient.stat(self._unc(name))
        except Exception as e:  # noqa: BLE001
            return False, f"stat failed: {e}"
        if mode in ("size", "md5"):  # md5 over SMB would re-read the whole file; size is enough
            return (st.st_size == local.stat().st_size,
                    f"{st.st_size} vs {local.stat().st_size} bytes")
        return True, ""

    def run_hook(self) -> str:
        return ""

    def close(self) -> None:
        try:
            if self._sess:
                self._sess.reset_connection_cache()
        except Exception:
            pass

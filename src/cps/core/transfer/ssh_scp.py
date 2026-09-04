from __future__ import annotations

import posixpath
from pathlib import Path

from .. import settings
from ..profiles import Transfer
from .base import ProgressCb, TransferError, md5_file


class SshBackend:
    def __init__(self, tr: Transfer):
        self.tr = tr
        self._client = None

    # --------------------------------------------------------------
    def _password(self) -> str | None:
        if self.tr.password_ref:
            return settings.get_secret(self.tr.password_ref)
        return None

    def connect(self) -> None:
        import paramiko

        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: dict = dict(
            hostname=self.tr.host, port=self.tr.port, username=self.tr.user,
            timeout=15, allow_agent=False, look_for_keys=False,
        )
        if self.tr.key_path:
            kwargs["key_filename"] = self.tr.key_path
        else:
            pw = self._password()
            if not pw:
                raise TransferError("no SSH password saved for this profile")
            kwargs["password"] = pw
        try:
            c.connect(**kwargs)
        except Exception as e:  # noqa: BLE001 - surface a clean message
            raise TransferError(f"SSH connect failed: {e}") from e
        self._client = c

    def ensure_dir(self) -> None:
        self._run(f"mkdir -p {_shq(self.tr.remote_dir)}")

    def put(self, local: Path, name: str, progress: ProgressCb | None = None) -> None:
        from scp import SCPClient

        assert self._client is not None
        remote = posixpath.join(self.tr.remote_dir, name)
        cb = (lambda _fn, size, sent: progress(sent, size)) if progress else None
        with SCPClient(self._client.get_transport(), socket_timeout=60, progress=cb) as scp:
            scp.put(str(local), remote_path=remote)

    def verify(self, local: Path, name: str, mode: str) -> tuple[bool, str]:
        remote = posixpath.join(self.tr.remote_dir, name)
        if mode == "none":
            return True, "skipped"
        if mode == "size":
            out = self._run(f"stat -c %s {_shq(remote)} 2>/dev/null || wc -c < {_shq(remote)}")
            try:
                rsize = int(out.strip().split()[0])
            except (ValueError, IndexError):
                return False, f"could not stat remote file ({out!r})"
            lsize = local.stat().st_size
            return (rsize == lsize), f"{rsize} vs {lsize} bytes"
        # md5
        out = self._run(f"md5sum {_shq(remote)} 2>/dev/null || md5 -q {_shq(remote)}")
        rmd5 = out.strip().split()[0] if out.strip() else ""
        lmd5 = md5_file(local)
        return (rmd5 == lmd5), f"{rmd5 or '?'} vs {lmd5}"

    def run_hook(self) -> str:
        if not self.tr.post_hook:
            return ""
        return self._run(self.tr.post_hook)

    def close(self) -> None:
        try:
            if self._client:
                self._client.close()
        except Exception:
            pass

    # --------------------------------------------------------------
    def _run(self, cmd: str) -> str:
        assert self._client is not None
        _in, out, err = self._client.exec_command(cmd, timeout=30)
        data = out.read().decode("utf-8", "replace")
        errtxt = err.read().decode("utf-8", "replace")
        return data if data else errtxt


def _shq(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"

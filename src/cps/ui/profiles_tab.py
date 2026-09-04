from __future__ import annotations

import copy
import uuid

from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from ..core import settings
from ..core.profiles import (
    TRANSFER_KINDS, VERIFY_MODES, Profile, knulli_preset,
)


class ProfilesTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._loading = False

        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_select)

        new_btn = QPushButton("New")
        clone_btn = QPushButton("Clone")
        del_btn = QPushButton("Delete")
        new_btn.clicked.connect(self._new)
        clone_btn.clicked.connect(self._clone)
        del_btn.clicked.connect(self._delete)
        left_btns = QHBoxLayout()
        for b in (new_btn, clone_btn, del_btn):
            left_btns.addWidget(b)

        left = QVBoxLayout()
        left.addWidget(QLabel("Profiles"))
        left.addWidget(self.list, 1)
        left.addLayout(left_btns)

        # --- editor ---
        self.name = QLineEdit()
        self.regex = QLineEdit()
        self.regex.setPlaceholderText(r"optional, e.g.  - (\d+) -   (group 1 = episode number)")
        self.verify = QComboBox(); self.verify.addItems(VERIFY_MODES)

        meta = QGroupBox("Profile")
        mf = QFormLayout(meta)
        mf.addRow("Name", self.name)
        mf.addRow("Episode regex", self.regex)
        mf.addRow("Verify after send", self.verify)

        self.kind = QComboBox(); self.kind.addItems(TRANSFER_KINDS)
        self.host = QLineEdit()
        self.port = QSpinBox(); self.port.setRange(1, 65535)
        self.user = QLineEdit()
        self.password = QLineEdit(); self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("stored in Windows Credential Manager")
        self.key_path = QLineEdit()
        key_btn = QPushButton("Browse")
        key_btn.clicked.connect(self._browse_key)
        self.remote_dir = QLineEdit()
        self.share = QLineEdit()
        self.local_path = QLineEdit()
        local_btn = QPushButton("Browse")
        local_btn.clicked.connect(self._browse_local)
        self.hook = QPlainTextEdit()
        self.hook.setPlaceholderText("shell command run on the device after copy (ssh only)")
        self.hook.setFixedHeight(60)

        tr = QGroupBox("Transfer")
        tf = QFormLayout(tr)
        tf.addRow("Kind", self.kind)
        tf.addRow("Host", self.host)
        tf.addRow("Port", self.port)
        tf.addRow("User", self.user)
        tf.addRow("Password", self.password)
        keyrow = QHBoxLayout(); keyrow.addWidget(self.key_path); keyrow.addWidget(key_btn)
        tf.addRow("SSH key file", self._wrap(keyrow))
        tf.addRow("Remote dir", self.remote_dir)
        tf.addRow("SMB share", self.share)
        localrow = QHBoxLayout(); localrow.addWidget(self.local_path); localrow.addWidget(local_btn)
        tf.addRow("Local/mounted path", self._wrap(localrow))
        tf.addRow("Post-copy hook", self.hook)

        save_btn = QPushButton("Save profile")
        save_btn.clicked.connect(self._save)
        test_btn = QPushButton("Test connection")
        test_btn.clicked.connect(self._test_conn)
        er_btns = QHBoxLayout()
        er_btns.addWidget(save_btn); er_btns.addWidget(test_btn); er_btns.addStretch(1)

        self.builtin_note = QLabel()
        self.builtin_note.setStyleSheet("color: gray;")

        right = QVBoxLayout()
        right.addWidget(meta)
        right.addWidget(tr)
        right.addLayout(er_btns)
        right.addWidget(self.builtin_note)
        right.addStretch(1)

        root = QHBoxLayout(self)
        lw = QWidget(); lw.setLayout(left); lw.setFixedWidth(240)
        rw = QWidget(); rw.setLayout(right)
        root.addWidget(lw)
        root.addWidget(rw, 1)

        self.kind.currentTextChanged.connect(self._sync_kind_fields)
        self.main.profilesChanged.connect(self._reload_list)
        self._reload_list()

    # ---------------------------------------------------------------
    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget(); w.setLayout(layout); return w

    def _reload_list(self) -> None:
        self._loading = True
        cur = self.list.currentRow()
        self.list.clear()
        for p in self.main.profiles:
            label = p.name + ("  (built-in)" if p.builtin else "")
            QListWidgetItem(label, self.list)
        self._loading = False
        if 0 <= cur < self.list.count():
            self.list.setCurrentRow(cur)
        elif self.list.count():
            self.list.setCurrentRow(0)

    def _current(self) -> Profile | None:
        i = self.list.currentRow()
        if 0 <= i < len(self.main.profiles):
            return self.main.profiles[i]
        return None

    def _on_select(self, _row: int) -> None:
        p = self._current()
        if not p:
            return
        self.main.set_current_profile(p.id)
        self._loading = True
        self.name.setText(p.name)
        self.regex.setText(p.episode_regex)
        self.verify.setCurrentText(p.verify)
        t = p.transfer
        self.kind.setCurrentText(t.kind)
        self.host.setText(t.host)
        self.port.setValue(t.port or 22)
        self.user.setText(t.user)
        self.password.setText(settings.get_secret(t.password_ref) or "" if t.password_ref else "")
        self.key_path.setText(t.key_path)
        self.remote_dir.setText(t.remote_dir)
        self.share.setText(t.share)
        self.local_path.setText(t.local_path)
        self.hook.setPlainText(t.post_hook)
        self.builtin_note.setText(
            "Built-in preset — edits are allowed but 'Clone' keeps a safe copy." if p.builtin else "")
        self._loading = False
        self._sync_kind_fields(t.kind)

    def _sync_kind_fields(self, kind: str) -> None:
        is_ssh = kind == "ssh"
        is_smb = kind == "smb"
        is_local = kind == "localdir"
        self.host.setEnabled(is_ssh or is_smb)
        self.port.setEnabled(is_ssh or is_smb)
        self.user.setEnabled(is_ssh or is_smb)
        self.password.setEnabled(is_ssh or is_smb)
        self.key_path.setEnabled(is_ssh)
        self.remote_dir.setEnabled(not is_local)
        self.share.setEnabled(is_smb)
        self.local_path.setEnabled(is_local)
        self.hook.setEnabled(is_ssh)

    def _collect_into(self, p: Profile) -> None:
        p.name = self.name.text().strip() or "Unnamed"
        p.episode_regex = self.regex.text().strip()
        p.verify = self.verify.currentText()
        t = p.transfer
        t.kind = self.kind.currentText()
        t.host = self.host.text().strip()
        t.port = self.port.value()
        t.user = self.user.text().strip()
        t.key_path = self.key_path.text().strip()
        t.remote_dir = self.remote_dir.text().strip()
        t.share = self.share.text().strip()
        t.local_path = self.local_path.text().strip()
        t.post_hook = self.hook.toPlainText().strip()
        pw = self.password.text()
        if pw:
            ref = t.password_ref or f"profile-{p.id}"
            settings.set_secret(ref, pw)
            t.password_ref = ref

    def _save(self) -> None:
        p = self._current()
        if not p:
            return
        self._collect_into(p)
        self.main.persist_profiles()
        self._reload_list()
        QMessageBox.information(self, "Saved", f"Profile '{p.name}' saved.")

    def _new(self) -> None:
        p = Profile(id=uuid.uuid4().hex[:8], name="New profile")
        self.main.profiles.append(p)
        self.main.persist_profiles()
        self._reload_list()
        self.list.setCurrentRow(self.list.count() - 1)

    def _clone(self) -> None:
        p = self._current()
        if not p:
            return
        c = Profile.from_dict(copy.deepcopy(p.to_dict()))
        c.id = uuid.uuid4().hex[:8]
        c.name = f"{p.name} (copy)"
        c.builtin = False
        self.main.profiles.append(c)
        self.main.persist_profiles()
        self._reload_list()
        self.list.setCurrentRow(self.list.count() - 1)

    def _delete(self) -> None:
        p = self._current()
        if not p:
            return
        if QMessageBox.question(self, "Delete", f"Delete profile '{p.name}'?") != QMessageBox.Yes:
            return
        self.main.profiles = [x for x in self.main.profiles if x.id != p.id]
        self.main.persist_profiles()
        self.main.refresh_profiles()          # re-seeds KNULLI if it was removed
        self._reload_list()

    def _browse_key(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "SSH private key")
        if f:
            self.key_path.setText(f)

    def _browse_local(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Target folder (SD card / mount)")
        if d:
            self.local_path.setText(d)

    def _test_conn(self) -> None:
        p = self._current()
        if not p:
            return
        self._collect_into(p)
        from ..core.transfer import make_backend
        try:
            b = make_backend(p.transfer)
            b.connect()
            b.ensure_dir()
            b.close()
            QMessageBox.information(self, "Connection OK", f"Reached {p.transfer.host or p.transfer.local_path}.")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Connection failed", str(e))

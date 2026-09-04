from __future__ import annotations


def human_bytes(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def human_rate(bps: float) -> str:
    if bps <= 0:
        return "—"
    return f"{human_bytes(bps)}/s"


def human_eta(seconds: float) -> str:
    """Compact time-remaining: '3d 4h', '1h 12m', '4m 30s', '12s', '—' when unknown."""
    if not seconds or seconds <= 0 or seconds != seconds or seconds == float("inf"):
        return "—"
    seconds = int(seconds)
    if seconds >= 86400:
        return f"{seconds // 86400}d {seconds % 86400 // 3600}h"
    if seconds >= 3600:
        return f"{seconds // 3600}h {seconds % 3600 // 60}m"
    if seconds >= 60:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds}s"


def human_duration(seconds: float) -> str:
    """Elapsed time, always shows a value (0s rather than —)."""
    return human_eta(seconds) if seconds and seconds > 0 else "0s"


# The engines record what failed in their own terms, which is right for the log
# and useless on screen: "Command '[...ffprobe.EXE, -v, error, ...]' returned
# non-zero exit status 1" tells a reader nothing they can act on.
_PLAIN_ERRORS = (
    ("could not read the file", "This file is damaged, or it is not a video."),
    ("ffprobe failed", "This file is damaged, or it is not a video."),
    ("ffmpeg crashed", "The converter stopped unexpectedly on this file."),
    ("encode crashed", "The converter stopped unexpectedly on this file."),
    ("ffmpeg failed", "The converter could not finish this file."),
    ("nothing was produced", "No converted file came out of this one."),
    ("no output produced", "No converted file came out of this one."),
    ("no video files found", "This torrent has no video files in it."),
    ("cannot start torrent engine", "The torrent connection could not be started. "
                                    "Another program may be using the same port."),
    ("failed", "The converter could not finish this file."),
)


def count_of(n: int, singular: str, plural: str | None = None) -> str:
    """“1 file”, “3 files” — worth the four lines to never ship “1 files”."""
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def plain_error(raw: str) -> str:
    """One sentence a person can act on, for anything shown outside the Log."""
    text = (raw or "").strip()
    if not text:
        return "Something went wrong."
    low = text.lower()
    for needle, plain in _PLAIN_ERRORS:
        if needle in low:
            return plain
    first = text.splitlines()[0]
    looks_technical = ":\\" in first or "/" in first or "Traceback" in first
    if looks_technical or len(first) > 120:
        return "Something went wrong. The Log has the details."
    return first


def confirm_deleting_sources(parent, count: int, singular: str, plural: str) -> bool:
    """Ask before anything irreversible, with buttons that name the outcome.

    'Yes'/'No' makes the reader re-read the question to work out which is which,
    and Qt would make the destructive one the default. Both actions are spelled
    out instead, and keeping the files is what Enter and Esc do.
    """
    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Delete the originals?")
    box.setText(f"The {singular} will be deleted once it has been converted."
                if count == 1 else
                f"All {count} {plural} will be deleted as they are converted.")
    box.setInformativeText("The converted copies are kept. This cannot be undone.")
    keep = box.addButton("Keep the originals", QMessageBox.RejectRole)
    delete = box.addButton("Delete after converting", QMessageBox.DestructiveRole)
    box.setDefaultButton(keep)
    box.setEscapeButton(keep)
    box.exec()
    # only an explicit press deletes: closing with Esc or the X leaves
    # clickedButton() as None, and that must mean "keep", never "delete"
    return box.clickedButton() is delete

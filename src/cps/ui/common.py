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

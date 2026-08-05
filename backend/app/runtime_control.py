"""Process-local runtime controls for maintenance operations."""

_maintenance_mode = False


def set_maintenance_mode(enabled: bool) -> None:
    global _maintenance_mode
    _maintenance_mode = enabled


def is_maintenance_mode() -> bool:
    return _maintenance_mode

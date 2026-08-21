from ..extensions import db


def _clear_scoped_session_registry() -> None:
    registry = getattr(db.session, "registry", None)
    clear = getattr(registry, "clear", None)
    if clear is None:
        return
    try:
        clear()
    except Exception:
        pass


def discard_db_session() -> None:
    """Drop the current scoped session, even if closing it hits a dead connection."""
    try:
        db.session.remove()
    except Exception:
        _clear_scoped_session_registry()


def safe_session_rollback(*, remove: bool = False) -> None:
    try:
        db.session.rollback()
    except Exception:
        pass
    if remove:
        discard_db_session()

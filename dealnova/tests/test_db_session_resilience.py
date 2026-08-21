from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def _function_body(source: str, function_name: str) -> str:
    marker = f"def {function_name}("
    start = source.index(marker)
    next_marker = source.find("\ndef ", start + len(marker))
    next_route = source.find("\n@bp.route", start + len(marker))
    candidates = [pos for pos in (next_marker, next_route) if pos != -1]
    end = min(candidates) if candidates else len(source)
    return source[start:end]


def test_discard_db_session_clears_registry_when_remove_raises(monkeypatch):
    from app.services import db_session

    calls = []

    class Registry:
        def clear(self):
            calls.append("clear")

    class Session:
        registry = Registry()

        def remove(self):
            calls.append("remove")
            raise RuntimeError("broken close")

    monkeypatch.setattr(db_session.db, "session", Session())

    db_session.discard_db_session()

    assert calls == ["remove", "clear"]


def test_safe_session_rollback_removes_broken_session(monkeypatch):
    from app.services import db_session

    calls = []

    class Registry:
        def clear(self):
            calls.append("clear")

    class Session:
        registry = Registry()

        def rollback(self):
            calls.append("rollback")
            raise RuntimeError("lost connection")

        def remove(self):
            calls.append("remove")
            raise RuntimeError("broken close")

    monkeypatch.setattr(db_session.db, "session", Session())

    db_session.safe_session_rollback(remove=True)

    assert calls == ["rollback", "remove", "clear"]


def test_load_user_treats_closed_cursor_errors_as_recoverable():
    source = _read("app/__init__.py")
    body = _function_body(source, "load_user")

    assert "NoSuchColumnError" in source
    assert "ResourceClosedError" in source
    assert "RECOVERABLE_DB_SESSION_ERRORS" in body
    assert "discard_db_session()" in body


def test_vendor_dashboard_db_error_uses_safe_session_rollback():
    source = _read("app/routes/vendor.py")
    start = source.index("def dashboard_orders_live(")
    end = source.find("\n\n@bp.route", start + 1)
    body = source[start : end if end != -1 else len(source)]
    db_error_start = body.index("except SQLAlchemyError")
    next_exception_start = body.index("except Exception", db_error_start)
    db_error_block = body[db_error_start:next_exception_start]

    assert "safe_session_rollback(remove=True)" in db_error_block
    assert "db.session.rollback()" not in db_error_block

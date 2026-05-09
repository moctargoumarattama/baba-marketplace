from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def test_recent_logs_uses_column_projection_not_full_orm_hydration():
    source = _read("app/services/logging_service.py")
    method = source.split("def get_recent_logs(", 1)[1].split("    @staticmethod", 1)[0]

    assert "SimpleNamespace" in source
    assert "db.session.query(" in method
    assert "ActivityLog.id," in method
    assert "ActivityLog.timestamp," in method
    assert "ActivityLog.query" not in method
    assert ".filter_by(" not in method
    assert "return []" in method

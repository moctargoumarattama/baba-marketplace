from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models.runtime_state import RuntimeState


JsonFactory = Callable[[], Any]


def _safe_session_rollback() -> None:
    try:
        db.session.rollback()
    except Exception:
        pass


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _default_value(factory_or_value: JsonFactory | Any) -> Any:
    if callable(factory_or_value):
        return factory_or_value()
    if isinstance(factory_or_value, dict):
        return dict(factory_or_value)
    if isinstance(factory_or_value, list):
        return list(factory_or_value)
    if isinstance(factory_or_value, set):
        return set(factory_or_value)
    return factory_or_value


def _decode_json(raw_value: str | None, default_factory: JsonFactory | Any) -> Any:
    default_value = _default_value(default_factory)
    if not raw_value:
        return default_value
    try:
        return json.loads(raw_value)
    except Exception:
        return default_value


def _encode_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _lock_rows(keys: list[str]) -> dict[str, RuntimeState]:
    normalized_keys = sorted({str(key).strip() for key in keys if str(key).strip()})
    if not normalized_keys:
        return {}

    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            rows = {
                row.state_key: row
                for row in (
                    RuntimeState.query
                    .filter(RuntimeState.state_key.in_(normalized_keys))
                    .with_for_update()
                    .all()
                )
            }
            now = datetime.utcnow()
            for key in normalized_keys:
                if key in rows:
                    continue
                row = RuntimeState(
                    state_key=key,
                    created_at=now,
                    updated_at=now,
                )
                db.session.add(row)
                rows[key] = row
            db.session.flush()
            return rows
        except IntegrityError as exc:
            last_error = exc
            _safe_session_rollback()
    if last_error is not None:
        raise last_error
    return {}


def get_int_state(key: str, default: int = 0) -> int:
    row = RuntimeState.query.filter_by(state_key=str(key)).first()
    if row is None:
        return int(default)
    return _coerce_int(row.value_int, default=default)


def increment_int_state(key: str, delta: int = 1, default: int = 0) -> int:
    normalized_key = str(key).strip()
    try:
        rows = _lock_rows([normalized_key])
        row = rows.get(normalized_key)
        if row is None:
            return int(default)
        row.value_int = _coerce_int(row.value_int, default=default) + int(delta)
        row.updated_at = datetime.utcnow()
        db.session.commit()
        return _coerce_int(row.value_int, default=default)
    except Exception:
        _safe_session_rollback()
        raise


def set_int_state(key: str, value: int) -> int:
    normalized_key = str(key).strip()
    try:
        rows = _lock_rows([normalized_key])
        row = rows.get(normalized_key)
        if row is None:
            return _coerce_int(value)
        row.value_int = _coerce_int(value)
        row.updated_at = datetime.utcnow()
        db.session.commit()
        return _coerce_int(row.value_int)
    except Exception:
        _safe_session_rollback()
        raise


def get_json_state(key: str, default_factory: JsonFactory | Any):
    row = RuntimeState.query.filter_by(state_key=str(key)).first()
    if row is None:
        return _default_value(default_factory)
    return _decode_json(row.value_json, default_factory)


def set_json_state(key: str, value: Any) -> Any:
    normalized_key = str(key).strip()
    try:
        rows = _lock_rows([normalized_key])
        row = rows.get(normalized_key)
        if row is None:
            return value
        row.value_json = _encode_json(value)
        row.updated_at = datetime.utcnow()
        db.session.commit()
        return value
    except Exception:
        _safe_session_rollback()
        raise


@contextmanager
def locked_json_states(specs: dict[str, JsonFactory | Any]):
    normalized_specs = {
        str(key).strip(): factory
        for key, factory in (specs or {}).items()
        if str(key).strip()
    }
    rows = _lock_rows(list(normalized_specs.keys()))
    payloads = {
        key: _decode_json(getattr(rows.get(key), "value_json", None), factory)
        for key, factory in normalized_specs.items()
    }
    try:
        yield payloads
        now = datetime.utcnow()
        for key, value in payloads.items():
            row = rows.get(key)
            if row is None:
                continue
            row.value_json = _encode_json(value)
            row.updated_at = now
        db.session.commit()
    except Exception:
        _safe_session_rollback()
        raise


def mutate_json_states(specs: dict[str, JsonFactory | Any], mutator: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    with locked_json_states(specs) as payloads:
        mutator(payloads)
        return payloads

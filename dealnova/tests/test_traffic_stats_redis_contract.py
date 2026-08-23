from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def _function_body(source: str, function_name: str) -> str:
    marker = f"def {function_name}("
    start = source.index(marker)
    next_def = source.find("\ndef ", start + len(marker))
    return source[start : next_def if next_def != -1 else len(source)]


def test_public_traffic_tracking_hits_redis_before_sql_fallback():
    source = _read("app/services/traffic_stats.py")
    body = _function_body(source, "track_request_hit")

    assert "_redis_record_page_view(now)" in body
    assert "_increment_counter_bucket(" in body
    assert body.index("_redis_record_page_view(now)") < body.index("_increment_counter_bucket(")
    assert "_record_daily_page_view(now" in body


def test_custom_events_and_orders_use_redis_first():
    source = _read("app/services/traffic_stats.py")
    custom_body = _function_body(source, "track_custom_event")
    delivery_body = _function_body(source, "track_delivery_request_created")

    assert "_redis_record_custom_event(safe_event, current_dt)" in custom_body
    assert custom_body.index("_redis_record_custom_event(safe_event, current_dt)") < custom_body.index(
        "_mutate_durable_dicts("
    )
    assert "_redis_record_delivery_request_created(current_dt)" in delivery_body
    assert delivery_body.index("_redis_record_delivery_request_created(current_dt)") < delivery_body.index(
        "_increment_counter_bucket("
    )


def test_live_metrics_prefers_redis_snapshot_and_keeps_sql_fallback():
    source = _read("app/services/traffic_stats.py")
    body = _function_body(source, "get_live_traffic_metrics")

    assert "redis_client = _redis_client()" in body
    assert "_redis_live_metrics_snapshot(redis_client, current_dt)" in body
    assert body.index("redis_client = _redis_client()") < body.index("_read_counter_bucket(")


def test_flush_command_and_hook_are_wired_for_grouped_persistence():
    traffic_source = _read("app/services/traffic_stats.py")
    init_source = _read("app/__init__.py")
    maintenance_source = _read("app/services/maintenance.py")
    flush_body = _function_body(traffic_source, "flush_traffic_analytics_to_sql")

    assert "_ANALYTICS_FLUSH_LOCK_KEY" in traffic_source
    assert "_daily_stats_key(current_dt)" in flush_body
    assert "ACTIVE_VISITORS_KEY" in flush_body
    assert "VISITOR_HISTORY_KEY" in flush_body
    assert "LIFETIME_EVENTS_KEY" in flush_body
    assert "g.analytics_flush_result = flush_traffic_analytics_to_sql(force=False)" in init_source
    assert '@app.cli.command("traffic-flush")' in maintenance_source

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Mapping


DATE_RANGE_VALUES = {"today", "month", "year", "custom"}


@dataclass(frozen=True)
class DateFilter:
    range_filter: str
    start_at: datetime
    end_at: datetime
    date_from: str
    date_to: str
    label: str


def parse_iso_date(raw_value: str | None) -> date | None:
    value = (raw_value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _next_month(month_start: datetime) -> datetime:
    if month_start.month == 12:
        return month_start.replace(year=month_start.year + 1, month=1)
    return month_start.replace(month=month_start.month + 1)


def resolve_date_filter(
    args: Mapping[str, object],
    *,
    default: str = "month",
    now: datetime | None = None,
    from_keys: tuple[str, ...] = ("date_from", "from"),
    to_keys: tuple[str, ...] = ("date_to", "to"),
) -> DateFilter:
    current = now or datetime.utcnow()
    today_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = today_start.replace(day=1)
    year_start = today_start.replace(month=1, day=1)

    range_filter = str(args.get("range") or default).strip().lower()
    if range_filter not in DATE_RANGE_VALUES:
        range_filter = default if default in DATE_RANGE_VALUES else "month"

    date_from_raw = ""
    for key in from_keys:
        date_from_raw = str(args.get(key) or "").strip()
        if date_from_raw:
            break

    date_to_raw = ""
    for key in to_keys:
        date_to_raw = str(args.get(key) or "").strip()
        if date_to_raw:
            break

    custom_from = parse_iso_date(date_from_raw)
    custom_to = parse_iso_date(date_to_raw)

    if range_filter == "today":
        start_at = today_start
        end_at = today_start + timedelta(days=1)
        label = "Aujourd'hui"
    elif range_filter == "year":
        start_at = year_start
        end_at = year_start.replace(year=year_start.year + 1)
        label = "Cette annee"
    elif range_filter == "custom":
        start_at = datetime.combine(custom_from, datetime.min.time()) if custom_from else month_start
        end_at = (
            datetime.combine(custom_to + timedelta(days=1), datetime.min.time())
            if custom_to
            else current + timedelta(days=1)
        )
        label = "Dates"
    else:
        start_at = month_start
        end_at = _next_month(month_start)
        range_filter = "month"
        label = "Ce mois"

    if end_at <= start_at:
        end_at = start_at + timedelta(days=1)

    return DateFilter(
        range_filter=range_filter,
        start_at=start_at,
        end_at=end_at,
        date_from=date_from_raw,
        date_to=date_to_raw,
        label=label,
    )


def apply_date_filter(query, column, date_filter: DateFilter):
    return query.filter(column >= date_filter.start_at, column < date_filter.end_at)

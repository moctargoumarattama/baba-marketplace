import math
from collections.abc import Mapping

from flask import current_app


DEFAULT_MAX_LIMIT = 50


def get_max_limit() -> int:
    try:
        raw = int(current_app.config.get("MAX_LIMIT", DEFAULT_MAX_LIMIT))
    except Exception:
        raw = DEFAULT_MAX_LIMIT
    return max(1, raw)


def normalize_page(page: int | None, default: int = 1) -> int:
    try:
        parsed = int(page if page is not None else default)
    except (TypeError, ValueError):
        parsed = default
    return max(1, parsed)


def normalize_limit(limit: int | None, default: int = 10, max_limit: int | None = None) -> int:
    try:
        parsed = int(limit if limit is not None else default)
    except (TypeError, ValueError):
        parsed = default
    if parsed < 1:
        parsed = default if default > 0 else 1
    ceiling = max_limit if max_limit is not None else get_max_limit()
    return min(parsed, max(1, int(ceiling)))


def page_from_args(args: Mapping[str, object], key: str = "page", default: int = 1) -> int:
    raw = args.get(key, default)
    return normalize_page(raw, default=default)


def limit_from_args(
    args: Mapping[str, object],
    key: str = "limit",
    default: int = 10,
    max_limit: int | None = None,
) -> int:
    raw = args.get(key, default)
    return normalize_limit(raw, default=default, max_limit=max_limit)


def paginate_with_clamped_page(query, *, page: int, per_page: int, error_out: bool = False, **kwargs):
    requested_page = normalize_page(page)
    pagination = query.paginate(
        page=requested_page,
        per_page=per_page,
        error_out=error_out,
        **kwargs,
    )
    pages = int(getattr(pagination, "pages", 0) or 0)
    target_page = pages if pages > 0 else 1
    if requested_page > target_page:
        return query.paginate(
            page=target_page,
            per_page=per_page,
            error_out=error_out,
            **kwargs,
        )
    return pagination


class SimplePagination:
    def __init__(self, page: int, per_page: int, total: int):
        self.page = max(int(page or 1), 1)
        self.per_page = max(int(per_page or 1), 1)
        self.total = int(total or 0)
        if self.total == 0:
            self.pages = 0
        else:
            self.pages = int(math.ceil(self.total / float(self.per_page)))

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.pages > 0 and self.page < self.pages

    @property
    def prev_num(self) -> int:
        return max(self.page - 1, 1)

    @property
    def next_num(self) -> int:
        return min(self.page + 1, self.pages or 1)

    def iter_pages(self, left_edge=2, left_current=2, right_current=2, right_edge=2):
        if self.pages == 0:
            return []
        last = 0
        for num in range(1, self.pages + 1):
            if (
                num <= left_edge
                or (self.page - left_current - 1 < num < self.page + right_current)
                or num > self.pages - right_edge
            ):
                if last + 1 != num:
                    yield None
                yield num
                last = num

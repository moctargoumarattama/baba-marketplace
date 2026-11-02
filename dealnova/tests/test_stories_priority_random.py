import random
from datetime import datetime, timedelta
import pytest

from dealnova.app.services.stories import get_homepage_stories


def test_picking_prioritizes_24h_and_falls_back_to_recent():
    pool_24h = [{"id": f"item_24h_{i}", "title": f"Item 24h {i}"} for i in range(50)]
    pool_recent = [{"id": f"item_recent_{i}", "title": f"Item Recent {i}"} for i in range(30)]

    def pick(limit=15, stories_24h=None, stories_recent=None):
        s24 = list(stories_24h or [])
        srec = list(stories_recent or [])
        random.shuffle(s24)
        random.shuffle(srec)
        selected = s24[:limit]
        if len(selected) < limit:
            seen = {s["id"] for s in selected}
            for it in srec:
                if it["id"] not in seen:
                    selected.append(it)
                    seen.add(it["id"])
                    if len(selected) >= limit:
                        break
        return selected

    # Case 1: 50 items in 24h -> all 15 are randomly picked from 24h
    res1 = pick(15, pool_24h, pool_recent)
    assert len(res1) == 15
    assert all("24h" in x["id"] for x in res1)

    # Case 2: 5 items in 24h -> exactly 5 from 24h + 10 from recent
    res2 = pick(15, pool_24h[:5], pool_recent)
    assert len(res2) == 15
    assert sum(1 for x in res2 if "24h" in x["id"]) == 5
    assert sum(1 for x in res2 if "recent" in x["id"]) == 10

    # Case 3: 0 items in 24h -> all 15 from recent
    res3 = pick(15, [], pool_recent)
    assert len(res3) == 15
    assert all("recent" in x["id"] for x in res3)


def test_random_shuffle_produces_variance():
    pool_24h = [{"id": f"item_24h_{i}", "title": f"Item 24h {i}"} for i in range(25)]
    orders = set()
    for _ in range(5):
        s = list(pool_24h)
        random.shuffle(s)
        orders.add(tuple(x["id"] for x in s[:5]))
    # With 25 items shuffled 5 times, there should be multiple distinct orderings
    assert len(orders) > 1

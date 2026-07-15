"""
Tests for extract/extract_orders.py — the days_back / updated_at filter logic.

We mock extract.extract_orders.run_query so no network call to Shopify happens,
and capture every GraphQL query string the extractor builds so we can assert on it.

The mock returns a single empty page (hasNextPage = False) so the pagination
loop runs exactly once and we get exactly one query to inspect.
"""

import re
from datetime import datetime, timedelta, timezone

import pytest

from extract import extract_orders as orders_mod


def _empty_page():
    """A run_query response with no orders and no next page."""
    return {
        "data": {
            "orders": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }
        }
    }


@pytest.fixture
def captured_queries(monkeypatch):
    """Patch run_query to capture query strings instead of hitting Shopify."""
    queries = []

    def fake_run_query(query, variables=None, store="fellers_ranch"):
        queries.append(query)
        return _empty_page()

    monkeypatch.setattr(orders_mod, "run_query", fake_run_query)
    return queries


def test_days_back_injects_updated_at_filter(captured_queries):
    """days_back=N must add a `query: "updated_at:>=..."` clause."""
    orders_mod.extract_orders(days_back=7)

    assert len(captured_queries) == 1
    query = captured_queries[0]

    assert 'query: "updated_at:>=' in query


def test_days_back_cutoff_date_is_correct(captured_queries):
    """The cutoff in the filter must be ~N days before now (UTC)."""
    days_back = 30
    before = datetime.now(timezone.utc) - timedelta(days=days_back)

    orders_mod.extract_orders(days_back=days_back)
    after = datetime.now(timezone.utc) - timedelta(days=days_back)

    query = captured_queries[0]
    match = re.search(r'updated_at:>=(\S+?)"', query)
    assert match, f"no updated_at cutoff found in query:\n{query}"

    cutoff = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )

    # Cutoff must fall within the window bracketed by our two "now" readings
    # (allow 1s of slack on each side for clock/second-rounding).
    assert before - timedelta(seconds=1) <= cutoff <= after + timedelta(seconds=1)


def test_days_back_none_produces_no_filter_clause(captured_queries):
    """days_back=None (full backfill) must NOT add any query filter clause."""
    orders_mod.extract_orders(days_back=None)

    query = captured_queries[0]
    assert "updated_at" not in query
    assert "query:" not in query


def test_sort_key_is_updated_at(captured_queries):
    """orders(...) must always sort by UPDATED_AT, in both modes."""
    orders_mod.extract_orders(days_back=14)
    orders_mod.extract_orders(days_back=None)

    for query in captured_queries:
        assert "sortKey: UPDATED_AT" in query


def test_pagination_follows_cursor(monkeypatch):
    """Sanity check: a two-page response is fully drained and cursor threaded."""
    responses = [
        {
            "data": {
                "orders": {
                    "pageInfo": {"hasNextPage": True, "endCursor": "CURSOR_1"},
                    "edges": [{"node": {"id": "gid://order/1"}}],
                }
            }
        },
        {
            "data": {
                "orders": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "edges": [{"node": {"id": "gid://order/2"}}],
                }
            }
        },
    ]
    calls = []

    def fake_run_query(query, variables=None, store="fellers_ranch"):
        calls.append(query)
        return responses[len(calls) - 1]

    monkeypatch.setattr(orders_mod, "run_query", fake_run_query)

    result = orders_mod.extract_orders(days_back=None)

    assert len(result) == 2
    # First page has no cursor; second page must thread the returned endCursor.
    assert 'after:' not in calls[0]
    assert 'after: "CURSOR_1"' in calls[1]

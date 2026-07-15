"""
Tests for load/bigquery_client.py — upsert idempotency logic.

No BigQuery is ever contacted: get_client() is patched to return a MagicMock,
and we assert on the SQL strings the MERGE upsert builds rather than executing
them. load_schema and create_table_if_not_exists are patched too so no schema
files are read and no staging table is created.
"""

from unittest.mock import MagicMock

import pytest

from load import bigquery_client


@pytest.fixture
def mock_bq(monkeypatch):
    """
    Patch out every external touchpoint of upsert_rows and hand back the
    mock client so tests can inspect .query() / .load_table_from_json() calls.
    """
    client = MagicMock(name="bq_client")
    # load_table_from_json(...).result() and query(...).result() must chain.
    client.load_table_from_json.return_value.result.return_value = None
    client.query.return_value.result.return_value = None

    monkeypatch.setattr(bigquery_client, "get_client", lambda: client)
    monkeypatch.setattr(bigquery_client, "create_table_if_not_exists", lambda *a, **k: None)
    monkeypatch.setattr(bigquery_client, "load_schema", lambda *a, **k: [])
    # bigquery.LoadJobConfig is still the real class; give it a harmless stub
    # so we don't depend on enum internals during construction.
    monkeypatch.setattr(
        bigquery_client.bigquery, "LoadJobConfig", MagicMock(name="LoadJobConfig")
    )
    return client


def _merge_query(client):
    """Return the MERGE SQL string (first .query() call) from a mock client."""
    assert client.query.call_args_list, "client.query was never called"
    return client.query.call_args_list[0].args[0]


def test_empty_rows_is_noop(monkeypatch):
    """upsert_rows([]) must not touch the client at all."""
    def boom():
        raise AssertionError("get_client() called for an empty upsert")

    monkeypatch.setattr(bigquery_client, "get_client", boom)

    # Should return cleanly without raising / without building a client.
    bigquery_client.upsert_rows("fact_orders", [], key_field="order_id")


def test_merge_on_clause_uses_key_field(mock_bq):
    rows = [{"order_id": "1", "total": "10.00"}]
    bigquery_client.upsert_rows("fact_orders", rows, key_field="order_id")

    query = _merge_query(mock_bq)
    assert "ON T.order_id = S.order_id" in query


def test_merge_dedup_partitions_by_key_field(mock_bq):
    rows = [{"order_id": "1", "total": "10.00"}]
    bigquery_client.upsert_rows("fact_orders", rows, key_field="order_id")

    query = _merge_query(mock_bq)
    # ROW_NUMBER() dedup must partition by the key field.
    assert "ROW_NUMBER()" in query
    assert "PARTITION BY order_id" in query
    assert "WHERE row_num = 1" in query


def test_merge_update_excludes_key_field_but_insert_includes_it(mock_bq):
    """UPDATE SET must not reassign the key; INSERT must still list it."""
    rows = [{"order_id": "1", "total": "10.00", "status": "paid"}]
    bigquery_client.upsert_rows("fact_orders", rows, key_field="order_id")

    query = _merge_query(mock_bq)
    # Non-key fields are updated...
    assert "T.total = S.total" in query
    assert "T.status = S.status" in query
    # ...but the key field is never on the left of an UPDATE assignment.
    assert "T.order_id = S.order_id" not in query.split("WHEN MATCHED")[1].split(
        "WHEN NOT MATCHED"
    )[0]
    # INSERT column list still includes the key.
    assert "order_id" in query.split("INSERT (")[1]


def test_key_field_flows_through_for_different_table(mock_bq):
    """Sanity: a different key_field is threaded everywhere it matters."""
    rows = [{"sku": "ABC", "name": "Widget"}]
    bigquery_client.upsert_rows("dim_products", rows, key_field="sku")

    query = _merge_query(mock_bq)
    assert "PARTITION BY sku" in query
    assert "ON T.sku = S.sku" in query


def test_staging_is_cleared_after_merge(mock_bq):
    """The final query must clear the staging table (idempotency hygiene)."""
    rows = [{"order_id": "1", "total": "10.00"}]
    bigquery_client.upsert_rows("fact_orders", rows, key_field="order_id")

    # Two queries: [0] MERGE, [1] DELETE staging.
    assert len(mock_bq.query.call_args_list) == 2
    delete_query = mock_bq.query.call_args_list[1].args[0]
    assert "DELETE FROM" in delete_query
    assert "fact_orders_staging" in delete_query

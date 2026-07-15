"""
Tests for extract/airtable_client.py — the optional-Airtable branching.

Airtable is optional; the client must short-circuit (never raise, never call
the network) when credentials are missing or set to the literal "placeholder".

Credentials are read from the environment at call time, so we drive these tests
purely with monkeypatch.setenv / delenv — no network, no real .env.
"""

import pytest

from extract import airtable_client


@pytest.fixture(autouse=True)
def clear_airtable_env(monkeypatch):
    """Start every test from a known state: no Airtable creds set."""
    monkeypatch.delenv("AIRTABLE_API_KEY", raising=False)
    monkeypatch.delenv("AIRTABLE_BASE_ID", raising=False)


def test_not_configured_when_creds_missing():
    assert airtable_client._airtable_configured() is False


def test_not_configured_when_only_api_key_present(monkeypatch):
    monkeypatch.setenv("AIRTABLE_API_KEY", "key_real123")
    # base id still missing
    assert airtable_client._airtable_configured() is False


def test_not_configured_when_only_base_id_present(monkeypatch):
    monkeypatch.setenv("AIRTABLE_BASE_ID", "app_real123")
    # api key still missing
    assert airtable_client._airtable_configured() is False


@pytest.mark.parametrize(
    "api_key, base_id",
    [
        ("placeholder", "app_real123"),
        ("key_real123", "placeholder"),
        ("placeholder", "placeholder"),
        ("PLACEHOLDER", "app_real123"),  # case-insensitive
        ("key_real123", "  placeholder  "),  # whitespace-trimmed
    ],
)
def test_not_configured_when_creds_are_placeholder(monkeypatch, api_key, base_id):
    monkeypatch.setenv("AIRTABLE_API_KEY", api_key)
    monkeypatch.setenv("AIRTABLE_BASE_ID", base_id)
    assert airtable_client._airtable_configured() is False


def test_configured_only_when_both_creds_real(monkeypatch):
    monkeypatch.setenv("AIRTABLE_API_KEY", "key_real123")
    monkeypatch.setenv("AIRTABLE_BASE_ID", "app_real123")
    assert airtable_client._airtable_configured() is True


def test_extract_sku_mapping_returns_empty_when_not_configured(monkeypatch):
    """Must return {} (not raise, not hit the network) when unconfigured."""
    # Guard: if this were to reach the network, requests.get would blow up loudly.
    def explode(*args, **kwargs):
        raise AssertionError("network call attempted while Airtable unconfigured")

    monkeypatch.setattr(airtable_client.requests, "get", explode)

    result = airtable_client.extract_sku_mapping()
    assert result == {}


def test_fetch_table_returns_empty_when_not_configured(monkeypatch):
    """fetch_table short-circuits to [] without touching the network."""
    def explode(*args, **kwargs):
        raise AssertionError("network call attempted while Airtable unconfigured")

    monkeypatch.setattr(airtable_client.requests, "get", explode)

    assert airtable_client.fetch_table("MASTER") == []

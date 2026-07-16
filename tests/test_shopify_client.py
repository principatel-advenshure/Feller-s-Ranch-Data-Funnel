"""
Tests for extract/shopify_client.py — the GraphQL runner, its error handling,
and the reused module-level Session.

Fully offline: get_valid_token is stubbed (no auth, no real shop URL) and the
module-level _SESSION.post is monkeypatched (no HTTP). The retry/backoff config
lives on the urllib3 Retry attached to the session's adapter, so we assert on
that configuration rather than firing real transient failures.
"""

import pytest

from extract import shopify_client as sc


class _FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json


@pytest.fixture
def _fake_token(monkeypatch):
    """Stub auth so run_query never touches token_manager / the network."""
    monkeypatch.setattr(
        sc,
        "get_valid_token",
        lambda store="fellers_ranch": ("fake-token", "fellers.myshopify.com", None, None),
    )


# --------------------------------------------------------------------------- #
# run_query — happy path
# --------------------------------------------------------------------------- #

def test_run_query_returns_parsed_data_on_200(monkeypatch, _fake_token):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _FakeResponse(200, {"data": {"shop": {"name": "Feller's Ranch"}}})

    monkeypatch.setattr(sc._SESSION, "post", fake_post)

    result = sc.run_query("{ shop { name } }")

    assert result == {"data": {"shop": {"name": "Feller's Ranch"}}}
    # URL is built from the shop_url + pinned API version.
    assert captured["url"] == (
        "https://fellers.myshopify.com/admin/api/2026-07/graphql.json"
    )
    # Token from get_valid_token flows into the auth header.
    assert captured["headers"]["X-Shopify-Access-Token"] == "fake-token"
    # (connect, read) timeout tuple is passed through.
    assert captured["timeout"] == (sc.CONNECT_TIMEOUT, sc.READ_TIMEOUT)


def test_run_query_passes_variables_when_provided(monkeypatch, _fake_token):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        return _FakeResponse(200, {"data": {}})

    monkeypatch.setattr(sc._SESSION, "post", fake_post)

    sc.run_query("query($id: ID!){ node(id:$id){ id } }", variables={"id": "gid://1"})

    assert captured["json"]["variables"] == {"id": "gid://1"}


def test_run_query_omits_variables_when_none(monkeypatch, _fake_token):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        return _FakeResponse(200, {"data": {}})

    monkeypatch.setattr(sc._SESSION, "post", fake_post)

    sc.run_query("{ shop { name } }")

    assert "variables" not in captured["json"]


# --------------------------------------------------------------------------- #
# run_query — error paths
# --------------------------------------------------------------------------- #

def test_run_query_raises_on_non_200(monkeypatch, _fake_token):
    monkeypatch.setattr(
        sc._SESSION, "post",
        lambda *a, **k: _FakeResponse(401, {}, text="Unauthorized"),
    )

    with pytest.raises(Exception, match="Query failed: 401"):
        sc.run_query("{ shop { name } }")


def test_run_query_raises_on_graphql_errors_in_body(monkeypatch, _fake_token):
    monkeypatch.setattr(
        sc._SESSION, "post",
        lambda *a, **k: _FakeResponse(
            200, {"errors": [{"message": "Field 'bogus' doesn't exist"}]}
        ),
    )

    with pytest.raises(Exception, match="GraphQL error"):
        sc.run_query("{ bogus }")


# --------------------------------------------------------------------------- #
# Session singleton / reuse
# --------------------------------------------------------------------------- #

def test_session_is_reused_across_calls(monkeypatch, _fake_token):
    """run_query must reuse the module-level _SESSION, not build a fresh one."""
    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        return _FakeResponse(200, {"data": {}})

    monkeypatch.setattr(sc._SESSION, "post", fake_post)

    # Guard: if run_query ever rebuilds the session, this blows up.
    def _boom():
        raise AssertionError("_build_session should not be called during run_query")

    monkeypatch.setattr(sc, "_build_session", _boom)

    session_before = sc._SESSION
    sc.run_query("{ shop { name } }")
    sc.run_query("{ shop { name } }")

    assert calls["n"] == 2
    assert sc._SESSION is session_before  # same singleton object


def test_session_is_a_requests_session_with_retry_adapter():
    import requests

    assert isinstance(sc._SESSION, requests.Session)

    adapter = sc._SESSION.get_adapter("https://fellers.myshopify.com")
    retry = adapter.max_retries

    assert retry.total == sc.MAX_CONNECTION_RETRIES
    assert retry.backoff_factor == 1.0
    # Transient statuses are retried; POST is in the allowed set.
    assert set(retry.status_forcelist) == {429, 500, 502, 503, 504}
    assert "POST" in retry.allowed_methods


# --------------------------------------------------------------------------- #
# Pinned API version
# --------------------------------------------------------------------------- #

def test_api_version_is_pinned():
    assert sc.API_VERSION == "2026-07"

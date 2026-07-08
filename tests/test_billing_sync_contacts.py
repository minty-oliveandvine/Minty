"""Tests for the billing contacts-sync endpoint.

Regression: Module 2 (billing_backend) POSTs to
``/api/entities/<id>/billing/sync-contacts-if-changed`` when the Bill Settings /
contact picker opens, but Module 1 only ever implemented the *chart* sync
routes — so the contacts POST hit no route and Flask returned a default 404
(seen in app.log as ``...sync-contacts-if-changed HTTP/1.1" 404``). This adds
the missing route; these tests pin its behaviour via the real app/test client,
which also proves the route is registered (not a 404-not-found anymore).
"""

from __future__ import annotations

from types import SimpleNamespace

URL = "/api/entities/e1/billing/sync-contacts-if-changed"


def test_missing_bearer_returns_401(client):
    resp = client.post(URL)
    assert resp.status_code == 401
    assert resp.get_json()["message"] == "Bearer token required"


def test_unknown_entity_returns_json_404(client, monkeypatch):
    """Bearer present but entity absent. A JSON ``entity_not_found`` 404 proves
    the route is registered — a missing route (the original bug) would be
    Flask's default HTML 404 with no JSON body instead."""
    from blueprints.entity.routes import billing_sync

    monkeypatch.setattr(
        billing_sync,
        "Entity",
        SimpleNamespace(query=SimpleNamespace(get=lambda _id: None)),
    )
    resp = client.post(URL, headers={"Authorization": "Bearer abc"})
    assert resp.status_code == 404
    assert resp.get_json()["reason"] == "entity_not_found"


def test_no_xero_org_id_skips(client, monkeypatch):
    from blueprints.entity.routes import billing_sync

    monkeypatch.setattr(
        billing_sync,
        "Entity",
        SimpleNamespace(query=SimpleNamespace(get=lambda _id: SimpleNamespace(xero_org_id=None))),
    )
    resp = client.post(URL, headers={"Authorization": "Bearer abc"})
    assert resp.status_code == 200
    assert resp.get_json()["reason"] == "no_xero_org_id"


def test_happy_path_triggers_background_sync(client, monkeypatch):
    from blueprints.entity.routes import billing_sync

    monkeypatch.setattr(
        billing_sync,
        "Entity",
        SimpleNamespace(query=SimpleNamespace(get=lambda _id: SimpleNamespace(xero_org_id="org-123"))),
    )
    token_user = SimpleNamespace(id="u1", access_token="tok")
    monkeypatch.setattr(
        billing_sync, "get_xero_token_user_for_entity", lambda _id: token_user
    )
    monkeypatch.setattr(billing_sync, "ensure_valid_token", lambda _u: True)

    calls = []
    monkeypatch.setattr(
        billing_sync,
        "sync_contacts_if_changed_background",
        lambda *a, **kw: calls.append((a, kw)),
    )

    resp = client.post(URL, headers={"Authorization": "Bearer abc"})
    assert resp.status_code == 202
    assert resp.get_json()["status"] == "triggered"
    # Resolved locally (entity_id, access_token, xero_org_id) — never trusting
    # the request payload.
    assert calls == [(("e1", "tok", "org-123"), {})]


def test_no_valid_token_skips(client, monkeypatch):
    from blueprints.entity.routes import billing_sync

    monkeypatch.setattr(
        billing_sync,
        "Entity",
        SimpleNamespace(query=SimpleNamespace(get=lambda _id: SimpleNamespace(xero_org_id="org-123"))),
    )
    monkeypatch.setattr(
        billing_sync, "get_xero_token_user_for_entity", lambda _id: None
    )
    monkeypatch.setattr(billing_sync, "ensure_valid_token", lambda _u: False)

    resp = client.post(URL, headers={"Authorization": "Bearer abc"})
    assert resp.status_code == 200
    assert resp.get_json()["reason"] == "no_valid_xero_token"

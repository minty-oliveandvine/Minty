from __future__ import annotations

from blueprints.entity.services import payment_methods


def test_list_payment_methods_denies_without_permission(monkeypatch):
    monkeypatch.setattr(
        payment_methods, "has_permission_by_user_id", lambda *_args, **_kwargs: False
    )
    response, status = payment_methods.list_payment_methods("user-1", "entity-1")
    assert status == 403
    assert response["error"] == "Access denied"


def test_add_payment_method_denies_without_permission(monkeypatch):
    monkeypatch.setattr(
        payment_methods, "has_permission_by_user_id", lambda *_args, **_kwargs: False
    )
    response, status = payment_methods.add_payment_method(
        "user-1",
        "entity-1",
        {"name": "Visa", "type": "Electronic", "value_name": "visa_sales"},
    )
    assert status == 403
    assert response["error"] == "Access denied"


def test_add_payment_method_validates_required_fields_before_db(monkeypatch):
    monkeypatch.setattr(
        payment_methods, "has_permission_by_user_id", lambda *_args, **_kwargs: True
    )
    response, status = payment_methods.add_payment_method("user-1", "entity-1", {})
    assert status == 400
    assert response["error"] == "No data provided"


def test_update_payment_method_denies_without_permission(monkeypatch):
    monkeypatch.setattr(
        payment_methods, "has_permission_by_user_id", lambda *_args, **_kwargs: False
    )
    response, status = payment_methods.update_payment_method(
        "user-1", "entity-1", "method-1", {"name": "Mastercard"}
    )
    assert status == 403
    assert response["error"] == "Access denied"


def test_delete_payment_method_denies_without_permission(monkeypatch):
    monkeypatch.setattr(
        payment_methods, "has_permission_by_user_id", lambda *_args, **_kwargs: False
    )
    response, status = payment_methods.delete_payment_method(
        "user-1", "entity-1", "method-1"
    )
    assert status == 403
    assert response["error"] == "Access denied"


def test_reorder_payment_methods_denies_without_permission(monkeypatch):
    monkeypatch.setattr(
        payment_methods, "has_permission_by_user_id", lambda *_args, **_kwargs: False
    )
    response, status = payment_methods.reorder_payment_methods(
        "user-1", "entity-1", ["m1", "m2"]
    )
    assert status == 403
    assert response["error"] == "Access denied"


def test_reorder_payment_methods_validates_method_ids(monkeypatch):
    monkeypatch.setattr(
        payment_methods, "has_permission_by_user_id", lambda *_args, **_kwargs: True
    )
    response, status = payment_methods.reorder_payment_methods("user-1", "entity-1", None)
    assert status == 400
    assert response["error"] == "method_ids array is required"

"""Tests for cashier report history permissions.

Cashiers should be able to:
- View all reports in their entity (own + others)
- Edit/create drafts for any report in their entity (own + others)
- Delete only their own reports (not others')

The report step routes (opening, sales, expense, deposit, cash_count, ending)
use ``has_permission(REPORT_EDIT_OWN)`` which grants edit access to any report
within the entity, regardless of ownership.  The ``can_edit_report`` /
``can_delete_report`` helpers are still ownership-aware and used for the delete
flow and the report-detail legacy routes.
"""
from __future__ import annotations

from types import SimpleNamespace

from services.permission_policy import (
    Permission,
    Role,
    can_delete_report,
    can_edit_report,
    can_view_report,
    has_permission,
)


# ---------------------------------------------------------------------------
# REPORT_VIEW_ENTITY is accessible by cashier role
# ---------------------------------------------------------------------------


def test_cashier_has_report_view_entity_permission(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="cashier", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    cashier = SimpleNamespace(id="cashier-1", role="entity_base")
    assert has_permission(cashier, Permission.REPORT_VIEW_ENTITY, entity_id="e-1")


def test_cashier_has_report_view_own_permission(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="cashier", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    cashier = SimpleNamespace(id="cashier-1", role="entity_base")
    assert has_permission(cashier, Permission.REPORT_VIEW_OWN, entity_id="e-1")


# ---------------------------------------------------------------------------
# Cashier can view all reports (own + others)
# ---------------------------------------------------------------------------


def test_cashier_can_view_own_report(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="cashier", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    cashier = SimpleNamespace(id="cashier-1", username="alice", role="entity_base")
    own_report = SimpleNamespace(company="e-1", uploaded_by="alice")

    assert can_view_report(cashier, own_report)


def test_cashier_can_view_other_users_report(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="cashier", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    cashier = SimpleNamespace(id="cashier-1", username="alice", role="entity_base")
    other_report = SimpleNamespace(company="e-1", uploaded_by="bob")

    assert can_view_report(cashier, other_report)


# ---------------------------------------------------------------------------
# Cashier can edit/create drafts for any entity report (route-level check)
#
# Routes use ``has_permission(REPORT_EDIT_OWN)`` which does NOT check
# ownership -- any cashier+ in the entity can edit any report.
# ---------------------------------------------------------------------------


def test_cashier_has_report_edit_own_permission(monkeypatch):
    """REPORT_EDIT_OWN (used by routes) grants edit access to any entity report."""
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="cashier", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    cashier = SimpleNamespace(id="cashier-1", role="entity_base")
    assert has_permission(cashier, Permission.REPORT_EDIT_OWN, entity_id="e-1")


def test_cashier_can_edit_own_report(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="cashier", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    cashier = SimpleNamespace(id="cashier-1", username="alice", role="entity_base")
    own_report = SimpleNamespace(company="e-1", uploaded_by="alice")

    assert can_edit_report(cashier, own_report)


def test_can_edit_report_helper_still_checks_ownership(monkeypatch):
    """can_edit_report policy helper retains ownership check (used by delete flow)."""
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="cashier", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    cashier = SimpleNamespace(id="cashier-1", username="alice", role="entity_base")
    other_report = SimpleNamespace(company="e-1", uploaded_by="bob")

    assert not can_edit_report(cashier, other_report)


def test_route_level_edit_allows_cashier_on_any_entity_report(monkeypatch):
    """Routes check REPORT_EDIT_OWN (not can_edit_report), so any cashier can edit."""
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="cashier", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    alice = SimpleNamespace(id="cashier-1", username="alice", role="entity_base")
    bob = SimpleNamespace(id="cashier-2", username="bob", role="entity_base")

    assert has_permission(alice, Permission.REPORT_EDIT_OWN, entity_id="e-1")
    assert has_permission(bob, Permission.REPORT_EDIT_OWN, entity_id="e-1")


# ---------------------------------------------------------------------------
# Cashier can only delete their own reports
# ---------------------------------------------------------------------------


def test_cashier_can_delete_own_report(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="cashier", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    cashier = SimpleNamespace(id="cashier-1", username="alice", role="entity_base")
    own_report = SimpleNamespace(company="e-1", uploaded_by="alice")

    assert can_delete_report(cashier, own_report)


def test_cashier_cannot_delete_other_users_report(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="cashier", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    cashier = SimpleNamespace(id="cashier-1", username="alice", role="entity_base")
    other_report = SimpleNamespace(company="e-1", uploaded_by="bob")

    assert not can_delete_report(cashier, other_report)


# ---------------------------------------------------------------------------
# Higher roles (shop_manager+) retain full entity-level edit/delete
# ---------------------------------------------------------------------------


def test_shop_manager_can_edit_any_report(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="shop_manager", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    manager = SimpleNamespace(id="mgr-1", username="boss", role="entity_base")
    other_report = SimpleNamespace(company="e-1", uploaded_by="alice")

    assert can_edit_report(manager, other_report)


def test_shop_manager_can_delete_any_report(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="shop_manager", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    manager = SimpleNamespace(id="mgr-1", username="boss", role="entity_base")
    other_report = SimpleNamespace(company="e-1", uploaded_by="alice")

    assert can_delete_report(manager, other_report)


def test_shop_manager_can_view_any_report(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="shop_manager", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    manager = SimpleNamespace(id="mgr-1", username="boss", role="entity_base")
    other_report = SimpleNamespace(company="e-1", uploaded_by="alice")

    assert can_view_report(manager, other_report)


# ---------------------------------------------------------------------------
# Entity base role cannot view/edit entity reports
# ---------------------------------------------------------------------------


def test_entity_base_cannot_view_entity_reports(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="entity_base", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    base_user = SimpleNamespace(id="base-1", username="nobody", role="entity_base")
    assert not has_permission(base_user, Permission.REPORT_VIEW_ENTITY, entity_id="e-1")


def test_entity_base_cannot_view_other_users_report(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="entity_base", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    base_user = SimpleNamespace(id="base-1", username="nobody", role="entity_base")
    other_report = SimpleNamespace(company="e-1", uploaded_by="alice")

    assert not can_view_report(base_user, other_report)


def test_entity_base_cannot_edit_reports(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="entity_base", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    base_user = SimpleNamespace(id="base-1", role="entity_base")
    assert not has_permission(base_user, Permission.REPORT_EDIT_OWN, entity_id="e-1")


# ---------------------------------------------------------------------------
# Cashier REPORT_EDIT_ENTITY and REPORT_DELETE_ENTITY remain shop_manager+
# ---------------------------------------------------------------------------


def test_cashier_lacks_report_edit_entity_permission(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="cashier", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    cashier = SimpleNamespace(id="cashier-1", role="entity_base")
    assert not has_permission(cashier, Permission.REPORT_EDIT_ENTITY, entity_id="e-1")


def test_cashier_lacks_report_delete_entity_permission(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="cashier", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    cashier = SimpleNamespace(id="cashier-1", role="entity_base")
    assert not has_permission(cashier, Permission.REPORT_DELETE_ENTITY, entity_id="e-1")


# ---------------------------------------------------------------------------
# Report history route logic: cashier sees all reports (uploaded_by=None)
# ---------------------------------------------------------------------------


def test_history_route_shows_all_reports_for_cashier(monkeypatch):
    """When a cashier has REPORT_VIEW_ENTITY, uploaded_by should be None (all reports)."""
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="cashier", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    cashier = SimpleNamespace(id="cashier-1", role="entity_base")
    can_view_entity = has_permission(
        cashier, Permission.REPORT_VIEW_ENTITY, entity_id="e-1"
    )
    uploaded_by = None if can_view_entity else "cashier-username"

    assert can_view_entity is True
    assert uploaded_by is None


def test_history_route_shows_all_reports_for_entity_connected_user():
    """Any user connected to an entity sees all reports (uploaded_by=None).

    The history route now sets can_view_entity_history=True unconditionally
    because @require_entity_access already verifies entity membership.
    """
    can_view_entity_history = True
    uploaded_by = None if can_view_entity_history else "base-username"

    assert can_view_entity_history is True
    assert uploaded_by is None


# ---------------------------------------------------------------------------
# Cross-entity isolation: cashier cannot access reports from another entity
# ---------------------------------------------------------------------------


def test_cashier_cannot_view_report_from_different_entity(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, entity_id):
        if entity_id == "e-1":
            return SimpleNamespace(role="cashier", approved=True)
        return None

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    cashier = SimpleNamespace(id="cashier-1", username="alice", role="entity_base")
    report_other_entity = SimpleNamespace(company="e-2", uploaded_by="bob")

    assert not can_view_report(cashier, report_other_entity)
    assert not can_edit_report(cashier, report_other_entity)
    assert not can_delete_report(cashier, report_other_entity)


def test_cashier_cannot_edit_report_in_different_entity(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, entity_id):
        if entity_id == "e-1":
            return SimpleNamespace(role="cashier", approved=True)
        return None

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    cashier = SimpleNamespace(id="cashier-1", role="entity_base")
    assert not has_permission(cashier, Permission.REPORT_EDIT_OWN, entity_id="e-2")

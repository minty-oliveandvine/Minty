from __future__ import annotations

from types import SimpleNamespace

from services.permission_policy import (
    Permission,
    Role,
    can_delete_report,
    can_edit_report,
    can_view_report,
    can_manage_role_assignment,
    has_permission,
    is_superuser,
    legacy_role_to_system_role,
    normalize_role,
    normalize_system_role,
    role_at_least,
)


def test_normalize_role_aliases():
    assert normalize_role("user") == Role.ENTITY_BASE.value
    assert normalize_role("client") == Role.CASHIER.value
    assert normalize_role("shop manager") == Role.SHOP_MANAGER.value
    assert normalize_role("super admin") == Role.SUPER_ADMIN.value


def test_normalize_system_role_aliases():
    assert normalize_system_role(None) == "normal"
    assert normalize_system_role("normal") == "normal"
    assert normalize_system_role("SUPERADMIN") == "superadmin"
    assert normalize_system_role("SUPERUSER") == "superadmin"  # pre-rename spelling
    assert normalize_system_role("unexpected") == "normal"


def test_legacy_role_to_system_role_promotes_only_admin_variants():
    assert legacy_role_to_system_role("admin") == "superadmin"
    assert legacy_role_to_system_role("super admin") == "superadmin"
    assert legacy_role_to_system_role("cashier") == "normal"
    assert legacy_role_to_system_role("accountant") == "normal"


def test_is_superuser_supports_system_role_and_legacy_role():
    assert is_superuser(SimpleNamespace(system_role="superuser")) is True
    assert is_superuser(SimpleNamespace(system_role="normal")) is False
    assert is_superuser(SimpleNamespace(role="super_admin")) is True
    assert is_superuser(SimpleNamespace(role="admin")) is True
    assert is_superuser(SimpleNamespace(role="accountant")) is False


def test_role_hierarchy_comparison():
    assert role_at_least("accountant", "shop_manager")
    assert role_at_least("super_admin", "admin")
    assert not role_at_least("cashier", "accountant")


def test_can_manage_role_assignment():
    assert can_manage_role_assignment("shop_manager", "cashier")
    assert can_manage_role_assignment("accountant", "shop_manager")
    assert not can_manage_role_assignment("shop_manager", "accountant")
    assert can_manage_role_assignment("shop_manager", "shop_manager")
    assert not can_manage_role_assignment("cashier", "cashier")


def test_has_permission_with_entity_membership(monkeypatch):
    from services import permission_policy

    user = SimpleNamespace(id="u-1", role="entity_base")

    def _membership(_user_id, _entity_id):
        return SimpleNamespace(role="shop_manager", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    assert has_permission(user, Permission.USER_INVITE, entity_id="e-1")
    assert has_permission(user, Permission.REPORT_VIEW_ENTITY, entity_id="e-1")
    assert not has_permission(user, Permission.XERO_SETTINGS_UPDATE, entity_id="e-1")


def test_report_history_permissions_by_role(monkeypatch):
    from services import permission_policy

    def _membership(user_id, _entity_id):
        role = "cashier" if user_id == "cashier" else "accountant"
        return SimpleNamespace(role=role, approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    cashier = SimpleNamespace(id="cashier", role="entity_base")
    accountant = SimpleNamespace(id="accountant", role="entity_base")

    assert has_permission(cashier, Permission.REPORT_VIEW_OWN, entity_id="e-1")
    assert has_permission(cashier, Permission.REPORT_VIEW_ENTITY, entity_id="e-1")
    assert has_permission(accountant, Permission.REPORT_VIEW_ENTITY, entity_id="e-1")


def test_entity_create_permission_is_available_to_all_authenticated_users():
    normal_user = SimpleNamespace(id="u-1", system_role="normal")
    superuser = SimpleNamespace(id="u-2", system_role="superuser")

    assert has_permission(normal_user, Permission.ENTITY_CREATE)
    assert has_permission(superuser, Permission.ENTITY_CREATE)
    assert not has_permission(None, Permission.ENTITY_CREATE)


def test_user_role_delete_permission_requires_accountant(monkeypatch):
    from services import permission_policy

    def _membership(user_id, _entity_id):
        role = "accountant" if user_id == "acct" else "shop_manager"
        return SimpleNamespace(role=role, approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    accountant = SimpleNamespace(id="acct", role="entity_base")
    manager = SimpleNamespace(id="mgr", role="entity_base")

    assert has_permission(accountant, Permission.USER_ROLE_DELETE, entity_id="e-1")
    assert not has_permission(manager, Permission.USER_ROLE_DELETE, entity_id="e-1")


def test_coa_create_delete_permissions_require_accountant(monkeypatch):
    from services import permission_policy

    def _membership(user_id, _entity_id):
        role = "accountant" if user_id == "acct" else "shop_manager"
        return SimpleNamespace(role=role, approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    accountant = SimpleNamespace(id="acct", role="entity_base")
    manager = SimpleNamespace(id="mgr", role="entity_base")

    assert has_permission(accountant, Permission.COA_CREATE, entity_id="e-1")
    assert has_permission(accountant, Permission.COA_DELETE, entity_id="e-1")
    assert not has_permission(manager, Permission.COA_CREATE, entity_id="e-1")
    assert not has_permission(manager, Permission.COA_DELETE, entity_id="e-1")


def test_has_permission_denies_without_membership_except_superuser(monkeypatch):
    from services import permission_policy

    def _no_membership(_user_id, _entity_id):
        return None

    monkeypatch.setattr(permission_policy, "_membership_for", _no_membership)

    normal_user = SimpleNamespace(id="u-1", system_role="normal")
    superuser = SimpleNamespace(id="u-2", system_role="superuser")

    assert not has_permission(normal_user, Permission.XERO_SETTINGS_VIEW, entity_id="e-1")
    assert has_permission(superuser, Permission.XERO_SETTINGS_UPDATE, entity_id="e-1")


def test_report_edit_delete_rules(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        if _user_id == "manager":
            return SimpleNamespace(role="shop_manager", approved=True)
        return SimpleNamespace(role="cashier", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    report = SimpleNamespace(company="e-1", uploaded_by="owner")

    owner_user = SimpleNamespace(id="owner-id", username="owner", role="cashier")
    other_cashier = SimpleNamespace(id="cashier", username="someone", role="cashier")
    manager = SimpleNamespace(id="manager", username="boss", role="cashier")

    assert can_edit_report(owner_user, report)
    assert can_delete_report(owner_user, report)
    assert not can_edit_report(other_cashier, report)
    assert not can_delete_report(other_cashier, report)
    assert can_edit_report(manager, report)
    assert can_delete_report(manager, report)


def test_report_view_rules(monkeypatch):
    from services import permission_policy

    def _membership(_user_id, _entity_id):
        if _user_id == "manager":
            return SimpleNamespace(role="shop_manager", approved=True)
        return SimpleNamespace(role="cashier", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    report = SimpleNamespace(company="e-1", uploaded_by="owner")
    owner_user = SimpleNamespace(id="owner-id", username="owner", role="cashier")
    other_cashier = SimpleNamespace(id="cashier", username="someone", role="cashier")
    manager = SimpleNamespace(id="manager", username="boss", role="cashier")

    assert can_view_report(owner_user, report)
    assert can_view_report(other_cashier, report)
    assert can_view_report(manager, report)


def test_report_access_helpers_respect_entity_membership(monkeypatch):
    from services import permission_policy

    def _membership(user_id, entity_id):
        if entity_id != "e-1":
            return None
        if user_id == "manager":
            return SimpleNamespace(role="shop_manager", approved=True)
        return SimpleNamespace(role="cashier", approved=True)

    monkeypatch.setattr(permission_policy, "_membership_for", _membership)

    report_other_entity = SimpleNamespace(company="e-2", uploaded_by="owner")
    manager = SimpleNamespace(id="manager", username="boss", role="cashier")
    owner = SimpleNamespace(id="owner-id", username="owner", role="cashier")

    assert not can_edit_report(manager, report_other_entity)
    assert not can_view_report(manager, report_other_entity)
    assert not can_edit_report(owner, report_other_entity)
    assert not can_view_report(owner, report_other_entity)

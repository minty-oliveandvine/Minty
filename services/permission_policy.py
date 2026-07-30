from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from blueprints.auth.system_roles import (
    SYSTEM_ROLE_SUPERUSER,
    legacy_role_to_system_role as legacy_global_role_to_system_role,
    normalize_system_role as normalize_user_system_role,
)
from models.db import User, UserEntity


class Role(str, Enum):
    ENTITY_BASE = "entity_base"
    CASHIER = "cashier"
    SHOP_MANAGER = "shop_manager"
    ACCOUNTANT = "accountant"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class SystemRole(str, Enum):
    NORMAL = "normal"
    SUPERUSER = "superuser"


class Permission(str, Enum):
    USER_INVITE = "user_invite"
    USER_VIEW_ALL = "user_view_all"
    USER_ROLE_ASSIGN = "user_role_assign"
    USER_ROLE_DELETE = "user_role_delete"
    ENTITY_CREATE = "entity_create"
    ENTITY_VIEW = "entity_view"
    ENTITY_UPDATE = "entity_update"
    ENTITY_RENAME = "entity_rename"
    ENTITY_DELETE = "entity_delete"
    MODULE_VIEW = "module_view"
    MODULE_MANAGE = "module_manage"
    SALES_METHOD_VIEW = "sales_method_view"
    SALES_METHOD_CREATE = "sales_method_create"
    SALES_METHOD_UPDATE = "sales_method_update"
    SALES_METHOD_DELETE = "sales_method_delete"
    SALES_METHOD_REORDER = "sales_method_reorder"
    COA_VIEW = "coa_view"
    COA_CREATE = "coa_create"
    COA_UPDATE = "coa_update"
    COA_DELETE = "coa_delete"
    XERO_SETTINGS_VIEW = "xero_settings_view"
    XERO_SETTINGS_UPDATE = "xero_settings_update"
    REPORT_VIEW_OWN = "report_view_own"
    REPORT_VIEW_ENTITY = "report_view_entity"
    REPORT_EDIT_OWN = "report_edit_own"
    REPORT_EDIT_ENTITY = "report_edit_entity"
    REPORT_DELETE_OWN = "report_delete_own"
    REPORT_DELETE_ENTITY = "report_delete_entity"
    REPORT_PUBLISH = "report_publish"
    CONTACT_CREATE = "contact_create"


ROLE_RANK: dict[str, int] = {
    Role.ENTITY_BASE.value: 0,
    Role.CASHIER.value: 1,
    Role.SHOP_MANAGER.value: 2,
    Role.ACCOUNTANT.value: 3,
    Role.ADMIN.value: 4,
    Role.SUPER_ADMIN.value: 5,
}

ROLE_ALIASES: dict[str, str] = {
    "user": Role.ENTITY_BASE.value,
    "no_role": Role.ENTITY_BASE.value,
    "none": Role.ENTITY_BASE.value,
    "entity base": Role.ENTITY_BASE.value,
    "entity-base": Role.ENTITY_BASE.value,
    "client": Role.CASHIER.value,
    "shop manager": Role.SHOP_MANAGER.value,
    "shop-manager": Role.SHOP_MANAGER.value,
    "super admin": Role.SUPER_ADMIN.value,
    "super-admin": Role.SUPER_ADMIN.value,
}

@dataclass(frozen=True)
class PermissionRule:
    min_role: Role
    entity_scoped: bool = True


PERMISSION_RULES: dict[Permission, PermissionRule] = {
    Permission.USER_INVITE: PermissionRule(Role.SHOP_MANAGER),
    Permission.USER_VIEW_ALL: PermissionRule(Role.SHOP_MANAGER),
    Permission.USER_ROLE_ASSIGN: PermissionRule(Role.SHOP_MANAGER),
    Permission.USER_ROLE_DELETE: PermissionRule(Role.ACCOUNTANT),
    Permission.ENTITY_CREATE: PermissionRule(Role.ENTITY_BASE, entity_scoped=False),
    Permission.ENTITY_VIEW: PermissionRule(Role.CASHIER),
    Permission.ENTITY_UPDATE: PermissionRule(Role.ACCOUNTANT),
    Permission.ENTITY_RENAME: PermissionRule(Role.ADMIN),
    Permission.ENTITY_DELETE: PermissionRule(Role.ADMIN),
    # Seeing which modules an entity subscribes to is read-only information
    # every entity member needs; changing them is admin-only.
    Permission.MODULE_VIEW: PermissionRule(Role.CASHIER),
    Permission.MODULE_MANAGE: PermissionRule(Role.ADMIN),
    Permission.SALES_METHOD_VIEW: PermissionRule(Role.CASHIER),
    Permission.SALES_METHOD_CREATE: PermissionRule(Role.ACCOUNTANT),
    Permission.SALES_METHOD_UPDATE: PermissionRule(Role.ACCOUNTANT),
    Permission.SALES_METHOD_DELETE: PermissionRule(Role.ACCOUNTANT),
    Permission.SALES_METHOD_REORDER: PermissionRule(Role.ACCOUNTANT),
    Permission.COA_VIEW: PermissionRule(Role.CASHIER),
    Permission.COA_CREATE: PermissionRule(Role.ACCOUNTANT),
    Permission.COA_UPDATE: PermissionRule(Role.ACCOUNTANT),
    Permission.COA_DELETE: PermissionRule(Role.ACCOUNTANT),
    Permission.XERO_SETTINGS_VIEW: PermissionRule(Role.CASHIER),
    Permission.XERO_SETTINGS_UPDATE: PermissionRule(Role.ACCOUNTANT),
    Permission.REPORT_VIEW_OWN: PermissionRule(Role.CASHIER),
    Permission.REPORT_VIEW_ENTITY: PermissionRule(Role.CASHIER),
    Permission.REPORT_EDIT_OWN: PermissionRule(Role.CASHIER),
    Permission.REPORT_EDIT_ENTITY: PermissionRule(Role.SHOP_MANAGER),
    Permission.REPORT_DELETE_OWN: PermissionRule(Role.CASHIER),
    Permission.REPORT_DELETE_ENTITY: PermissionRule(Role.SHOP_MANAGER),
    Permission.REPORT_PUBLISH: PermissionRule(Role.ACCOUNTANT),
    Permission.CONTACT_CREATE: PermissionRule(Role.CASHIER),
}


def normalize_role(role: Any) -> str:
    if role is None:
        return Role.ENTITY_BASE.value

    role_text = str(role).strip().lower()
    if role_text in ROLE_ALIASES:
        return ROLE_ALIASES[role_text]
    if role_text in ROLE_RANK:
        return role_text
    return Role.ENTITY_BASE.value


def normalize_system_role(role: Any) -> str:
    return normalize_user_system_role(role)


def legacy_role_to_system_role(role: Any) -> str:
    return legacy_global_role_to_system_role(role)


def is_superuser(user: Any) -> bool:
    if not user:
        return False

    system_role = getattr(user, "system_role", None)
    if system_role is not None:
        return normalize_system_role(system_role) == SYSTEM_ROLE_SUPERUSER

    return legacy_role_to_system_role(getattr(user, "role", None)) == SYSTEM_ROLE_SUPERUSER


# Permissions that a superuser is allowed to use on entities where they have
# no user_entity row. Everything outside this set (any write/create/update/
# delete/publish) is rejected for "readonly superuser" mode.
READONLY_ALLOWED_PERMISSIONS: frozenset["Permission"] = frozenset({
    Permission.USER_VIEW_ALL,
    Permission.ENTITY_VIEW,
    Permission.MODULE_VIEW,
    Permission.SALES_METHOD_VIEW,
    Permission.COA_VIEW,
    Permission.XERO_SETTINGS_VIEW,
    Permission.REPORT_VIEW_OWN,
    Permission.REPORT_VIEW_ENTITY,
})


def is_superuser_readonly(user: Any, entity_id: str | None) -> bool:
    """True when the user is a superuser viewing an entity they have no
    user_entity row on. In this state the user can see/enter the entity
    (granted by is_superuser) but cannot perform any write actions.
    """
    if not is_superuser(user):
        return False
    if not entity_id:
        return False
    return not has_entity_membership(user, entity_id)


def role_at_least(role: str, minimum_role: str) -> bool:
    return ROLE_RANK.get(normalize_role(role), 0) >= ROLE_RANK.get(
        normalize_role(minimum_role), 0
    )


def _membership_for(user_id: str, entity_id: str) -> UserEntity | None:
    return UserEntity.query.filter_by(user_id=user_id, entity_id=entity_id).first()


def has_entity_membership(user: Any, entity_id: str | None) -> bool:
    """Return True if the user has an explicit UserEntity row for this entity.

    Unlike ``has_entity_access`` this does NOT grant superusers automatic
    access — it is a raw membership check used to distinguish between a
    superuser viewing their own entity (full CRUD) vs. a foreign entity
    (read-only).
    """
    if not user or not entity_id or not getattr(user, "id", None):
        return False
    return _membership_for(str(user.id), str(entity_id)) is not None


def has_entity_access(user: Any, entity_id: str | None, require_approved: bool = True) -> bool:
    if not user or not entity_id or not getattr(user, "id", None):
        return False

    if is_superuser(user):
        return True

    membership = _membership_for(str(user.id), str(entity_id))
    if not membership:
        return False

    if require_approved and hasattr(membership, "approved") and not membership.approved:
        return False
    return True


def resolve_effective_role(user: Any, entity_id: str | None = None) -> str:
    if not user:
        return Role.ENTITY_BASE.value

    if is_superuser(user):
        return Role.SUPER_ADMIN.value

    if entity_id and getattr(user, "id", None):
        membership = _membership_for(str(user.id), str(entity_id))
        if membership and getattr(membership, "approved", True):
            return normalize_role(getattr(membership, "role", None))

    return Role.ENTITY_BASE.value


def has_permission(user: Any, permission: Permission, entity_id: str | None = None) -> bool:
    rule = PERMISSION_RULES.get(permission)
    if not rule:
        return False

    if rule.entity_scoped:
        if not entity_id:
            return False
        # Readonly superuser: can use view-only perms on entities they have
        # no membership on; all writes are denied here regardless of rank.
        if is_superuser_readonly(user, entity_id):
            return permission in READONLY_ALLOWED_PERMISSIONS
        effective_role = resolve_effective_role(user, entity_id)
        if effective_role != Role.SUPER_ADMIN.value and not has_entity_access(
            user, entity_id, require_approved=True
        ):
            return False
        return role_at_least(effective_role, rule.min_role.value)

    if permission == Permission.ENTITY_CREATE:
        return bool(user and getattr(user, "id", None))

    effective_role = resolve_effective_role(user, None)
    return role_at_least(effective_role, rule.min_role.value)


def has_permission_by_user_id(
    user_id: str, permission: Permission, entity_id: str | None = None
) -> bool:
    user = User.query.get(user_id)
    if not user:
        return False
    return has_permission(user, permission, entity_id=entity_id)


def can_manage_role_assignment(actor_role: str, target_role: str) -> bool:
    normalized_actor = normalize_role(actor_role)
    normalized_target = normalize_role(target_role)
    if not role_at_least(normalized_actor, Role.SHOP_MANAGER.value):
        return False
    return ROLE_RANK.get(normalized_actor, 0) >= ROLE_RANK.get(normalized_target, 0)


def can_manage_role_assignment_for_entity(
    user: Any, target_role: str, entity_id: str | None
) -> bool:
    if not user:
        return False
    actor_role = resolve_effective_role(user, entity_id)
    return can_manage_role_assignment(actor_role, target_role)


def can_edit_report(user: Any, report: Any) -> bool:
    if not user or not report:
        return False

    entity_id = getattr(report, "company", None)
    if not entity_id:
        return False

    uploaded_by = getattr(report, "uploaded_by", None)
    if (
        uploaded_by
        and uploaded_by == getattr(user, "username", None)
        and has_permission(user, Permission.REPORT_EDIT_OWN, entity_id)
    ):
        return True

    return has_permission(user, Permission.REPORT_EDIT_ENTITY, entity_id)


def can_view_report(user: Any, report: Any) -> bool:
    if not user or not report:
        return False

    entity_id = getattr(report, "company", None)
    if not entity_id:
        return False

    uploaded_by = getattr(report, "uploaded_by", None)
    if (
        uploaded_by
        and uploaded_by == getattr(user, "username", None)
        and has_permission(user, Permission.REPORT_VIEW_OWN, entity_id)
    ):
        return True

    return has_permission(user, Permission.REPORT_VIEW_ENTITY, entity_id)


def can_delete_report(user: Any, report: Any) -> bool:
    if not user or not report:
        return False

    entity_id = getattr(report, "company", None)
    if not entity_id:
        return False

    uploaded_by = getattr(report, "uploaded_by", None)
    if (
        uploaded_by
        and uploaded_by == getattr(user, "username", None)
        and has_permission(user, Permission.REPORT_DELETE_OWN, entity_id)
    ):
        return True

    return has_permission(user, Permission.REPORT_DELETE_ENTITY, entity_id)

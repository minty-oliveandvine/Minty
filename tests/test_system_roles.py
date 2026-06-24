from __future__ import annotations

from blueprints.auth.system_roles import (
    SYSTEM_ROLE_DEFAULT,
    SYSTEM_ROLE_NORMAL,
    SYSTEM_ROLE_SUPERUSER,
    SYSTEM_ROLE_VALUES,
    legacy_role_to_system_role,
    normalize_system_role,
)
from models.db import User


def test_normalize_system_role_limits_values_to_normal_and_superuser():
    assert SYSTEM_ROLE_VALUES == (SYSTEM_ROLE_NORMAL, SYSTEM_ROLE_SUPERUSER)
    assert normalize_system_role(None) == SYSTEM_ROLE_DEFAULT
    assert normalize_system_role("normal") == SYSTEM_ROLE_NORMAL
    assert normalize_system_role(" SUPERUSER ") == SYSTEM_ROLE_SUPERUSER
    assert normalize_system_role("admin") == SYSTEM_ROLE_DEFAULT


def test_legacy_role_mapping_promotes_only_admin_variants_to_superuser():
    assert legacy_role_to_system_role("admin") == SYSTEM_ROLE_SUPERUSER
    assert legacy_role_to_system_role("super_admin") == SYSTEM_ROLE_SUPERUSER
    assert legacy_role_to_system_role("super-admin") == SYSTEM_ROLE_SUPERUSER
    assert legacy_role_to_system_role("Admin") == SYSTEM_ROLE_SUPERUSER
    assert legacy_role_to_system_role("accountant") == SYSTEM_ROLE_NORMAL
    assert legacy_role_to_system_role("user") == SYSTEM_ROLE_NORMAL
    assert legacy_role_to_system_role(None) == SYSTEM_ROLE_NORMAL


def test_user_model_exposes_system_role_contract_helpers():
    assert User.SYSTEM_ROLE_VALUES == SYSTEM_ROLE_VALUES
    assert User.SYSTEM_ROLE_DEFAULT == SYSTEM_ROLE_DEFAULT
    assert User.normalize_system_role("superuser") == SYSTEM_ROLE_SUPERUSER
    assert User.legacy_role_to_system_role("admin") == SYSTEM_ROLE_SUPERUSER

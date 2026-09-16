from __future__ import annotations

from typing import Any, Final

from blueprints.shared.enums import SystemRole

# The words are the database's (``system_role`` enum, docs/schema/01_schema_rebased.sql
# item 18): the global super admin is ``superadmin``. The constant keeps its historical
# name so the ~30 call sites that compare against ``SYSTEM_ROLE_SUPERUSER`` read as before.
SYSTEM_ROLE_NORMAL: Final[str] = SystemRole.NORMAL.value
SYSTEM_ROLE_ADMIN: Final[str] = SystemRole.ADMIN.value
SYSTEM_ROLE_SUPERUSER: Final[str] = SystemRole.SUPERADMIN.value
SYSTEM_ROLE_DEFAULT: Final[str] = SYSTEM_ROLE_NORMAL
SYSTEM_ROLE_VALUES: Final[tuple[str, ...]] = SystemRole.values()

# Pre-split entity ``role`` values once used as the global flag; both mean the super admin.
# ``superuser`` (the code's word for the *system* role until 2026-09) is handled by
# ``normalize_system_role`` - it was never an entity role.
LEGACY_SUPERUSER_ROLES: Final[frozenset[str]] = frozenset({"admin", "super_admin"})


def normalize_system_role(system_role: Any) -> str:
    """The stored value for whatever a caller hands over; unknown words are ``normal``."""
    if system_role is None:
        return SYSTEM_ROLE_DEFAULT

    normalized_role = str(system_role).strip().lower()
    if normalized_role == "superuser":  # pre-2026-09 spelling, e.g. in an old JWT
        return SYSTEM_ROLE_SUPERUSER
    if normalized_role in SYSTEM_ROLE_VALUES:
        return normalized_role
    return SYSTEM_ROLE_DEFAULT


def legacy_role_to_system_role(role: Any) -> str:
    if role is None:
        return SYSTEM_ROLE_DEFAULT

    normalized_role = str(role).strip().lower().replace(" ", "_").replace("-", "_")
    if normalized_role in LEGACY_SUPERUSER_ROLES:
        return SYSTEM_ROLE_SUPERUSER
    return SYSTEM_ROLE_DEFAULT

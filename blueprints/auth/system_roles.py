from __future__ import annotations

from typing import Any, Final

SYSTEM_ROLE_NORMAL: Final[str] = "normal"
SYSTEM_ROLE_SUPERUSER: Final[str] = "superuser"
SYSTEM_ROLE_DEFAULT: Final[str] = SYSTEM_ROLE_NORMAL
SYSTEM_ROLE_VALUES: Final[tuple[str, str]] = (
    SYSTEM_ROLE_NORMAL,
    SYSTEM_ROLE_SUPERUSER,
)

LEGACY_SUPERUSER_ROLES: Final[frozenset[str]] = frozenset({"admin", "super_admin"})


def normalize_system_role(system_role: Any) -> str:
    if system_role is None:
        return SYSTEM_ROLE_DEFAULT

    normalized_role = str(system_role).strip().lower()
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

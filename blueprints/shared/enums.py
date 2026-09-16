"""The database's enums, as the code must write them.

One member per value of the Postgres enum types in ``docs/schema/01_schema_rebased.sql``
(item 18 of its header is the register). Every string the application stores in an enum
column comes from here; a literal like ``"superuser"`` or ``"posted"`` in a route is a bug,
because the column rejects it. billing-backend and onboarding-backend carry the same values
as ``TextChoices``; ``tests/test_enums_match_schema.py`` reads the schema file and fails when
any of the three copies drifts.

Added per phase C unit (docs/modernisation_plan.md): C1 ``SystemRole``, ``EntityRole``; C2 ``EntityStatus``,
``ModuleCode``; C3 ``SaleType``; C4 ``ReportStatus``, ``PublishStatus``, ``DiscrepancyType``,
``CashType``; C5 ``SyncStatus``, ``SyncDirection``; C6 ``InvitationStatus``;
C7 ``SubscriptionPhase``, ``ExtensionState``, ``TransferStatus``, ``AuditOutcome``.
"""

from __future__ import annotations

from enum import Enum, nonmember


class _DbEnum(str, Enum):
    """A str-valued enum: compares equal to its value, so ``user.system_role == "normal"``
    and ``SystemRole.NORMAL`` are the same test, and Jinja prints the bare value.

    Each subclass names its Postgres type as ``pg_name = nonmember("...")`` - ``nonmember``
    because anything else assigned in an Enum body becomes a member.
    """

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(m.value for m in cls)


class SystemRole(_DbEnum):
    """``system_role`` — the global (not per-entity) role of a person.

    ``superadmin`` is what the code used to call ``superuser``; ``admin`` exists in the
    type but nothing in the application grants it yet.
    """

    pg_name = nonmember("system_role")

    NORMAL = "normal"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class EntityRole(_DbEnum):
    """``entity_role`` — a person's role within one company (``user_entity.role``).

    The six-level hierarchy ``services/permission_policy.ROLE_RANK`` ranks; kept as the
    application's own words rather than the redesign's owner/admin/member/viewer.
    """

    pg_name = nonmember("entity_role")

    ENTITY_BASE = "entity_base"
    CASHIER = "cashier"
    SHOP_MANAGER = "shop_manager"
    ACCOUNTANT = "accountant"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class EntityStatus(_DbEnum):
    """``entity_status`` — where a company stands: still in the wizard, or live with /
    without a Xero organisation linked (decided 2026-09-15; the old ``active``,
    ``cancelled`` and ``deleted`` words are gone — a cancelled subscription is a
    subscription state, and nothing links to the soft-delete)."""

    pg_name = nonmember("entity_status")

    ONBOARDING = "onboarding"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


class ModuleCode(_DbEnum):
    """``module_code`` — Minty's two modules (item 20). ``PAYMENT_REQUEST`` was ``BILL``
    in the code; ``billing_plan.code`` keeps the old word by decision, so the plan key
    is mapped (``subscription/services/billing.plan_code``)."""

    pg_name = nonmember("module_code")

    PETTY_CASH = "PETTY_CASH"
    PAYMENT_REQUEST = "PAYMENT_REQUEST"

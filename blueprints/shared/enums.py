"""The database's enums, as the code must write them.

One member per value of the Postgres enum types in ``docs/schema/01_schema_rebased.sql``
(item 18 of its header is the register). Every string the application stores in an enum
column comes from here; a literal like ``"superuser"`` or ``"posted"`` in a route is a bug,
because the column rejects it. billing-backend and onboarding-backend carry the same values
as ``TextChoices``; ``tests/test_enums_match_schema.py`` reads the schema file and fails when
any of the three copies drifts.

Added per phase C unit (docs/modernisation/modernisation_plan.md): C1 ``SystemRole``, ``EntityRole``; C2 ``EntityStatus``,
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


class SaleType(_DbEnum):
    """``sale_type`` — the bucket a sales method belongs to (``sale_info.type``).

    ``other`` replaces the old ``Cash`` word; the Cash method itself is the catalogue row
    whose ``value_name`` is ``cash_sales`` (``SaleInfo.CASH_VALUE_NAME``). The report totals
    key on the bucket, the wizard's sales step lists ``electronic`` and ``delivery``.
    """

    pg_name = nonmember("sale_type")

    ELECTRONIC = "electronic"
    DELIVERY = "delivery"
    OTHER = "other"

    @classmethod
    def normalize(cls, word) -> "SaleType | None":
        """The member for a caller's spelling - the enum's own, or the pre-C3 capitalised
        ``Electronic`` / ``Delivery`` / ``Cash`` the settings page and old JSON still send.
        None for anything else."""
        key = str(word or "").strip().lower()
        if key == "cash":
            return cls.OTHER
        try:
            return cls(key)
        except ValueError:
            return None


class ReportStatus(_DbEnum):
    """``report_status`` — where a day's report stands. ``submitted`` is what the code used to
    call ``posted``; ``published`` is written only when the Xero publish succeeds (schema
    header, report_status derivation). ``partially_published`` no longer exists."""

    pg_name = nonmember("report_status")

    DRAFT = "draft"
    SUBMITTED = "submitted"
    PUBLISHED = "published"
    VOID = "void"


class PublishStatus(_DbEnum):
    """``publish_status`` — the Xero publish job's own state on ``report.publishing_status``
    (``processing`` -> ``publishing``, ``not_published``/NULL -> ``unpublished``)."""

    pg_name = nonmember("publish_status")

    UNPUBLISHED = "unpublished"
    PUBLISHING = "publishing"
    COMPLETED = "completed"
    FAILED = "failed"


class DiscrepancyType(_DbEnum):
    """``discrepancy_type`` — the cash count against the book balance (``shortage`` -> ``short``,
    ``surplus`` -> ``over``)."""

    pg_name = nonmember("discrepancy_type")

    NONE = "none"
    OVER = "over"
    SHORT = "short"

    @classmethod
    def normalize(cls, word) -> "DiscrepancyType":
        key = str(word or "none").strip().lower()
        return {"shortage": cls.SHORT, "surplus": cls.OVER, "": cls.NONE}.get(key) or cls(key)


class InvitationStatus(_DbEnum):
    """``invitation_status`` — a team invite's life. ``revoked`` is what the code called
    ``cancelled`` (the Settings → Users "cancel" button)."""

    pg_name = nonmember("invitation_status")

    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class SubscriptionPhase(_DbEnum):
    """``subscription_phase`` — ``entity_module_subscription.phase`` and the audit log's
    before/after. The words are ``blueprints.subscription.constants.PHASE_*``."""

    pg_name = nonmember("subscription_phase")

    TRIAL = "trial"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    SCHEDULED_CANCEL = "scheduled_cancel"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ExtensionState(_DbEnum):
    """``extension_state`` — the cancel-extension charge. ``deleted`` / ``credited`` /
    ``refunded`` are legacy terminal states nothing produces today; rows still hold them."""

    pg_name = nonmember("extension_state")

    PENDING = "pending"
    INVOICED = "invoiced"
    DELETED = "deleted"
    CREDITED = "credited"
    REFUNDED = "refunded"


class TransferStatus(_DbEnum):
    """``transfer_status`` — a change-of-payer offer (``subscription_transfer.status``)."""

    pg_name = nonmember("transfer_status")

    PENDING = "pending"
    CHARGING = "charging"
    CHARGED = "charged"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class AuditOutcome(_DbEnum):
    """``audit_outcome`` — ``subscription_audit_log.outcome``."""

    pg_name = nonmember("audit_outcome")

    SUCCEEDED = "succeeded"
    ABORTED = "aborted"


class CashType(_DbEnum):
    """``cash_type`` — a denomination is a coin or a note."""

    pg_name = nonmember("cash_type")

    COIN = "coin"
    NOTE = "note"


class ExpenseAttachmentRole(_DbEnum):
    """``expense_attachment_role`` — what a file on an expense line is."""

    pg_name = nonmember("expense_attachment_role")

    RECEIPT = "receipt"
    INVOICE = "invoice"
    OTHER = "other"

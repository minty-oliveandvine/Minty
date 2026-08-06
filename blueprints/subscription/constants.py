"""Shared subscription status vocabulary.

Kept dependency-free (no models / no Stripe imports) so both the live Stripe
layer and the optional cache model can import it without creating an import
cycle through ``models.db``.
"""

# Stripe subscription statuses that grant module access (combined with an
# unexpired grace window at read time).
ACTIVE_STATUSES = ("active", "trialing")

# --- App-tracked lifecycle phases (entity_module_subscription.phase) ----------
PHASE_TRIAL = "trial"
PHASE_ACTIVE = "active"
PHASE_PAST_DUE = "past_due"
PHASE_SCHEDULED_CANCEL = "scheduled_cancel"
PHASE_CANCELLED = "cancelled"
PHASE_EXPIRED = "expired"
SUBSCRIPTION_PHASES = (
    PHASE_TRIAL,
    PHASE_ACTIVE,
    PHASE_PAST_DUE,
    PHASE_SCHEDULED_CANCEL,
    PHASE_CANCELLED,
    PHASE_EXPIRED,
)

# --- Cancel-extension lifecycle (entity_module_subscription.extension_state) ---
# The extension covers the access days AFTER the billing anchor, so it bills ON the
# anchor invoice: a PENDING invoice item that Stripe sweeps onto the payer's next
# invoice. It is only charged up-front when there is no next invoice to ride (the
# payer's last line).
#   pending  -> queued as a pending invoice item; undo = delete it (no money moved)
#   invoiced -> collected (swept onto the anchor invoice, or charged up-front)
#   deleted / credited / refunded -> terminal undo outcomes
EXT_PENDING = "pending"
EXT_INVOICED = "invoiced"
EXT_DELETED = "deleted"
EXT_CREDITED = "credited"
EXT_REFUNDED = "refunded"
EXTENSION_STATES = (
    EXT_PENDING,
    EXT_INVOICED,
    EXT_DELETED,
    EXT_CREDITED,
    EXT_REFUNDED,
)

# --- Audit actions (subscription_audit_log.action) ----------------------------
AUDIT_CANCEL = "cancel"
AUDIT_UNCANCEL = "uncancel"
# The subscription ENDED, as opposed to being cancelled: the days a cancellation bought,
# or the grace a debt was allowed, finally ran out. Nobody clicks this one — it is the
# access sweep recording a date passing (see ``checkout.terminate_lapsed_module``).
AUDIT_TERMINATE = "terminate"

# --- Audit outcomes (subscription_audit_log.outcome) --------------------------
OUTCOME_SUCCEEDED = "succeeded"
OUTCOME_ABORTED = "aborted"

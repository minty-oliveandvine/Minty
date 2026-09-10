"""Minty's own price catalog — what a combination of modules costs, and what it's called.

Until now this lived entirely in Stripe: ``stripe_state.plan_for_module`` and
``bundle_plan`` read live Prices, and the display name existed only as a Stripe Product
name. That makes Stripe load-bearing for arithmetic, not just for collecting money, so
it has to move in-house before billing can.

A plan is keyed by the SET of modules it bills, not by a single module — the bundle is a
combination with its own price and its own name, and has no ``entity_function`` row it
could hang off. ``code`` is that set, upper-cased and sorted, joined with ``+``:

    'BILL'   'PETTY_CASH'   'BILL+PETTY_CASH'

Sorting is what makes the key canonical: {PETTY_CASH, BILL} and {BILL, PETTY_CASH} are
the same plan and must not become two rows.

``display_name`` is deliberately separate from ``entity_function.function_name``. That
one names a module in the app; this one is what a customer reads on an invoice, and the
two are allowed to diverge — "Petty Cash" in the UI, "Petty Cash (Monthly)" on a bill.

NOTE ON HISTORY: rows here describe the price NOW. An invoice already issued must not
change when a price does, so ``billing.Line`` carries amount and name BY VALUE and the
issued invoice keeps its own copy. Never reconstruct a historical invoice by reading this
table.
"""
import uuid

from models.db import db
from blueprints.subscription.models.mixins import TimestampMixin
from blueprints.subscription.models.column_types import uuid_column

# ``plan_code`` — which builds the canonical ``code`` value below — lives in
# ``services.billing`` rather than here. It is pure string canonicalisation with no
# database dependency, and keeping it out of a model module means callers can import it
# without dragging in ``models.db``: doing that from ``store`` pulled the model layer in
# early enough to trip the entity-models circular import.


class BillingPlan(TimestampMixin, db.Model):
    __tablename__ = "billing_plan"
    __table_args__ = {"schema": "pettycashv2"}

    id = db.Column(uuid_column(), primary_key=True, default=lambda: str(uuid.uuid4()))
    # The module SET this plan bills — see ``plan_code``.
    code = db.Column(db.String(200), nullable=False, unique=True, index=True)
    display_name = db.Column(db.String(200), nullable=False)
    # Integer minor units, never a float: 40000 == HKD 400.00.
    amount = db.Column(db.Integer, nullable=False)
    currency = db.Column(
        db.CHAR(3),
        db.ForeignKey("pettycashv2.currency_info.currency_code"),
        nullable=False,
    )
    # Monthly only in practice — the business sells nothing else, and no other interval
    # has been verified. See billing.period_containing.
    interval_months = db.Column(db.Integer, nullable=False, default=1)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    def __repr__(self):
        return f"<BillingPlan {self.code} {self.amount} {self.currency}>"

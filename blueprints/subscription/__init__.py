"""Subscription blueprint.

Minty owns billing. The local tables ARE the source of truth for the plan catalog and
for every entity's subscription and access state; Stripe is the payment rail that
invoices are issued against, nothing more.

* ``user_stripe_customer`` — the billing ACCOUNT: anchor, currency, paid-through, the
  dunning schedule, and the payer's Stripe customer id.
* ``entity_module_subscription`` — phase, access window, trial and cancel-extension
  state per (entity, module).
* ``billing_plan`` — the price catalog, keyed by the SET of module codes.
* ``subscription_audit_log`` — the cancel/renew trail.

Billing is ONE cycle per payer with ONE line per entity (both modules on an entity share
the bundle price). A customer is resolved entity -> payer user -> customer, so one
payer's cycle spans every entity they own — which is why ``entity_id`` travels on the
invoice LINE rather than being inferred from anything Stripe holds.

Its routes are the PAYER PORTAL only -- fifteen bearer-token JSON endpoints under
``/api/me/...``, called cross-origin by the Module 2 frontend and listed in
``routes/portal.py``. (This docstring long said "this blueprint has no routes"; that was
true when the Stripe webhook receiver went with the subscription biller, and stopped
being true when the portal landed.)

The SESSION-cookie surface is elsewhere: the customer-facing actions a signed-in admin
takes -- checkout, trial, billing portal, module toggle -- hang off the entity settings
routes and call into ``blueprints.subscription.services``.
"""
from flask import Blueprint

subscription_bp = Blueprint("subscription", __name__)

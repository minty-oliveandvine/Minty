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

This blueprint has no routes. The Stripe webhook receiver lived here and went with the
subscription biller. The customer-facing actions (checkout, trial, billing portal,
module toggle) hang off the entity settings routes and call into
``blueprints.subscription.services``.
"""
from flask import Blueprint

subscription_bp = Blueprint("subscription", __name__)

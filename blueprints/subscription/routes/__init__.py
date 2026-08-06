# The Stripe webhook receiver used to live here. It is gone with the subscription
# biller: every handler existed to mirror Stripe's own subscription state back into
# ``entity_module_subscription``, and Minty now owns that state outright.
#
# What lives here now is the PAYER PORTAL API — the one subscription route that is not
# entity-scoped, because its subject is every entity a payer owns. See portal.py.
#
# Imported for the side effect of registering the route on ``subscription_bp``; the
# blueprint loader imports this package before registering the blueprint.
from blueprints.subscription.routes import portal  # noqa: F401

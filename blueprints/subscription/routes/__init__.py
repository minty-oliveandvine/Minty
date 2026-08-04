# No routes.
#
# The Stripe webhook receiver used to live here. It is gone with the subscription
# biller: every handler existed to mirror Stripe's own subscription state back into
# ``entity_module_subscription``, and Minty now owns that state outright. The blueprint
# itself is kept so its registration stays valid and a future subscription-owned route
# has somewhere to go.

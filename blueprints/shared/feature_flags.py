"""Feature switches read from the environment.

``SUBSCRIPTION_ENABLED`` — the subscription feature as a whole: plans, trials, checkout,
the payer portal, the notices, the daily pass. **Off unless set**, like the scheduler's own
switch: production cut over to the redesigned schema with subscriptions dark
(``docs/modernisation/modernisation_plan.md``, Phase E), because no company held a
subscription row and nothing was lost by keeping the feature out of sight until launch.

Dark means:

* module access is what ``entity_function_map.is_enabled`` says, as it was before the
  engine existed; onboarding sets it at step 2 and an entity admin can flip it on the
  module settings page (``entity_settings_module_toggle``);
* every route that would quote, charge, capture a card or read Stripe answers 404;
* the module page lists the modules and nothing else; no notice, no popup, no panel;
* finalize enables the chosen modules and starts nothing; ``/plans`` is empty;
* the scheduler does not start whatever ``SUBSCRIPTION_SCHEDULER_ENABLED`` says.

Flipping it on writes nothing: no grant, no trial, no revocation. What was on stays on
and what was off stays off; taking access away from a module that never had a
subscription behind it is a separate, deliberate command (``flask subscriptions
revoke-ungranted``), never a side effect of the switch.
"""

from __future__ import annotations

import os
from functools import wraps

from flask import abort

_TRUE = {"1", "true", "yes", "on"}


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE


def subscriptions_enabled() -> bool:
    """Whether the subscription feature is live. Read on every call: cheap, and a test can
    flip the environment without rebuilding the app."""
    return _flag("SUBSCRIPTION_ENABLED", False)


def minty_web_module_page() -> bool:
    """Whether the LIVE module settings page is minty-web's (Part 2 step 4a) rather than
    the Jinja one. On by default: the Jinja page is what the dark switch keeps, and the
    redesigned page lives in the hub. ``MINTY_WEB_MODULE_PAGE=0`` keeps the Jinja page for a
    developer running Flask alone; the test suite sets it so the Jinja tests still describe
    what they exercise. Gone at step 5 with the Jinja page itself."""
    return _flag("MINTY_WEB_MODULE_PAGE", True)


def minty_web_hub() -> bool:
    """Whether the entity list and My Profile are minty-web's pages rather than the Jinja list
    and billing-frontend's profile. With it on, ``/entity`` and every "open my profile" link go
    to minty-web (its ``/entities`` and ``/profile``); with it off everything is as it was.

    **Off unless set**, unlike ``MINTY_WEB_MODULE_PAGE``: that one fires only while
    subscriptions are live, but ``/entity`` is the first page after every login, so switching
    this on in an environment where minty-web is not deployed would strand every sign-in.
    Turn it on per environment once minty-web answers there."""
    return _flag("MINTY_WEB_HUB", False)


def require_subscriptions_enabled(view):
    """A route that exists only while subscriptions are live: 404 when they are dark.

    404, not 403: a dark feature has no routes, and an address that answers "forbidden"
    tells a caller there is something there to be allowed into.
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not subscriptions_enabled():
            abort(404)
        return view(*args, **kwargs)

    return wrapped

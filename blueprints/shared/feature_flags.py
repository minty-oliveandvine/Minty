"""Feature switches read from the environment.

Subscriptions have no switch any more: the dark switch (``SUBSCRIPTION_ENABLED``) was removed
on 2026-10-01, once the stack was deployed to a test site, and the feature is simply on. Its
rule outlives it: turning the feature on wrote nothing (no grant, no trial, no revocation), and
taking access away from a module with no subscription behind it is still the separate,
deliberate ``flask subscriptions revoke-ungranted``. The daily pass keeps its own switch,
``SUBSCRIPTION_SCHEDULER_ENABLED`` (``services/app_runtime/scheduler.py``).
"""

from __future__ import annotations

from services.app_runtime.env import flag


def minty_web_hub() -> bool:
    """Whether the entity list is minty-web's page rather than the Jinja list. With it on,
    ``/entity`` goes to minty-web's ``/entities``; with it off the Jinja list stays. (My
    Profile is minty-web's either way since 2026-10-01, when billing-frontend's profile page
    was deleted - see ``entity.open_profile``.)

    **Off unless set**: ``/entity`` is the first page after every login, so switching this on
    in an environment where minty-web is not deployed would strand every sign-in. Turn it on
    per environment once minty-web answers there."""
    return flag("MINTY_WEB_HUB", False)

"""Only the payer may change what an entity is billed for.

``Permission.MODULE_MANAGE`` says who may administer an entity. It does not say whose
card is on the line, and every subscription action spends or commits ONE person's money:
cancel queues an extension charge, start-trial creates something that converts to paid,
Pay now takes a payment, checkout buys. A co-admin could trigger any of them against a
card belonging to someone who never saw the screen.

``upsert_module_row`` already enforced one payer per entity — but that kept the BILLING
coherent, not the permissions. It quietly ignored the second admin's payer id and charged
the first one anyway.

Two halves, and the second is the one that matters:

  * the page hides the actions for anyone who is not the payer;
  * every route refuses them, because hiding a button is not a permission.

An entity with NO payer is open to any admin — starting the first trial or subscription
is precisely what establishes the payer.
"""
from __future__ import annotations

import re

SETTINGS = r"C:\Github\Minty\blueprints\entity\routes\settings.py"

# Every module-subscription route that spends or commits money, or opens the portal that
# can. If you add one, add it here — this list is the point of the structural test.
MONEY_ROUTES = [
    "checkout",
    "authorize-billing",
    "confirm-billing",
    "start-trial",
    "cancel-preview",
    "retry-payment",
    "cancel",
    "payment-method",
    "renew",
    "manage-billing",
    # The lapsed-trial restart screen. The four card routes do not name an entity in
    # what they act on, but they are money-adjacent and carry the same guard stack, so
    # they belong here: without the payer check a co-admin could nominate the card the
    # restart is about to charge.
    "payment-methods",
    "payment-methods/setup-intent",
    "payment-methods/confirm",
    "payment-methods/default",
    "restart-quote",
    "restart-billing",
]


def test_the_payer_may_manage(app, monkeypatch):
    from blueprints.subscription.services import store

    monkeypatch.setattr(store, "payer_for_entity", lambda eid: "u1")

    with app.app_context():
        assert store.may_manage_subscription("e1", "u1") is True


def test_another_admin_may_not(app, monkeypatch):
    """The case this exists for: a second admin on someone else's billing relationship."""
    from blueprints.subscription.services import store

    monkeypatch.setattr(store, "payer_for_entity", lambda eid: "u1")

    with app.app_context():
        assert store.may_manage_subscription("e1", "u2") is False


def test_an_entity_with_no_payer_is_open_to_any_admin(app, monkeypatch):
    """Nobody is being billed yet, and starting the first trial is what MAKES the payer.
    Refusing here would leave an entity that no one could ever subscribe."""
    from blueprints.subscription.services import store

    monkeypatch.setattr(store, "payer_for_entity", lambda eid: None)

    with app.app_context():
        assert store.may_manage_subscription("e1", "anyone") is True


def test_ids_are_compared_as_strings(app, monkeypatch):
    """Payer ids come back as UUID objects from some drivers and strings from others; a
    mismatch there would lock the payer out of their own subscription."""
    import uuid

    from blueprints.subscription.services import store

    uid = uuid.uuid4()
    monkeypatch.setattr(store, "payer_for_entity", lambda eid: uid)

    with app.app_context():
        assert store.may_manage_subscription("e1", str(uid)) is True


def test_missing_arguments_deny(app, monkeypatch):
    from blueprints.subscription.services import store

    with app.app_context():
        assert store.may_manage_subscription(None, "u1") is False
        assert store.may_manage_subscription("e1", None) is False


# --- the routes ----------------------------------------------------------------


def _decorators_for(src: str, path_segment: str) -> str:
    """The decorator block between a route's @entity_bp.route(...) and its def."""
    m = re.search(
        r'@entity_bp\.route\(\s*\n?\s*"/entity/settings/module/<string:org_id>/'
        + re.escape(path_segment)
        + r'".*?\ndef ',
        src,
        re.S,
    )
    assert m, f"route {path_segment} not found"
    return m.group(0)


def test_every_money_route_requires_the_payer():
    """Hiding the buttons is presentation. This is the permission.

    Asserted structurally rather than by calling each route: the guard is a decorator,
    and a route that simply forgot it would pass any behavioural test written against the
    payer's own session.
    """
    src = open(SETTINGS, encoding="utf-8").read()

    missing = [
        seg for seg in MONEY_ROUTES
        if "require_subscription_payer" not in _decorators_for(src, seg)
    ]
    assert missing == [], f"unguarded money routes: {missing}"


def test_the_money_routes_also_still_require_the_permission():
    """Being the payer is necessary, not sufficient — an entity admin who stops being an
    admin must not keep the buttons because they happen to hold the card."""
    src = open(SETTINGS, encoding="utf-8").read()

    missing = [
        seg for seg in MONEY_ROUTES
        if "require_permission" not in _decorators_for(src, seg)
    ]
    assert missing == [], f"routes missing the permission guard: {missing}"


def test_the_stripe_return_leg_is_not_payer_guarded():
    """checkout-complete is the GET Stripe redirects back to. Refusing it would strand a
    payment that has ALREADY happened, leaving the customer charged and unentitled."""
    src = open(SETTINGS, encoding="utf-8").read()

    assert "require_subscription_payer" not in _decorators_for(src, "checkout-complete")

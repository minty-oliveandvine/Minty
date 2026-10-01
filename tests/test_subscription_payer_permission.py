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

The routes half (``@require_subscription_payer`` on every money route) is pinned in
minty-billing-api now: Flask's session routes went with its Jinja module page on 2026-10-01,
and ``store.may_manage_subscription`` below is the rule they shared.

An entity with NO payer is open to any admin — starting the first trial or subscription
is precisely what establishes the payer.
"""
from __future__ import annotations

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

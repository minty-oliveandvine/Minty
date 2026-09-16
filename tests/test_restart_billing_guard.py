"""The restart route takes money, so its refusals are the load-bearing part.

Four things stand between a POST and a charge, and the ORDER matters as much as the
checks:

1. the entity must genuinely have a lapsed trial (409) — without it this URL charges a
   company that is running perfectly well;
2. the codes must be ones that actually lapsed (422) — the list arrives from the browser;
3. the card is nominated BEFORE the charge (402 when there is none) — charging while the
   account still points at a different card bills one the payer was never shown;
4. only then the subscribe, priced server-side.

The guard STACK (login / entity access / MODULE_MANAGE / payer) is covered structurally
by ``test_subscription_payer_permission.py``, which is how this codebase checks these
routes — no test here re-proves it.
"""
from __future__ import annotations

import re

import pytest

SETTINGS = "blueprints/entity/routes/settings.py"


class _User:
    id = "u1"


@pytest.fixture
def as_payer(app, monkeypatch):
    """A request context with a signed-in payer, so the helper can read current_user."""
    import blueprints.entity.routes.settings as settings_mod

    monkeypatch.setattr(settings_mod, "current_user", _User())
    with app.test_request_context():
        yield settings_mod


def _lapsed(mode="takeover", codes=("PETTY_CASH",)):
    return {
        "mode": mode,
        "lapsed": [{"code": c, "name": c.title(), "lapsed_on": None} for c in codes],
        "payer_user_id": "u1",
        "has_card": True,
        "has_consent": False,
    }


# --- 1. nothing to restart ----------------------------------------------------


def test_an_entity_with_no_lapse_is_refused(as_payer, monkeypatch):
    """The check that stops this URL charging a company that is running fine."""
    monkeypatch.setattr(
        "blueprints.subscription.services.consent.lapsed_trial_for_entity",
        lambda eid, uid=None, **kw: {"mode": None, "lapsed": []},
    )

    _state, codes, error = as_payer._restart_state_and_codes("e1", ["PETTY_CASH"])

    assert codes == []
    assert error is not None and error[1] == 409


@pytest.mark.parametrize("mode", ["takeover", "panel"])
def test_both_modes_may_restart(as_payer, monkeypatch, mode):
    """The panel's button posts to the same route — a part-lapsed entity has just as
    much right to buy its module back as a fully lapsed one."""
    monkeypatch.setattr(
        "blueprints.subscription.services.consent.lapsed_trial_for_entity",
        lambda eid, uid=None, **kw: _lapsed(mode),
    )

    _state, codes, error = as_payer._restart_state_and_codes("e1", ["PETTY_CASH"])

    assert error is None
    assert codes == ["PETTY_CASH"]


# --- 2. what may be charged for -----------------------------------------------


@pytest.mark.parametrize(
    "requested",
    [
        [],                          # nothing ticked
        ["PAYMENT_REQUEST"],                    # did not lapse
        ["PETTY_CASH", "PAYMENT_REQUEST"],      # one good, one not — refused whole
        ["NOT_A_MODULE"],            # not a module at all
    ],
)
def test_a_set_that_cannot_be_honoured_is_refused(as_payer, monkeypatch, requested):
    """Refused OUTRIGHT rather than filtered down: silently dropping the bad code would
    charge for a different set than the payer submitted."""
    monkeypatch.setattr(
        "blueprints.subscription.services.consent.lapsed_trial_for_entity",
        lambda eid, uid=None, **kw: _lapsed(codes=("PETTY_CASH",)),
    )

    _state, codes, error = as_payer._restart_state_and_codes("e1", requested)

    assert codes == []
    assert error is not None and error[1] == 422


def test_picking_one_of_two_lapsed_modules_is_allowed(as_payer, monkeypatch):
    """Forcing the bundle would sell a module the customer may have let go on purpose."""
    monkeypatch.setattr(
        "blueprints.subscription.services.consent.lapsed_trial_for_entity",
        lambda eid, uid=None, **kw: _lapsed(codes=("PETTY_CASH", "PAYMENT_REQUEST")),
    )

    _state, codes, error = as_payer._restart_state_and_codes("e1", ["PAYMENT_REQUEST"])

    assert error is None
    assert codes == ["PAYMENT_REQUEST"]


# --- 3 and 4. the order money happens in --------------------------------------


def _restart_source() -> str:
    """The route's EXECUTABLE body — docstring and imports stripped.

    Both are stripped deliberately: the docstring describes the ordering this file
    asserts, and the import line names ``confirm_modules_checkout`` well before the call
    to it. Searching the raw text would match prose and imports and prove nothing about
    what actually runs.
    """
    src = open(SETTINGS, encoding="utf-8").read()
    start = src.index("def entity_settings_module_restart_billing(")
    end = src.index("def _entity_has_card(", start)
    body = src[start:end]
    body = body[body.index('"""', body.index('"""') + 3) + 3:]
    return "\n".join(
        line for line in body.split("\n")
        if not line.strip().startswith(("from ", "import ", "#"))
        and "CheckoutError," not in line
        and line.strip() not in ("confirm_modules_checkout)",)
    )


def test_the_card_is_nominated_before_anything_is_charged():
    """Recording a charge while the company still points at a different card would bill
    one the payer was never shown. Asserted on ORDER, because both calls being present
    says nothing about which ran first."""
    body = _restart_source()

    assert body.index("set_for_entity") < body.index("confirm_modules_checkout")


def test_a_payer_with_no_card_is_refused_before_the_charge():
    body = _restart_source()

    assert "402" in body
    assert body.index("402") < body.index("confirm_modules_checkout")


def test_the_codes_are_resolved_before_the_card_is_touched():
    """A bad set must not leave a re-pointed company behind as a side effect."""
    body = _restart_source()

    assert body.index("_restart_state_and_codes") < body.index("set_for_entity")


def test_the_charge_is_priced_from_the_resolved_codes():
    """Never from an amount in the request — the browser sends a selection, not a price."""
    body = _restart_source()

    assert "requested_codes=codes" in body
    # The only things read off the request are the selection and the card id. An amount
    # taken from the body would be a price the payer could edit.
    reads = [line for line in body.split("\n") if "body.get(" in line]
    assert reads, "the route does read its body"
    assert all(("codes" in line or "payment_method" in line) for line in reads), reads


def test_the_quote_route_resolves_codes_the_same_way():
    """If the quote and the charge resolved the set differently, the payer would be
    shown one number and billed against another."""
    src = open(SETTINGS, encoding="utf-8").read()
    quote = src[
        src.index("def entity_settings_module_restart_quote(") :
        src.index("def entity_settings_module_restart_billing(")
    ]

    assert "_restart_state_and_codes" in quote
    # And it must not be able to charge.
    assert "confirm_modules_checkout" not in quote


def test_the_restart_route_records_no_new_consent_site():
    """Consent lands through ``confirm_modules_checkout``, the same function every other
    paid purchase writes it from. A direct ``record_billing_consent`` here would be a
    fifth write site with none of that path's disclosure in front of it."""
    body = _restart_source()

    assert "record_billing_consent" not in body
    assert "authorize_entity_billing" not in body


def test_authorize_billing_is_left_alone():
    """Write site 1 still serves onboarding's Buy-now and the trial decision modal. A
    window check bolted onto it would break both."""
    src = open(SETTINGS, encoding="utf-8").read()
    body = src[
        src.index("def entity_settings_module_authorize_billing(") :
        src.index("# --- The lapsed-trial restart screen")
    ]

    assert "lapsed_trial_for_entity" not in body
    assert re.search(r"authorize_entity_billing\(org, current_user\)", body)

"""The payer portal API — Module 2's "Manage subscriptions" screen.

One endpoint, and it is the FIRST subscription route that is not entity-scoped. Every
other money route hangs off ``/entity/<id>/...`` and is gated by
``@require_subscription_payer``: pick a company, prove you pay for it, then act. That
decorator cannot serve this screen — there is no entity in the path to check against,
because the screen's whole subject is "all of them".

So the gate here is different in shape and stricter in effect. The token identifies a
USER; the query filters on ``payer_user_id``; and the result is, by construction, only
what that user pays for. There is no id in the request that could be swapped for
somebody else's, which is a stronger guarantee than checking one — this endpoint cannot
be pointed at another payer's companies at all.

Auth mirrors ``entity.routes.modules.subscription_notice_api``: the billing JWT Module 2
already holds, signed with this app's ``SECRET_KEY``. Two differences, both deliberate:

* the token's ``entity_id`` claim is IGNORED. Profile is reached with an unscoped token
  (``billing_app_profile_unscoped_url`` mints one with no entity), and this screen spans
  entities anyway, so requiring a claim would lock out the exact path the design uses.
* it is READ-ONLY and stays that way. Cancelling and subscribing remain on the entity
  settings page behind the payer decorator; this is the index, not a second till.
"""

from __future__ import annotations

import os

import jwt
from flask import current_app, jsonify, make_response, request

from blueprints.subscription import subscription_bp


def _frontend_origin() -> str:
    return os.environ.get("FRONTEND_APP_URL", "http://localhost:3000").rstrip("/")


def _cors(resp):
    """Allow the Module 2 frontend to call this cross-origin (bearer-token auth).

    Names the origin rather than leaning on the global flask-cors install, and pins
    ``Vary: Origin`` so a response cached for one origin is never replayed to another.
    Same contract as ``_notice_cors``.
    """
    resp.headers["Access-Control-Allow-Origin"] = _frontend_origin()
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    return resp


def _unauthorized(reason: str, status: int = 401):
    return _cors(make_response(jsonify({"error": reason}), status))


def _user_id_from_bearer() -> str | None:
    """The ``user_id`` claim of a valid billing JWT, or None."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        decoded = jwt.decode(
            header[len("Bearer "):].strip(),
            current_app.config.get("SECRET_KEY"),
            algorithms=["HS256"],
        )
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, jwt.DecodeError):
        return None
    user_id = decoded.get("user_id")
    return str(user_id) if user_id else None


def _int_arg(name: str, default: int) -> int:
    """A positive integer query arg. Junk falls back to the default rather than 400ing —
    paging is navigation, and a mangled ``?page=`` should show page one, not an error."""
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


@subscription_bp.route("/api/me/subscriptions", methods=["GET", "OPTIONS"])
def my_subscriptions_api():
    """Every entity the caller PAYS FOR, with each module's status and next date.

    Query params, all optional:
      ``q``          free-text over entity name, subscriber, country, module and status
      ``sort``       one of ``portal.SORT_FIELDS`` (default ``entity``)
      ``direction``  ``asc`` / ``desc``
      ``page``       1-based
      ``per_page``   clamped to ``portal.MAX_PER_PAGE``

    An unknown sort field falls back to entity name rather than erroring: this drives a
    column header, and an unrecognised one means the client is newer than the server,
    which should degrade to a sensible order and not a broken table.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        return _unauthorized("unauthorized")

    from models.db import User

    user = User.query.get(user_id)
    if user is None:
        return _unauthorized("no_user_claim", 403)

    from blueprints.subscription.services import portal

    try:
        payload = portal.build_payer_subscriptions(
            user_id,
            query=request.args.get("q", ""),
            sort=request.args.get("sort", "entity"),
            direction=request.args.get("direction", "asc"),
            page=_int_arg("page", 1),
            per_page=_int_arg("per_page", portal.DEFAULT_PER_PAGE),
        )
    except Exception:
        # Unlike the notice endpoint there is no useful empty answer here — an empty
        # table reads as "you pay for nothing", which is a worse lie than an error the
        # page can retry from.
        current_app.logger.exception(
            "payer subscriptions API failed for user %s", user_id
        )
        return _cors(
            make_response(
                jsonify({"error": "Could not load your subscriptions."}), 500
            )
        )

    return _cors(make_response(jsonify(payload), 200))


@subscription_bp.route(
    "/api/me/subscriptions/subscriber-options", methods=["GET", "OPTIONS"]
)
def my_subscriber_options_api():
    """Who one entity's bill could be handed to — its admins, and who holds it now.

    ``entity`` is REQUIRED, and it is the first id the payer portal accepts that is not
    a filter over an already-payer-scoped set. So it is checked rather than trusted: the
    read model answers None unless the caller is the payer for that entity, and this
    returns 404 for it. Not 403 — "you are not the payer for this company" and "no such
    company" are the same answer to someone who should not be asking, and telling the two
    apart would confirm an id.

    READ ONLY, and the screen it feeds is too. Moving an entity to a different payer
    changes whose card renews it, and the write needs a proration story and an audit
    entry that do not exist yet.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        return _unauthorized("unauthorized")

    entity_id = (request.args.get("entity") or "").strip()
    if not entity_id:
        return _cors(make_response(jsonify({"error": "entity is required"}), 400))

    from blueprints.subscription.services import portal

    try:
        payload = portal.build_subscriber_options(user_id, entity_id)
    except Exception:
        current_app.logger.exception(
            "subscriber options API failed for user %s entity %s", user_id, entity_id
        )
        return _cors(
            make_response(jsonify({"error": "Could not load the subscribers."}), 500)
        )

    if payload is None:
        return _cors(
            make_response(
                jsonify({"error": "That company isn't on your billing account."}), 404
            )
        )

    return _cors(make_response(jsonify(payload), 200))


@subscription_bp.route(
    "/api/me/subscriptions/invite-admin", methods=["POST", "OPTIONS"]
)
def my_invite_admin_api():
    """Invite someone into an entity as an admin. Body: ``{"entity": id, "email": …}``.

    The ONLY write the payer portal performs against Minty's own tables, and it is
    deliberately the smallest one on this screen: it adds a MEMBER, it does not move a
    payer. Handing the bill over is a separate flow that has to survive the period already
    paid for, and it is still switched off.

    ``entity`` is checked, not trusted — ``invite_admin_to_entity`` refuses unless the
    caller is that entity's payer AND holds ``USER_INVITE`` on it, and answers the same
    message for "not your company" as for "no such company".
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        return _unauthorized("unauthorized")

    payload = request.get_json(silent=True) or {}
    entity_id = str(payload.get("entity") or "").strip()
    email = str(payload.get("email") or "").strip()
    if not entity_id:
        return _cors(make_response(jsonify({"error": "entity is required"}), 400))

    from blueprints.subscription.services import portal

    try:
        ok, message = portal.invite_admin_to_entity(user_id, entity_id, email)
    except Exception:
        current_app.logger.exception(
            "invite-admin failed for user %s entity %s", user_id, entity_id
        )
        return _cors(
            make_response(jsonify({"error": "Could not send that invitation."}), 500)
        )

    if not ok:
        # 422: the request was understood and refused for a stated reason the form shows
        # against the field — already a member, already invited, not an address.
        return _cors(make_response(jsonify({"error": message}), 422))
    return _cors(make_response(jsonify({"ok": True, "message": message}), 200))


def _transfer_call(handler, *, description: str):
    """The shared shell for the four handover routes.

    Every one of them answers the same way, and writing that four times is how the
    answers drift: preflight without a token, 401 without a bearer, 400 only for a
    missing routing id, **422 with a full sentence** for any business refusal, 500 for a
    surprise — and every response, errors included, back through ``_cors``.

    422 rather than 403 matters here. The service's refusals are sentences meant to be
    read by the person who clicked ("that person needs a saved payment method"), and the
    client only shows the server's words when they look like prose.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        return _unauthorized("unauthorized")

    payload = request.get_json(silent=True) or {}
    try:
        result = handler(user_id, payload)
    except _MissingField as exc:
        return _cors(make_response(jsonify({"error": str(exc)}), 400))
    except Exception:
        current_app.logger.exception("%s failed for user %s", description, user_id)
        return _cors(
            make_response(jsonify({"error": "Something got stuck on my end!"}), 500)
        )

    ok, message, data = result
    if not ok:
        return _cors(make_response(jsonify({"error": message}), 422))
    body = {"ok": True, "message": message}
    if data is not None:
        body["transfer"] = data
    return _cors(make_response(jsonify(body), 200))


class _MissingField(Exception):
    """A required routing id was absent — a 400, distinct from a stated refusal."""


def _required(payload: dict, field: str) -> str:
    value = str(payload.get(field) or "").strip()
    if not value:
        raise _MissingField(f"{field} is required")
    return value


@subscription_bp.route(
    "/api/me/subscriptions/transfer", methods=["POST", "OPTIONS"]
)
def my_transfer_initiate_api():
    """Offer this entity's subscription to another admin. Body: ``{entity, to_user}``.

    Authorised inside the service, not here: ``transfer_blockers`` refuses unless the
    caller is that entity's payer, which is the same test that gates every other change
    to a subscription.
    """
    from blueprints.subscription.services import transfers

    return _transfer_call(
        lambda user_id, payload: transfers.offer_transfer(
            user_id, _required(payload, "entity"), _required(payload, "to_user")
        ),
        description="transfer initiate",
    )


@subscription_bp.route(
    "/api/me/subscriptions/transfer/respond", methods=["POST", "OPTIONS"]
)
def my_transfer_respond_api():
    """Accept or decline a handover offered to you. Body: ``{transfer, accept}``.

    THE ONE ROUTE HERE THAT MOVES MONEY. It is also re-entrant: called twice it adopts
    the invoice already paid under the offer's key rather than raising a second one, so a
    double-click or a retry after a timeout costs nothing.
    """
    from blueprints.subscription.services import transfers

    return _transfer_call(
        lambda user_id, payload: transfers.respond_to_transfer(
            user_id,
            _required(payload, "transfer"),
            accept=bool(payload.get("accept")),
        ),
        description="transfer respond",
    )


@subscription_bp.route(
    "/api/me/subscriptions/transfer/cancel", methods=["POST", "OPTIONS"]
)
def my_transfer_cancel_api():
    """Withdraw an offer you made. Body: ``{transfer}``.

    The initiator's escape hatch. Without it their own exit from a company depends
    indefinitely on somebody else opening their email.
    """
    from blueprints.subscription.services import transfers

    return _transfer_call(
        lambda user_id, payload: (
            *transfers.cancel_transfer(user_id, _required(payload, "transfer")),
            None,
        ),
        description="transfer cancel",
    )


@subscription_bp.route("/api/me/subscriptions/transfers", methods=["GET", "OPTIONS"])
def my_transfers_api():
    """Handovers offered TO the caller.

    A NEW AUTHORISATION SHAPE for this file, and worth saying out loud: every other
    portal read filters on ``payer_user_id`` and is safe by construction because it can
    only ever return the caller's own companies. This one deliberately returns companies
    they do NOT pay for — that is the entire point — so it is scoped on ``to_user_id``
    from the token instead. Still nothing in the request can be swapped for someone
    else's offers, which is the property that matters.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        return _unauthorized("unauthorized")

    from blueprints.subscription.services import transfers

    try:
        payload = transfers.incoming_transfers_payload(user_id)
    except Exception:
        current_app.logger.exception("incoming transfers failed for user %s", user_id)
        return _cors(
            make_response(jsonify({"error": "Could not load those requests."}), 500)
        )
    return _cors(make_response(jsonify({"transfers": payload}), 200))


@subscription_bp.route("/api/me/invoices", methods=["GET", "OPTIONS"])
def my_invoices_api():
    """The caller's invoices, newest first.

    Query params: ``entity`` (narrow to one company), ``page``, ``per_page``.

    ``entity`` is a filter, not a permission: the set is already fixed to
    ``payer_user_id`` from the token, so an id the caller does not pay for matches
    nothing rather than reaching anything.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        return _unauthorized("unauthorized")

    from blueprints.subscription.services import portal

    try:
        payload = portal.build_payer_invoices(
            user_id,
            entity_id=(request.args.get("entity") or "").strip() or None,
            page=_int_arg("page", 1),
            per_page=_int_arg("per_page", 10),
        )
    except Exception:
        current_app.logger.exception("payer invoices API failed for user %s", user_id)
        return _cors(
            make_response(jsonify({"error": "Could not load your invoices."}), 500)
        )

    return _cors(make_response(jsonify(payload), 200))


# --- Saved payment methods ---------------------------------------------------
#
# The in-app wallet behind the billing account page. It replaced a hand-off to Stripe's
# hosted payment-method form — one POST that answered with a portal URL for the browser to
# leave for. That route is gone; the entity settings page still reaches the hosted portal
# through ``checkout.open_payment_method_update``, which is a different surface.
#
# What is NOT moved in-app is the card itself. Every one of these carries ids and display
# fields only — the number is typed into Stripe Elements and confirmed straight against a
# SetupIntent, so no PAN reaches this process (see ``services.payment_methods``).
#
# Same gate as the rest of the portal, with one difference that matters: four of them take
# a ``pm_…`` id FROM THE REQUEST, which is the first thing in this file that can be
# pointed somewhere. ``payment_methods._owned`` is what closes that — the method's customer
# is compared against the customer resolved from the TOKEN's user, and somebody else's id
# answers "not found" rather than being acted on.
#
# All POST, including the ones that read as DELETE or PATCH. ``_cors`` advertises GET,
# POST and OPTIONS, and a preflight for a method the header does not name is refused by
# the browser before the route is ever reached.


def _payment_methods_call(handler):
    """Run one payment-method action for the bearer's own account.

    Every endpoint below has the same shape — authenticate, act, answer the fresh list.
    Only the AUTH and the CORS wrapper are this transport's own; the three shared failure
    modes live in ``payment_methods.run``, which the onboarding twins and the settings
    page's session routes call too.
    """
    from blueprints.subscription.services import payment_methods

    user_id = _user_id_from_bearer()
    if not user_id:
        return _unauthorized("unauthorized")

    from models.db import User

    if User.query.get(user_id) is None:
        return _unauthorized("no_user_claim", 403)

    payload, status = payment_methods.run(handler, user_id)
    return _cors(make_response(jsonify(payload), status))


def _pm_id() -> str:
    return str((request.get_json(silent=True) or {}).get("payment_method") or "").strip()


@subscription_bp.route("/api/me/billing/payment-methods", methods=["GET", "OPTIONS"])
def my_payment_methods_api():
    """Every payment method saved on the caller's billing account, default first.

    ``has_account`` false is not an empty wallet: the payer has no Stripe customer at all,
    which is the ordinary state of an account whose trials never captured a card. The page
    shows "Add payment method" and nothing else there.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    from blueprints.subscription.services import payment_methods

    return _payment_methods_call(payment_methods.list_for_user)


@subscription_bp.route(
    "/api/me/billing/payment-methods/setup-intent", methods=["POST", "OPTIONS"]
)
def my_payment_method_setup_intent_api():
    """Open a SetupIntent for the in-app card form.

    Answers ``{client_secret, publishable_key, setup_intent}`` — what Stripe Elements needs
    to mount and confirm. The client secret authorises the browser to confirm THIS intent
    and nothing else; the publishable key is public by definition. Neither is a credential
    for this application.

    Takes nothing from the request. The customer, when there is one, is resolved from the
    token's user — and when there isn't, none is created here: an abandoned form must not
    leave a customer behind, so the customer is made in ``confirm`` once Stripe says a card
    exists.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    from blueprints.subscription.services import payment_methods

    return _payment_methods_call(payment_methods.start_setup)


@subscription_bp.route(
    "/api/me/billing/payment-methods/confirm", methods=["POST", "OPTIONS"]
)
def my_payment_method_confirm_api():
    """Adopt the card the browser just confirmed. Body: ``{setup_intent, make_default?}``.

    The intent id comes back from the client, so nothing in the body is trusted: the
    intent is re-read from Stripe and refused unless it carries this caller's own
    ``metadata.user_id`` stamp. A customerless SetupIntent has nothing else tying it to
    anybody, which is exactly why the stamp is there.

    Idempotent — a retried request cannot produce a second card or a second customer.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    from blueprints.subscription.services import payment_methods

    body = request.get_json(silent=True) or {}
    setup_intent = str(body.get("setup_intent") or "").strip()
    make_default = bool(body.get("make_default"))

    return _payment_methods_call(
        lambda user_id: payment_methods.confirm_setup(
            user_id, setup_intent, make_default=make_default
        )
    )


@subscription_bp.route(
    "/api/me/billing/payment-methods/default", methods=["POST", "OPTIONS"]
)
def my_payment_method_default_api():
    """Make one saved method the account's main card. Body: ``{payment_method}``.

    NOMINATES NOTHING. Each company is billed on the card it was put on — see
    ``entity-payment-method`` below — so this changes what is charged for nothing that is
    already running. It decides which card the pickers offer first.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    from blueprints.subscription.services import payment_methods

    payment_method = _pm_id()
    return _payment_methods_call(
        lambda user_id: payment_methods.set_default(user_id, payment_method)
    )


@subscription_bp.route(
    "/api/me/billing/entity-payment-method", methods=["GET", "POST", "OPTIONS"]
)
def my_entity_payment_method_api():
    """The card ONE company is billed on. Read it, or change it.

    GET  ``?entity=<id>``          -> the saved methods, plus ``nominated_id``
    POST ``{entity, payment_method}`` -> put that company on that card

    THE ONE WRITE ON THIS SURFACE WITH BILLING CONSEQUENCES, and they stop at the company
    named: its renewals, its purchases and its trial conversion are charged here from now
    on, and nothing else the payer owns moves. The account default is a suggestion by
    comparison.

    Two proofs, both inside the service and both required: the method must belong to the
    caller's own customer (``_owned``), and the caller must be the company's PAYER
    (``_payer_of``) — being an admin of it is not enough, or an admin who pays nothing
    could move someone else's billing onto a card of their choosing.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    from blueprints.subscription.services import payment_methods

    if request.method == "GET":
        entity_id = str(request.args.get("entity") or "").strip()
        return _payment_methods_call(
            lambda user_id: payment_methods.for_entity(user_id, entity_id)
        )

    payload = request.get_json(silent=True) or {}
    entity_id = str(payload.get("entity") or "").strip()
    payment_method = str(payload.get("payment_method") or "").strip()
    return _payment_methods_call(
        lambda user_id: payment_methods.set_for_entity(
            user_id, entity_id, payment_method
        )
    )


@subscription_bp.route(
    "/api/me/billing/payment-methods/update", methods=["POST", "OPTIONS"]
)
def my_payment_method_update_api():
    """Edit a saved method. Body: ``{payment_method, exp_month?, exp_year?, name?, address?}``.

    Only what Stripe permits to change on an existing method: the expiry, and the billing
    name and address. A card's number, brand and CVC are the card — replacing those is
    "Add payment method", and this endpoint cannot be used to try.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    from blueprints.subscription.services import payment_methods

    body = request.get_json(silent=True) or {}
    payment_method = _pm_id()
    address = body.get("address")

    return _payment_methods_call(
        lambda user_id: payment_methods.update(
            user_id,
            payment_method,
            exp_month=body.get("exp_month"),
            exp_year=body.get("exp_year"),
            name=body.get("name"),
            address=address if isinstance(address, dict) else None,
        )
    )


@subscription_bp.route(
    "/api/me/billing/payment-methods/remove", methods=["POST", "OPTIONS"]
)
def my_payment_method_remove_api():
    """Detach a saved method. Body: ``{payment_method}``.

    Two 409s the page shows verbatim, both about leaving a live account unable to pay
    itself: the default cannot go while another method could take its place, and the last
    method cannot go at all while something is still billing forward. Each names its fix.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    from blueprints.subscription.services import payment_methods

    payment_method = _pm_id()
    return _payment_methods_call(
        lambda user_id: payment_methods.remove(user_id, payment_method)
    )

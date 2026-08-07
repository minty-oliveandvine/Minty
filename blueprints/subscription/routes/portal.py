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


@subscription_bp.route("/api/me/billing", methods=["GET", "OPTIONS"])
def my_billing_api():
    """The caller's ONE billing account, and what each entity puts on it.

    Same gate and same reasoning as ``my_subscriptions_api``: no id in the request, so
    nothing to point at somebody else's account. Read-only — changing a card stays in the
    Stripe flows.

    Not paged. A payer has one account and a handful of entities on it, and the answer to
    "what am I being charged, and on which card" is not improved by arriving in slices.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        return _unauthorized("unauthorized")

    from models.db import User

    if User.query.get(user_id) is None:
        return _unauthorized("no_user_claim", 403)

    from blueprints.subscription.services import portal

    try:
        payload = portal.build_payer_billing(user_id)
    except Exception:
        current_app.logger.exception("payer billing API failed for user %s", user_id)
        return _cors(
            make_response(jsonify({"error": "Could not load your billing."}), 500)
        )

    return _cors(make_response(jsonify(payload), 200))


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


@subscription_bp.route(
    "/api/me/billing/payment-method", methods=["POST", "OPTIONS"]
)
def my_payment_method_api():
    """Open Stripe's payment-method form for the caller's billing account.

    Answers ``{"url": …}`` for the client to send the browser to. The card never touches
    this application — that is the point, and it is what keeps us out of PCI scope. The
    portal session is deep-linked to the payment-method flow and pinned to the restricted
    configuration, so Stripe's own Cancel button is unreachable (cancelling is in-app
    exclusively — see ``_billing_portal_configuration``).

    The ONLY write-ish route in the payer portal, and it still writes nothing here: it
    mints a Stripe session scoped to the caller's own customer, resolved from the token's
    user. There is no id in the request that could point it at somebody else's card.

    ``next`` is an optional PATH on the Module 2 origin to come back to. Validated as a
    path, never taken as a URL: echoing a caller-supplied absolute URL into a redirect
    Stripe will follow is an open redirect with extra steps.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        return _unauthorized("unauthorized")

    payload = request.get_json(silent=True) or {}
    nxt = str(payload.get("next") or "/profile/billing")
    # A single leading slash and nothing that could climb out of the origin. "//host"
    # is protocol-relative and would leave it entirely; ".." only normalises to another
    # path on the same origin, but there is no reason to hand Stripe one.
    if not nxt.startswith("/") or nxt.startswith("//") or ".." in nxt:
        nxt = "/profile/billing"
    return_url = f"{_frontend_origin()}{nxt}"

    from blueprints.subscription.services import store as sub_store
    from blueprints.subscription.services.checkout import (
        CheckoutError, open_payment_method_update_for_customer)

    try:
        session = open_payment_method_update_for_customer(
            sub_store.customer_id_for_user(user_id), return_url
        )
    except CheckoutError as exc:
        # 409 is the "no customer yet" case, and it is not an error the user caused: the
        # portal cannot create a customer, so the FIRST card has to come through the
        # entity's subscribe flow. The client turns this into that instruction.
        return _cors(make_response(jsonify({"error": exc.message}), exc.status))
    except Exception:
        current_app.logger.exception(
            "payment method API failed for user %s", user_id
        )
        return _cors(
            make_response(
                jsonify({"error": "Could not open the payment form."}), 500
            )
        )

    return _cors(make_response(jsonify({"url": session.get("url")}), 200))


@subscription_bp.route("/api/me/billing/options", methods=["GET", "OPTIONS"])
def my_billing_options_api():
    """Dropdown contents for the billing-account form — countries, currencies, plans.

    Behind the same token as the rest of the portal even though none of it is personal:
    it is the catalog this deployment sells, and there is no reason for it to be the one
    endpoint here that answers to anybody.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    if not _user_id_from_bearer():
        return _unauthorized("unauthorized")

    from blueprints.subscription.services import portal

    try:
        payload = portal.billing_form_options()
    except Exception:
        current_app.logger.exception("billing options API failed")
        return _cors(
            make_response(jsonify({"error": "Could not load the options."}), 500)
        )

    return _cors(make_response(jsonify(payload), 200))

# Entity create routes.


from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Protocol, cast
from urllib.parse import urlencode

import jwt
import pycountry
from flask import (current_app, flash, jsonify, make_response, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required
from iso4217 import Currency
from loguru import logger

from blueprints.entity import entity_bp
from blueprints.shared.enums import EntityStatus
from blueprints.shared import bearer_api
from blueprints.entity.forms import CreateEntityForm
from blueprints.entity.services.payment_methods import (
    list_sales_methods_grouped, replace_sales_methods)
from blueprints.entity.services.shared import create_entity_for_user


class _PyCountryCountry(Protocol):
    alpha_2: str
    name: str


# --- Onboarding handoff helpers -------------------------------------------

def _onboarding_base_url() -> str:
    return bearer_api.onboarding_origin()


def _mint_onboarding_token(user_id) -> str:
    """Short-lived JWT the onboarding app sends back to create the entity."""
    secret = current_app.config.get("SECRET_KEY")
    payload = {
        "user_id": str(user_id),
        "scope": "onboarding",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=60),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def onboarding_launch_url(
    user, *, entity_name: str = "", entity_id: str = "", fresh: bool = False
) -> str:
    """Launch URL into the onboarding wizard for an already-authenticated user.

    Mints the short-lived onboarding JWT (the same token the ``/api/onboarding/*``
    endpoints accept) and passes the user's name so the wizard boots
    authenticated without a fresh email round-trip. The app hydrates ``token``,
    ``first``, ``last``, ``entity_name``, ``entity_id`` and ``fresh`` from these
    query params (see the onboarding app). When ``entity_name`` is given
    (resuming an in-progress entity) it pre-fills Step 1.

    Pass ``entity_id`` when resuming an in-progress entity: the wizard binds the
    existing entity (fetching its saved state via ``GET /api/onboarding/state``)
    instead of starting fresh, and the freshly minted token authorizes those
    calls. This makes resume work with no browser localStorage (fresh browser /
    incognito / different device).

    Pass ``fresh=True`` for the "+" / "create new entity" action: it emits
    ``fresh=1`` so the wizard MUST start a brand-new onboarding and ignore any
    previously-saved session in localStorage. Without this, the app rehydrates
    its single global session blob and "+" resumes the last in-progress entity
    instead of creating a new one — which also makes it impossible to have more
    than one in-progress entity. ``fresh`` and ``entity_id`` are mutually
    exclusive (resume binds an entity; fresh forbids any).
    """
    params = {
        "token": _mint_onboarding_token(user.id),
        "first": (getattr(user, "first_name", "") or "").strip(),
        "last": (getattr(user, "last_name", "") or "").strip(),
    }
    if entity_name:
        params["entity_name"] = entity_name
    if entity_id:
        params["entity_id"] = entity_id
    if fresh and not entity_id:
        params["fresh"] = "1"
    query = urlencode({k: v for k, v in params.items() if v})
    return f"{_onboarding_base_url()}/?{query}"


def _user_id_from_bearer():
    """Decode the onboarding JWT from the Authorization header -> user_id.

    Now the shared decoder, which returns a STRING; this copy returned the raw claim.
    """
    return bearer_api.user_id_from_bearer()


def _cors(resp):
    """Allow the onboarding origin to call the API cross-origin (token auth).

    ``PUT`` beyond the portal's list: the wizard updates the entity in place."""
    return bearer_api.cors(
        resp, _onboarding_base_url(), methods="GET, POST, PUT, OPTIONS"
    )


def _resolve_country_code(value: str) -> str:
    """Payload value → country_info.country_code (ISO alpha-2 PK).

    The wizard sends the code directly; alpha-3 codes and English names are
    accepted as fallbacks so older callers keep working. Mirrors the tolerance
    of ``_resolve_currency_id`` — the two are submitted by the same dropdowns,
    so a payload form that resolves for one must resolve for the other.

    The registry name is the authoritative long form ("Hong Kong SAR China"),
    which a caller sending a display label ("Hong Kong") would otherwise miss,
    so the name match also accepts a unique prefix. Ambiguous prefixes resolve
    to "" rather than guessing between countries.

    Returns "" when nothing matches (never an unvalidated value —
    entities.country_code is an FK). Callers treat "" for a non-empty input as
    an error; they must not silently skip the assignment.
    """
    from models.db import CountryInfo

    v = (value or "").strip()
    if not v:
        return ""

    # ``ilike`` treats % and _ as wildcards, so a user-supplied one would widen
    # both name matches below ("%" otherwise matches every row). Escape once.
    esc = v.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    row = CountryInfo.query.get(v.upper())
    if row is None and len(v) == 3:
        row = CountryInfo.query.filter(
            CountryInfo.alpha3_code == v.upper()
        ).first()
    if row is None:
        row = CountryInfo.query.filter(
            CountryInfo.country_name_en.ilike(esc, escape="\\")
        ).first()
    if row is None:
        # Unique-prefix fallback: only when exactly one country starts with the
        # value, so an ambiguous label resolves to "" instead of guessing.
        matches = (
            CountryInfo.query.filter(
                CountryInfo.country_name_en.ilike(f"{esc}%", escape="\\")
            )
            .limit(2)
            .all()
        )
        if len(matches) == 1:
            row = matches[0]

    return row.country_code if row else ""


def _resolve_currency_id(value: str) -> str:
    """Payload value → currency_info.id uuid.

    The wizard sends the uuid directly; ISO codes and currency names are
    accepted as fallbacks so older callers keep working. Returns "" when
    nothing matches (never a raw code — entities.currency_id is an FK now).
    """
    import uuid as _uuid

    from models.db import CurrencyInfo

    v = (value or "").strip()
    if not v:
        return ""
    try:  # only hit the uuid PK with a valid uuid (a bad literal aborts the tx)
        _uuid.UUID(v)
        row = CurrencyInfo.query.get(v)
    except ValueError:
        row = None
    if row:
        return row.id
    row = CurrencyInfo.query.filter(
        (CurrencyInfo.currency_code == v.upper())
        | (CurrencyInfo.currency_name.ilike(v))
    ).first()
    return row.id if row else ""


def _normalize_contact_phone(value: str) -> tuple[str | None, str]:
    """Payload value → (stored phone or None, error).

    Digits only, mirroring the wizard, which strips punctuation before sending
    and caps the field at 11. Length is re-checked here rather than trusted:
    this is a plain JSON route, so the client-side maxLength is not a control.
    An empty value returns None — the caller writes NULL, which is how a user
    who deletes their number actually gets it cleared.
    """
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if not digits:
        return None, ""
    if not 8 <= len(digits) <= 11:
        return None, "Phone number must be 8-11 digits."
    return digits, ""


def _normalize_business_email(value: str) -> tuple[str | None, str]:
    """Payload value → (stored email or None, error).

    Deliberately shallow: one @ with something either side and no spaces. The
    column is the company's contact address and is never used to authenticate
    or to send a confirmation, so a stricter parser would reject legitimate
    addresses for no gain. Empty clears the field.
    """
    email = (value or "").strip()
    if not email:
        return None, ""
    if len(email) > 100:
        return None, "Business email must be 100 characters or fewer."
    local, sep, domain = email.partition("@")
    if not sep or not local or not domain or any(c.isspace() for c in email):
        return None, "Please enter a valid business email."
    return email, ""


# --- Routes ---------------------------------------------------------------

@entity_bp.route("/entity/success")
@login_required
def entity_create_success():
    entity_id = request.args.get("entity_id") or ""
    return render_template("entity/entity_create_success.html", entity_id=entity_id)


@entity_bp.route("/entity/create", methods=["GET", "POST"])
@login_required
def entity_create():
    # New entities are created through the onboarding wizard (Step 1). Send the
    # authenticated user straight there; the legacy POST handler below stays as
    # a server-side fallback but is no longer reached via the UI.
    #
    # fresh=True → emits ?fresh=1 so the wizard starts a brand-new onboarding and
    # ignores any saved session in localStorage. This is the "+" / create-new
    # action: it must NOT resume a previously in-progress entity (that only
    # happens by clicking the in-progress entity row, which passes entity_id).
    if request.method == "GET":
        return redirect(onboarding_launch_url(current_user, fresh=True))

    form = CreateEntityForm()
    countries = cast(Iterable[_PyCountryCountry], pycountry.countries)
    country_code = [
        {"country_code": c.alpha_2, "country_name": c.name} for c in countries
    ]
    currency_iterable = list(Currency)
    currencies = [
        {"currency_code": c.code, "currency_name": c.currency_name}
        for c in currency_iterable
    ]

    if request.method == "POST":
        if form.validate_on_submit():
            entity, error = create_entity_for_user(
                current_user.id,
                form.entity_name.data,
                _resolve_country_code(form.country_code.data),
                _resolve_currency_id(form.currency_code.data),
                status=EntityStatus.DISCONNECTED,  # live at once, no Xero org yet
            )
            if error:
                form.entity_name.errors = [*form.entity_name.errors, error]
                flash(error, "danger")
                return redirect(url_for("entity.entity_create"))
            # The form has always validated these two as required and then
            # thrown them away; now that the columns exist, persist them. The
            # form validators already bound the lengths, so the normalizers
            # here only strip the phone to digits.
            from models.db import db as _db
            entity.contact_phone, _ = _normalize_contact_phone(
                form.contact_phone.data
            )
            entity.business_email, _ = _normalize_business_email(
                form.business_email.data
            )
            _db.session.commit()
            return redirect(url_for("entity.entity_create_success", entity_id=entity.id))

    return render_template(
        "entity/entity_create.html",
        country_code=country_code,
        currencies=currencies,
        form=form,
    )


@entity_bp.route("/api/onboarding/server-time", methods=["GET", "OPTIONS"])
def onboarding_server_time():
    """Server-authoritative "today" in Hong Kong time for the onboarding app.

    GET → {"today": "YYYY-MM-DD"} in Asia/Hong_Kong. The onboarding date picker
    uses this to cap selectable dates at the current date so the future-date
    boundary matches the users' local midnight, not the browser's timezone.
    Public (returns only the current date); same CORS contract as the others.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    from models.db import tz

    resp = jsonify({"today": datetime.now(tz).date().isoformat()})
    return _cors(resp)


@entity_bp.route("/api/onboarding/currencies", methods=["GET", "OPTIONS"])
def onboarding_currencies():
    """Currency registry for the onboarding Step 1 dropdown.

    GET → {"currencies": [{"currency_id", "currency_name", "iso_code"}, ...]}
    ordered by currency_name. The dropdown shows currency_name but submits
    currency_id (the currency_info uuid PK) so the created entity's
    currency_id FK gets a uuid. The response keys keep their historical names
    (iso_code carries currency_info.currency_code) so the wizard needs no
    change. Public (reference data only); same CORS contract as the other
    onboarding routes.

    Only is_active rows are offered. currency_info is seeded with the full
    ISO 4217 list (~170 rows); is_active narrows that to the currencies this
    deployment actually operates in. No preselect concern here — this is the
    new-entity wizard, so there is no existing value to preserve (unlike the
    settings dropdowns, which keep the entity's current row regardless).
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    from models.db import CurrencyInfo

    rows = (
        CurrencyInfo.query.with_entities(
            CurrencyInfo.id,
            CurrencyInfo.currency_name,
            CurrencyInfo.currency_code,
        )
        .filter(CurrencyInfo.is_active.is_(True))
        .order_by(CurrencyInfo.currency_name)
        .all()
    )
    resp = jsonify({"currencies": [
        {"currency_id": cid, "currency_name": name, "iso_code": code}
        for cid, name, code in rows
    ]})
    return _cors(resp)


@entity_bp.route("/api/onboarding/countries", methods=["GET", "OPTIONS"])
def onboarding_countries():
    """Country registry for the onboarding Step 1 dropdown.

    GET → {"countries": [{"country_id", "country_name_en", "country_code"}, ...]}
    country_info's PK is the ISO alpha-2 country_code now, so ``country_id``
    carries that code too — the key is kept so the wizard's submit-the-id
    contract needs no change (the create / update endpoints resolve codes).
    Public; same CORS contract as the other onboarding routes.

    Only is_active rows are offered. country_info is seeded with the full ISO
    3166-1 list (~250 rows); is_active narrows that to the countries this
    deployment operates in. Ordered by display_order then name, so the
    common countries can be floated above the alphabetical tail by setting a
    value below the 999 default; ties fall back to alphabetical, which is
    what every row does while display_order is left at its default.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    from models.db import CountryInfo

    rows = (
        CountryInfo.query.with_entities(
            CountryInfo.country_code,
            CountryInfo.country_name_en,
        )
        .filter(CountryInfo.is_active.is_(True))
        .order_by(CountryInfo.display_order, CountryInfo.country_name_en)
        .all()
    )
    resp = jsonify({"countries": [
        {"country_id": code, "country_name_en": name, "country_code": code}
        for code, name in rows
    ]})
    return _cors(resp)


@entity_bp.route("/api/onboarding/state", methods=["GET", "OPTIONS"])
def onboarding_state():
    """Token-authenticated resume state for the onboarding app.

    GET ?entity_id=… → the full wizard picture reconstructed from the DB
    (basic info, modules, Xero, invites) plus a derived ``current_step`` /
    ``max_reached``. The ``entities`` row is the source of truth, so resume
    works with no browser localStorage (fresh browser / incognito / different
    device). Same JWT/CORS/membership contract as the other onboarding routes.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    entity_id = (request.args.get("entity_id") or "").strip()
    if not entity_id:
        resp = jsonify({"error": "entity_id is required"})
        resp.status_code = 400
        return _cors(resp)

    from blueprints.entity.services.onboarding_state import \
        get_onboarding_state

    data, status = get_onboarding_state(user_id, entity_id)
    resp = jsonify(data)
    resp.status_code = status
    return _cors(resp)


@entity_bp.route("/api/onboarding/saved-step", methods=["POST", "OPTIONS"])
def onboarding_saved_step():
    """Token-authenticated "Save and Exit" step for the onboarding app.

    POST {entity_id, saved_step} → persists ``saved_step`` (the frontend step
    id 1-9, stored verbatim) on the entity so resume can land the user back
    where they left off across devices/cleared browsers. Membership-checked
    against the JWT; same JWT/CORS contract as the other onboarding routes.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    payload = request.get_json(silent=True) or {}
    entity_id = (payload.get("entity_id") or "").strip()
    if not entity_id:
        resp = jsonify({"error": "entity_id is required"})
        resp.status_code = 400
        return _cors(resp)

    from blueprints.entity.services.onboarding_state import \
        save_onboarding_step

    data, status = save_onboarding_step(user_id, entity_id, payload.get("saved_step"))
    resp = jsonify(data)
    resp.status_code = status
    return _cors(resp)


@entity_bp.route("/api/onboarding/create", methods=["POST", "OPTIONS"])
def onboarding_create_entity():
    """Token-authenticated entity creation for the onboarding app (Step 1).

    Authenticated by a short-lived onboarding JWT (sent as
    ``Authorization: Bearer <token>``), so it works cross-origin without a
    session cookie. Reuses ``create_entity_for_user``.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    data = request.get_json(silent=True) or {}
    entity_name = data.get("entity_name") or data.get("name") or ""
    country_in = (
        data.get("country_id") or data.get("country") or data.get("country_code") or ""
    )
    country_code = _resolve_country_code(country_in)
    # A country that was supplied but doesn't resolve is a client error, not a
    # reason to create the entity with a NULL country: failing here surfaces the
    # mismatch instead of silently dropping the selection.
    if country_in and not country_code:
        resp = jsonify({"error": f"Unknown country: {country_in}"})
        resp.status_code = 400
        return _cors(resp)

    currency_in = (
        data.get("currency_id") or data.get("currency") or data.get("currency_code") or ""
    )
    currency_id = _resolve_currency_id(currency_in)
    if currency_in and not currency_id:
        resp = jsonify({"error": f"Unknown currency: {currency_in}"})
        resp.status_code = 400
        return _cors(resp)

    # Optional company contact details (Step 1). Validated before the entity is
    # created so a bad phone/email is a 400 rather than a half-saved entity.
    contact_phone, phone_err = _normalize_contact_phone(data.get("contact_phone"))
    if phone_err:
        resp = jsonify({"error": phone_err})
        resp.status_code = 400
        return _cors(resp)
    business_email, email_err = _normalize_business_email(data.get("business_email"))
    if email_err:
        resp = jsonify({"error": email_err})
        resp.status_code = 400
        return _cors(resp)

    entity, error = create_entity_for_user(user_id, entity_name, country_code, currency_id)
    if error:
        resp = jsonify({"error": error})
        resp.status_code = 409 if "exist" in error.lower() else 400
        return _cors(resp)

    from models.db import db as _db
    entity.status = EntityStatus.ONBOARDING
    entity.contact_phone = contact_phone
    entity.business_email = business_email
    _db.session.commit()

    resp = jsonify({"entity_id": entity.id, "name": entity.name})
    resp.status_code = 201
    return _cors(resp)


@entity_bp.route(
    "/api/onboarding/entity/<string:entity_id>", methods=["PUT", "OPTIONS"]
)
def onboarding_update_entity(entity_id):
    """Token-authenticated edit of an in-progress entity (onboarding Step 1).

    Lets the wizard persist name/country/currency edits when the user goes back
    to Step 1 on revisit. Overwrites the EXISTING entity row in place — it never
    creates a new entity. Mirrors the country→currency derivation of the
    session-authenticated Settings page (``_integration_minimal_entity_settings_post``),
    but authenticates via the onboarding JWT + membership check like the other
    ``/api/onboarding/*`` routes.

    PUT {entity_name, country, currency} → {"entity_id"} / {"error"}.
    Renames are gated on ``ENTITY_RENAME`` and 409 on a name already taken by a
    different entity. Same JWT/CORS contract as the other onboarding routes.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    entity_id = (entity_id or "").strip()
    if not entity_id:
        resp = jsonify({"error": "entity_id is required"})
        resp.status_code = 400
        return _cors(resp)

    from models.db import CountryInfo, CurrencyInfo, Entity, UserEntity
    from models.db import db as _db
    from services.permission_policy import (Permission,
                                            has_permission_by_user_id)

    membership = UserEntity.query.filter(
        UserEntity.user_id == str(user_id),
        UserEntity.entity_id == entity_id,
    ).first()
    if not membership:
        resp = jsonify({"error": "You don't have access to this entity"})
        resp.status_code = 403
        return _cors(resp)

    entity = Entity.query.get(entity_id)
    if not entity:
        resp = jsonify({"error": "Entity not found"})
        resp.status_code = 404
        return _cors(resp)

    payload = request.get_json(silent=True) or {}

    # --- Name (admin-only rename; re-check the gate on this crafted PUT) ------
    if "entity_name" in payload or "name" in payload:
        name_new = (payload.get("entity_name") or payload.get("name") or "").strip()
        if name_new != (entity.name or ""):
            if not has_permission_by_user_id(
                user_id, Permission.ENTITY_RENAME, entity_id
            ):
                resp = jsonify(
                    {"error": "You don't have permission to rename this entity"}
                )
                resp.status_code = 403
                return _cors(resp)
            if not name_new:
                resp = jsonify({"error": "Entity name is required."})
                resp.status_code = 400
                return _cors(resp)
            if len(name_new) > 100:
                resp = jsonify(
                    {"error": "Entity name must be 100 characters or fewer."}
                )
                resp.status_code = 400
                return _cors(resp)
            if Entity.query.filter(
                Entity.name == name_new, Entity.id != entity_id
            ).first():
                resp = jsonify({"error": "Entity name already exist"})
                resp.status_code = 409
                return _cors(resp)
            entity.name = name_new

    # --- Country / currency ---------------------------------------------------
    # The wizard submits the country code and the currency_info uuid (the
    # dropdowns show names but carry those values). An explicit currency wins;
    # when only the country is supplied, its registry currency is derived.
    country_in = (
        payload.get("country_id") or payload.get("country")
        or payload.get("country_code") or ""
    )
    country_code = _resolve_country_code(country_in)
    # A supplied-but-unresolvable country is a client error. Skipping the
    # assignment here used to leave country_code NULL while the currency (whose
    # resolver accepts names) still saved — the two silently diverged and the
    # 200 gave the wizard no way to notice.
    if country_in and not country_code:
        resp = jsonify({"error": f"Unknown country: {country_in}"})
        resp.status_code = 400
        return _cors(resp)
    if country_code:
        entity.country_code = country_code

    currency_in = (
        payload.get("currency_id") or payload.get("currency")
        or payload.get("currency_code") or ""
    )
    currency_id = _resolve_currency_id(currency_in)
    if currency_in and not currency_id:
        resp = jsonify({"error": f"Unknown currency: {currency_in}"})
        resp.status_code = 400
        return _cors(resp)
    if not currency_id and country_code:
        country_info = CountryInfo.query.get(country_code)
        if country_info and country_info.currency_id:
            currency_id = country_info.currency_id
    if currency_id:
        entity.currency_id = currency_id
        currency_info = CurrencyInfo.query.get(currency_id)
        if currency_info:
            entity.currency_format = currency_info.symbol or "$"

    # --- Contact details ------------------------------------------------------
    # Keyed off presence, not truthiness: both fields are optional, so "" is a
    # meaningful value meaning "clear this". An absent key leaves the stored
    # value alone, which keeps older callers that never send them working.
    if "contact_phone" in payload:
        contact_phone, phone_err = _normalize_contact_phone(payload.get("contact_phone"))
        if phone_err:
            resp = jsonify({"error": phone_err})
            resp.status_code = 400
            return _cors(resp)
        entity.contact_phone = contact_phone
    if "business_email" in payload:
        business_email, email_err = _normalize_business_email(
            payload.get("business_email")
        )
        if email_err:
            resp = jsonify({"error": email_err})
            resp.status_code = 400
            return _cors(resp)
        entity.business_email = business_email

    try:
        _db.session.commit()
    except Exception as exc:  # noqa: BLE001
        _db.session.rollback()
        logger.error(
            "onboarding_update_entity failed entity=%s: %s", entity_id, exc
        )
        resp = jsonify({"error": "Failed to update entity. Please try again."})
        resp.status_code = 500
        return _cors(resp)

    resp = jsonify({"entity_id": entity.id, "name": entity.name})
    resp.status_code = 200
    return _cors(resp)


@entity_bp.route("/api/onboarding/plans", methods=["GET", "OPTIONS"])
def onboarding_plans():
    """Module price list for onboarding Step 2's subscription summary.

    GET → {plans: [{code, name, amount, currency_code, …}], bundle_amount,
    bundle_codes, bundle_currency, trial_period_days}, read live from Stripe. The
    bundle price is what both modules together cost. Entity-independent
    (it's the catalog, not a customer's state), but token-gated like the other
    onboarding routes so an unauthenticated caller can't drive Stripe API traffic.

    Same JWT/CORS contract as the rest of ``/api/onboarding/*``.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    # Lazy import — pulls in the model graph and the Stripe layer.
    from blueprints.entity.services.modules import get_module_plan_catalog

    try:
        data = get_module_plan_catalog()
    except Exception:
        # Stripe unreachable / not configured: the wizard falls back to hiding the
        # summary rather than blocking module selection, so this is not fatal.
        current_app.logger.exception("onboarding_plans: could not load plan catalog")
        resp = jsonify({"error": "Plans are unavailable right now."})
        resp.status_code = 503
        return _cors(resp)

    return _cors(jsonify(data))


def _entity_for_member(user_id, entity_id):
    """The entity, if ``user_id`` is a member of it. Returns ``(entity, error_resp)``
    — exactly one is None. Shared by the payment-method routes."""
    from models.db import Entity, UserEntity

    if not entity_id:
        resp = jsonify({"error": "entity_id is required"})
        resp.status_code = 400
        return None, _cors(resp)

    membership = UserEntity.query.filter(
        UserEntity.user_id == str(user_id),
        UserEntity.entity_id == entity_id,
    ).first()
    if not membership:
        resp = jsonify({"error": "You don't have access to this entity"})
        resp.status_code = 403
        return None, _cors(resp)

    entity = Entity.query.get(entity_id)
    if not entity:
        resp = jsonify({"error": "Entity not found"})
        resp.status_code = 404
        return None, _cors(resp)
    return entity, None


@entity_bp.route("/api/onboarding/payment-method", methods=["GET", "OPTIONS"])
def onboarding_payment_method_status():
    """What Step 2's billing sheet needs to know about this entity's billing.

    GET ?entity_id=… → {"has_payment_method": bool, "has_billing_consent": bool,
    "card": {…}|null}.

    Two separate questions, and the second is the one that matters. ``has_payment_method``
    is read live from Stripe and belongs to the PAYER, shared across every entity they pay
    for, so it says nothing about this entity. Consent is per (entity, payer) and is what
    decides whether this entity's 30-day trial converts to paid at term end or simply
    lapses.

    ``card`` IS THIS ENTITY'S NOMINATED CARD, not the payer's default — the difference is
    the whole reason it is here. A caller that wants to print "we will bill you on this
    card" must print the one this entity is actually nominated on; the account default is
    a different card as soon as the payer has two, and naming it would tell them they are
    about to be billed on a card they are not. Null when nothing is nominated, and null
    is the honest answer rather than a fallback to the default.

    Neither gates the wizard: the trial starts either way, so a payer who skips the sheet
    still onboards — they just lapse at day 30 instead of converting.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    entity, err = _entity_for_member(user_id, (request.args.get("entity_id") or "").strip())
    if err:
        return err

    from blueprints.subscription.services.checkout import entity_has_payment_method

    try:
        has_pm = entity_has_payment_method(entity)
    except Exception:
        # Stripe unreachable — report "no card" rather than 500. The user can retry
        # the add-card button; they just can't advance yet.
        current_app.logger.exception(
            "onboarding payment-method: status check failed for %s", entity.id
        )
        has_pm = False

    # Local read, deliberately outside the try above: an unreachable Stripe must not be
    # able to report "no consent" for an entity the payer has already authorised, which
    # would offer them the billing sheet a second time for something they already have.
    from blueprints.subscription.services import store

    # The card this entity is nominated on, described the same way the billing dialog
    # describes its rows — both come from ``list_for_user``, so the summary and the picker
    # cannot render the same card two different ways.
    #
    # Best-effort, and separately guarded: a Stripe outage here must degrade to "no card
    # to show" rather than failing a status check whose other two answers are still good.
    card = None
    try:
        nominated = store.card_for_entity(entity.id, user_id)
        if nominated:
            from blueprints.subscription.services import payment_methods

            wallet = payment_methods.list_for_user(user_id)
            card = next(
                (m for m in wallet.get("methods", []) if m.get("id") == nominated), None
            )
    except Exception:
        current_app.logger.exception(
            "onboarding payment-method: could not describe the card for %s", entity.id
        )

    return _cors(
        jsonify(
            {
                "has_payment_method": has_pm,
                "has_billing_consent": store.has_billing_consent(entity.id, user_id),
                "card": card,
            }
        )
    )


@entity_bp.route("/api/onboarding/payment-method/setup", methods=["POST", "OPTIONS"])
def onboarding_payment_method_setup():
    """Open a hosted Stripe Checkout (setup mode) to save a card — no charge.

    POST {entity_id} → {"url": …}. Stripe redirects back to the wizard with
    ``?pm_session_id=…``, which the wizard hands to /payment-method/complete. No
    subscription is created here: onboarding starts the trials at finalize.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    payload = request.get_json(silent=True) or {}
    entity, err = _entity_for_member(user_id, (payload.get("entity_id") or "").strip())
    if err:
        return err

    from blueprints.subscription.services.checkout import (
        CheckoutError,
        start_payment_method_setup,
    )
    from models.db import User

    app_url = _onboarding_base_url()
    try:
        result = start_payment_method_setup(
            entity,
            User.query.get(str(user_id)),
            success_url=f"{app_url}/?pm_session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{app_url}/?pm_cancelled=1",
        )
    except CheckoutError as exc:
        resp = jsonify({"error": exc.message})
        resp.status_code = exc.status
        return _cors(resp)
    except Exception:
        current_app.logger.exception(
            "onboarding payment-method: could not open setup checkout for %s", entity.id
        )
        resp = jsonify({"error": "Could not open the payment form. Please try again."})
        resp.status_code = 503
        return _cors(resp)

    return _cors(jsonify(result))


@entity_bp.route("/api/onboarding/payment-method/complete", methods=["POST", "OPTIONS"])
def onboarding_payment_method_complete():
    """Save the card captured by a setup checkout as the customer's default.

    POST {entity_id, session_id} → {"has_payment_method": true}. Called by the wizard
    when Stripe redirects back with ``pm_session_id``. Idempotent, so a refresh of the
    return URL is harmless.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    payload = request.get_json(silent=True) or {}
    entity, err = _entity_for_member(user_id, (payload.get("entity_id") or "").strip())
    if err:
        return err

    session_id = (payload.get("session_id") or "").strip()
    if not session_id:
        resp = jsonify({"error": "session_id is required"})
        resp.status_code = 400
        return _cors(resp)

    from blueprints.subscription.services.checkout import (
        CheckoutError,
        complete_payment_method_setup,
    )

    try:
        complete_payment_method_setup(entity, session_id)
    except CheckoutError as exc:
        resp = jsonify({"error": exc.message})
        resp.status_code = exc.status
        return _cors(resp)
    except Exception:
        current_app.logger.exception(
            "onboarding payment-method: could not save card for %s", entity.id
        )
        resp = jsonify({"error": "Could not save your card. Please try again."})
        resp.status_code = 503
        return _cors(resp)

    return _cors(jsonify({"has_payment_method": True}))


# --- Onboarding billing sheet -----------------------------------------------
#
# The four payment-method routes below are deliberate MIRRORS of the payer portal's
# ``/api/me/billing/payment-methods*``, not a refactor of them: same service functions
# underneath, only the CORS header differs — and that difference is the entire reason
# they exist. The portal's ``_cors`` names ONE origin (``FRONTEND_APP_URL``), so a
# browser on the onboarding origin is blocked before the request is even authenticated.
# Widening the portal's header to a list would loosen the payer portal's surface for the
# benefit of a different app; four thin wrappers don't touch it at all.


def _billing_call(handler):
    """Run one payment-method action for the bearer's own account, CORS'd for onboarding.

    The onboarding twin of ``subscription.routes.portal._payment_methods_call``: same
    contract. Only the bearer check and this app's own CORS origin are its own — the
    three shared failure modes live in ``payment_methods.run``.

    Note these act on the PAYER, not on an entity — a card belongs to the person, not to
    the company — so unlike the routes above there is no entity to check membership on.
    """
    from blueprints.subscription.services import payment_methods

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    payload, status = payment_methods.run(handler, user_id)
    resp = jsonify(payload)
    resp.status_code = status
    return _cors(resp)


@entity_bp.route("/api/onboarding/billing/payment-methods", methods=["GET", "OPTIONS"])
def onboarding_billing_payment_methods():
    """Every card saved on the payer's account, with the default marked.

    GET → the same shape the payer portal renders, so the billing sheet and the billing
    page cannot drift into describing the same card differently.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    from blueprints.subscription.services import payment_methods

    return _billing_call(payment_methods.list_for_user)


@entity_bp.route(
    "/api/onboarding/billing/payment-methods/setup-intent", methods=["POST", "OPTIONS"]
)
def onboarding_billing_setup_intent():
    """Open a SetupIntent for the in-app card form.

    POST → ``{client_secret, publishable_key, setup_intent}``. The publishable key is
    handed back rather than configured in the onboarding app: one place holds the Stripe
    config, and a key that disagrees with the intent's account becomes a bug that cannot
    happen if the browser never chooses it.

    Works for a payer with no Stripe customer yet — a SetupIntent does not need one, and
    the customer is created at confirm once Stripe says the card is real. Abandoning the
    sheet here therefore leaves nothing behind.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    from blueprints.subscription.services import payment_methods

    return _billing_call(payment_methods.start_setup)


@entity_bp.route(
    "/api/onboarding/billing/payment-methods/confirm", methods=["POST", "OPTIONS"]
)
def onboarding_billing_confirm():
    """Adopt the card the browser just confirmed. Body: ``{setup_intent, make_default?}``.

    Only the intent id crosses this boundary — the card number is typed into Stripe
    Elements and confirmed straight against the SetupIntent, so no PAN reaches this
    process.

    Saving a card AUTHORISES NOTHING. Billing this entity needs that entity's own consent,
    which is ``/billing/authorize`` below — a separate call for exactly that reason.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    from blueprints.subscription.services import payment_methods

    payload = request.get_json(silent=True) or {}
    setup_intent = str(payload.get("setup_intent") or "").strip()
    make_default = bool(payload.get("make_default"))

    # THE BILLING ACCOUNT, and all three are optional. A body carrying none of them
    # behaves exactly as it did before accounts existed: the card is saved and nothing
    # else. ``billing_group_id`` puts it on an account the payer already has; an email or
    # a company with no group opens a new one. The service checks the group is the
    # caller's own — a group id from a browser is not a permission.
    billing_group_id = str(payload.get("billing_group_id") or "").strip() or None
    billing_email = payload.get("billing_email")
    billing_company = payload.get("billing_company")

    return _billing_call(
        lambda user_id: payment_methods.confirm_setup(
            user_id, setup_intent, make_default=make_default,
            billing_group_id=billing_group_id,
            billing_email=billing_email,
            billing_company=billing_company,
        )
    )


@entity_bp.route(
    "/api/onboarding/billing/payment-methods/default", methods=["POST", "OPTIONS"]
)
def onboarding_billing_set_default():
    """Make one card the account's main one. Body: ``{payment_method}``.

    It nominates nothing by itself. Each company is billed on the card it was put on
    (``EntityBillingGroup``), and this decides which card is offered first — including to
    ``billing/authorize`` below, which puts the company being set up onto it. In the
    wizard those two calls are one action, which is why choosing here still ends up
    deciding what this company is billed to; it does not touch the ones already running.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    from blueprints.subscription.services import payment_methods

    payment_method = str(
        (request.get_json(silent=True) or {}).get("payment_method") or ""
    ).strip()

    return _billing_call(
        lambda user_id: payment_methods.set_default(user_id, payment_method)
    )


@entity_bp.route("/api/onboarding/billing/accounts", methods=["GET", "POST", "OPTIONS"])
def onboarding_billing_accounts():
    """The payer's billing accounts, and the way to open one.

    GET → ``{accounts: [{id, billing_email, billing_company, default_id, cards[]}], …}``.
    An account is a name, the cards on it, and the one card it charges; the picker
    chooses between accounts rather than between loose cards.

    POST → open an account. Body: ``{payment_method, billing_email?, billing_company?}``.
    The card must already be saved — this does not take card details, and cannot: the
    number only ever exists inside Stripe Elements, and a card becomes the payer's at
    ``/payment-methods/confirm``. The ordinary onboarding path never calls this at all,
    because confirm opens the account in the same request the card is saved in; this is
    for opening a SECOND account on a card the payer already holds.

    OPENING AN ACCOUNT AUTHORISES NOTHING. It names a card and a company for invoices.
    Billing an entity still needs that entity's own consent — ``/billing/authorize``
    below — which is a separate call for exactly that reason.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    from blueprints.subscription.services import payment_methods

    if request.method == "GET":
        return _billing_call(payment_methods.accounts_for_user)

    payload = request.get_json(silent=True) or {}
    payment_method = str(payload.get("payment_method") or "").strip()
    if not payment_method:
        resp = jsonify({"error": "A saved card is required to open a billing account."})
        resp.status_code = 400
        return _cors(resp)

    billing_email = payload.get("billing_email")
    billing_company = payload.get("billing_company")

    def _open(user_id):
        from blueprints.subscription.services import store as sub_store

        # OWNERSHIP FIRST. ``_owned`` is the same check every mutation in
        # payment_methods makes: it proves the card is on the caller's own Stripe
        # customer, so a ``pm_...`` copied from anywhere else cannot open an account.
        payment_methods._owned(user_id, payment_method)
        account = sub_store.create_billing_account(
            user_id, payment_method,
            billing_email=billing_email, billing_company=billing_company,
        )
        return {
            "id": account.id,
            "billing_email": account.billing_email,
            "billing_company": account.billing_company,
            "default_id": account.stripe_payment_method_id,
        }

    return _billing_call(_open)


@entity_bp.route("/api/onboarding/billing/authorize", methods=["POST", "OPTIONS"])
def onboarding_billing_authorize():
    """Record consent to bill THIS entity. Charges nothing.

    Body: ``{entity_id, payment_method?}``.

    This is what the billing sheet actually secures. The 30-day trial still runs its full
    term; what
    changes is what happens at the end of it — ``checkout.convert_or_expire_due_trials``
    converts a trial to paid only when the payer has BOTH a card and a consent row for the
    entity, and lets it lapse otherwise. So this is the difference between "converts" and
    "expires", not between "trial" and "charged now".

    ``payment_method`` is nominated BEFORE consent is recorded, exactly as the in-app twin
    ``entity_settings_module_authorize_billing`` does it: authorising a charge while the
    company still points at a different card authorises one the payer was never shown.

    IT IS WHAT LETS ONBOARDING STOP SETTING THE ACCOUNT DEFAULT. The sheet used to make
    every card it captured the payer's default and let ``checkout._ensure_nominated`` find
    it again from there — which repointed every other company the payer owned as a side
    effect of confirming one. Sending the id explicitly says which card this company goes
    on and moves nothing else. Absent, ``_ensure_nominated`` still backstops the older
    clients.

    BOTH HALVES RUN BEFORE ANY SUBSCRIPTION EXISTS — onboarding starts the trials at
    finalize — and each needs its own reason to be allowed to.

    Consent is per entity rather than per subscription and outlives the wizard, so it
    simply does not care. The NOMINATION does: it is refused for a company with no payer,
    and during the wizard no company has one, because the payer is read from
    ``entity_module_subscription``. This request is the one that establishes the payer,
    which is why it passes ``establish_payer=True`` — the only caller that does. Membership
    is already proven above by ``_entity_for_member``, and ``set_for_entity`` still proves
    the card is this caller's.

    Idempotent per payer, so a double-click or a re-opened sheet is harmless.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    payload = request.get_json(silent=True) or {}
    entity, err = _entity_for_member(user_id, (payload.get("entity_id") or "").strip())
    if err:
        return err

    from blueprints.subscription.services import payment_methods
    from blueprints.subscription.services.checkout import (
        CheckoutError,
        authorize_entity_billing,
    )
    from models.db import User

    pm_id = str(payload.get("payment_method") or "").strip()
    try:
        if pm_id:
            # Routed through ``set_for_entity``, which proves both halves: the method
            # belongs to this caller, and this caller is the company's payer. Another
            # payer's ``pm_...`` answers "not found" rather than being nominated. Being a
            # member of the entity — all ``_entity_for_member`` above established — is
            # deliberately not enough to spend somebody else's card.
            payment_methods.set_for_entity(
                user_id, entity.id, pm_id, establish_payer=True
            )
    except payment_methods.PaymentMethodError as exc:
        resp = jsonify({"error": exc.message})
        resp.status_code = exc.status
        return _cors(resp)

    try:
        authorize_entity_billing(entity, User.query.get(str(user_id)))
    except CheckoutError as exc:
        resp = jsonify({"error": exc.message})
        resp.status_code = exc.status
        return _cors(resp)
    except Exception:
        current_app.logger.exception(
            "onboarding billing: could not authorize billing for %s", entity.id
        )
        resp = jsonify({"error": "Could not confirm billing. Please try again."})
        resp.status_code = 500
        return _cors(resp)

    return _cors(jsonify({"has_billing_consent": True}))


@entity_bp.route("/api/onboarding/modules", methods=["POST", "OPTIONS"])
def onboarding_modules():
    """Token-authenticated module selection (onboarding Step 2).

    POST {entity_id, module: "PETTY_CASH" | "PAYMENT_REQUEST"} → upserts both rows in
    ``entity_function_map`` (selected → is_enabled=true, the other → false).
    Returns {"modules": {code: bool, ...}} reflecting the resulting state.

    Same JWT/CORS contract as the other ``/api/onboarding/*`` routes. We
    enforce that the calling user is a member of the entity (the onboarding
    flow always satisfies this because Step 1 just created the entity under
    them, but the check is here as a defence against replay with a different
    entity_id).
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    payload = request.get_json(silent=True) or {}
    entity_id = (payload.get("entity_id") or "").strip()
    # Multi-select: prefer the `modules` array; fall back to the legacy
    # `module` single string so any older caller still works.
    modules_list = payload.get("modules")
    if isinstance(modules_list, list):
        selected = [str(m or "").strip().upper() for m in modules_list if (m or "").strip()]
    else:
        legacy = (payload.get("module") or "").strip().upper()
        selected = [legacy] if legacy else []
    if not entity_id:
        resp = jsonify({"error": "entity_id is required"})
        resp.status_code = 400
        return _cors(resp)
    if not selected:
        resp = jsonify({"error": "at least one module is required"})
        resp.status_code = 400
        return _cors(resp)

    # Lazy imports — these touch the db module which pulls in the full model
    # graph, and create.py is imported early in blueprint loading.
    from blueprints.entity.services.modules import (ACTOR_ONBOARDING,
                                                    apply_module_selections)
    from models.db import UserEntity

    membership = UserEntity.query.filter(
        UserEntity.user_id == str(user_id),
        UserEntity.entity_id == entity_id,
    ).first()
    if not membership:
        resp = jsonify({"error": "You don't have access to this entity"})
        resp.status_code = 403
        return _cors(resp)

    data, status = apply_module_selections(
        entity_id, selected, actor=ACTOR_ONBOARDING, user_id=str(user_id)
    )
    resp = jsonify(data)
    resp.status_code = status
    return _cors(resp)


@entity_bp.route("/api/onboarding/finalize", methods=["POST", "OPTIONS"])
def onboarding_finalize():
    """Finish onboarding: flip the entity live, start its trials, report the trial end.

    POST {entity_id} → {"status": "success", "trial_end": iso8601|null}.

    Clears the mid-onboarding flag so the entity routes to its dashboard on the next
    entity-list click instead of bouncing back to onboarding, and starts the card-free
    trials for the modules the wizard enabled.

    ``trial_end`` EXISTS BECAUSE THE ALL SET SCREEN STATES IT. That screen tells the payer
    their trial has started and when it runs to, so it has to be given the committed date
    rather than adding 30 days to today in the browser — a prediction that drifts past
    midnight and is simply wrong if starting the trials failed.

    Called on ARRIVAL at the All Set step, not on the way out of it. Same JWT/CORS
    contract as the other /api/onboarding/* routes.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    payload = request.get_json(silent=True) or {}
    entity_id = (payload.get("entity_id") or "").strip()
    if not entity_id:
        resp = jsonify({"error": "entity_id is required"})
        resp.status_code = 400
        return _cors(resp)

    from models.db import Entity, UserEntity
    from models.db import db as _db
    membership = UserEntity.query.filter(
        UserEntity.user_id == str(user_id),
        UserEntity.entity_id == entity_id,
    ).first()
    if not membership:
        resp = jsonify({"error": "You don't have access to this entity"})
        resp.status_code = 403
        return _cors(resp)

    entity = Entity.query.get(entity_id)
    if not entity:
        resp = jsonify({"error": "Entity not found"})
        resp.status_code = 404
        return _cors(resp)

    if entity.status == "onboarding":
        # entity_status (schema item 9): a live company is 'connected' when a Xero org is
        # linked, else 'disconnected'; there is no 'active'.
        entity.status = EntityStatus.CONNECTED if entity.xero_org_id else EntityStatus.DISCONNECTED
        _db.session.commit()

        # Start card-free Stripe trials for the modules the wizard enabled. The
        # subscription webhook keeps entity_function_map in lock-step. Best-effort:
        # a Stripe hiccup must not fail onboarding finalize.
        try:
            from blueprints.subscription.services.checkout import (
                start_trials_for_enabled_modules,
            )
            from models.db import User

            user = User.query.get(str(user_id))
            start_trials_for_enabled_modules(entity, user)
        except Exception:
            current_app.logger.exception(
                "onboarding finalize: failed to start trials for entity %s",
                entity_id,
            )

    # The trial's end date, for the All Set screen to state rather than guess.
    #
    # READ BACK from the rows rather than returned by the starter above, because this is
    # also the answer on a REVISIT: the guard skips starting anything once the entity is
    # active, and the rows are already there. Earliest across the modules — both switched
    # on share a start so they share an end, but taking the minimum is correct rather than
    # lucky.
    #
    # NULL IS A LEGITIMATE ANSWER and the caller must handle it: starting the trials is
    # best-effort, and an entity finalised before trials existed has no rows at all. The
    # screen omits the date rather than inventing one.
    trial_end = None
    try:
        from models.db import EntityModuleSubscription

        ends = [
            row.trial_end
            for row in EntityModuleSubscription.query.filter_by(
                entity_id=str(entity.id)
            ).all()
            if row.trial_end is not None
        ]
        if ends:
            trial_end = min(ends).isoformat()
    except Exception:
        current_app.logger.exception(
            "onboarding finalize: could not read the trial end for entity %s", entity_id
        )

    resp = jsonify({"status": "success", "trial_end": trial_end})
    resp.status_code = 200
    return _cors(resp)


@entity_bp.route("/api/onboarding/sales-methods", methods=["GET", "POST", "OPTIONS"])
def onboarding_sales_methods():
    """Token-authenticated petty-cash Sales Setting (onboarding Step 4).

    GET  ?entity_id=…  → {"electronic": [...], "delivery": [...]} of enabled names.
    POST {entity_id, electronic: [...], delivery: [...]} → reconciles EntitySaleSetting.

    Same JWT/CORS contract as ``onboarding_create_entity``; the underlying
    services enforce SALES_METHOD_* permission for the token's user on the
    entity, so an entity not owned by the user yields 403.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    if request.method == "GET":
        entity_id = (request.args.get("entity_id") or "").strip()
        if not entity_id:
            resp = jsonify({"error": "entity_id is required"})
            resp.status_code = 400
            return _cors(resp)
        data, status = list_sales_methods_grouped(user_id, entity_id)
        resp = jsonify(data)
        resp.status_code = status
        return _cors(resp)

    payload = request.get_json(silent=True) or {}
    entity_id = (payload.get("entity_id") or "").strip()
    if not entity_id:
        resp = jsonify({"error": "entity_id is required"})
        resp.status_code = 400
        return _cors(resp)

    data, status = replace_sales_methods(
        user_id,
        entity_id,
        payload.get("electronic") or [],
        payload.get("delivery") or [],
    )
    resp = jsonify(data)
    resp.status_code = status
    return _cors(resp)


@entity_bp.route("/api/onboarding/opening-balance", methods=["POST", "OPTIONS"])
def onboarding_opening_balance():
    """Token-authenticated petty-cash opening balance (onboarding Step 4).

    POST {entity_id, opening_date, cash_addition} → seeds the first 'opening'
    report draft for that date with the beginning amount recorded as
    cash_addition. Same JWT/CORS contract as the other onboarding endpoints.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    payload = request.get_json(silent=True) or {}
    entity_id = (payload.get("entity_id") or "").strip()
    if not entity_id:
        resp = jsonify({"error": "entity_id is required"})
        resp.status_code = 400
        return _cors(resp)

    from blueprints.report.services.shared import seed_opening_draft

    data, status = seed_opening_draft(
        user_id,
        entity_id,
        payload.get("opening_date") or payload.get("transaction_date"),
        payload.get("cash_addition", payload.get("opening_balance", 0)),
    )
    resp = jsonify(data)
    resp.status_code = status
    return _cors(resp)


@entity_bp.route("/api/onboarding/account-codes", methods=["GET", "POST", "OPTIONS"])
def onboarding_account_codes():
    """Token-authenticated petty-cash Account Code settings (onboarding Step 5).

    GET  ?entity_id=…  → Xero-sourced option lists + current selections.
    POST {entity_id, expense_codes: [...], mapping: {pettycash, deposit,
         director, cash_sale, discrepancy}} → persists the selection.

    Xero-dependent: returns 409 (connected: false) until the entity has a live
    Xero connection from Step 3. Same JWT/CORS contract as the other endpoints.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    from blueprints.entity.services.onboarding_account_codes import (
        get_account_code_options, save_account_codes)

    if request.method == "GET":
        entity_id = (request.args.get("entity_id") or "").strip()
        if not entity_id:
            resp = jsonify({"error": "entity_id is required"})
            resp.status_code = 400
            return _cors(resp)
        data, status = get_account_code_options(user_id, entity_id)
        resp = jsonify(data)
        resp.status_code = status
        return _cors(resp)

    payload = request.get_json(silent=True) or {}
    entity_id = (payload.get("entity_id") or "").strip()
    if not entity_id:
        resp = jsonify({"error": "entity_id is required"})
        resp.status_code = 400
        return _cors(resp)

    data, status = save_account_codes(
        user_id,
        entity_id,
        expense_codes=payload.get("expense_codes") or [],
        mapping=payload.get("mapping") or {},
    )
    resp = jsonify(data)
    resp.status_code = status
    return _cors(resp)


@entity_bp.route("/api/onboarding/contacts", methods=["POST", "OPTIONS"])
def onboarding_contacts():
    """Token-authenticated petty-cash contact mappings (onboarding Step 6 / Others).

    POST {entity_id, contacts: {director, cash_sale, discrepancy}} of Xero
    contact ids → persists into entity_pettycash_settings. Same JWT/CORS
    contract as the other onboarding endpoints.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    payload = request.get_json(silent=True) or {}
    entity_id = (payload.get("entity_id") or "").strip()
    if not entity_id:
        resp = jsonify({"error": "entity_id is required"})
        resp.status_code = 400
        return _cors(resp)

    from blueprints.entity.services.onboarding_account_codes import \
        save_contacts

    data, status = save_contacts(user_id, entity_id, payload.get("contacts") or {})
    resp = jsonify(data)
    resp.status_code = status
    return _cors(resp)


@entity_bp.route("/api/onboarding/contacts/create", methods=["POST", "OPTIONS"])
def onboarding_contacts_create():
    """Token-authenticated creation of a NEW Xero contact (onboarding Step 6).

    POST {entity_id, name} → creates the contact in the entity's Xero org,
    mirrors it into xero_contact_sync, and returns {"id", "label"} so the
    wizard can append it to the contact dropdown and select it. Use this when
    the desired contact doesn't exist yet; ``/api/onboarding/contacts`` only
    maps already-existing contacts. Same JWT/CORS contract as the other
    onboarding endpoints.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    payload = request.get_json(silent=True) or {}
    entity_id = (payload.get("entity_id") or "").strip()
    if not entity_id:
        resp = jsonify({"error": "entity_id is required"})
        resp.status_code = 400
        return _cors(resp)

    from blueprints.entity.services.onboarding_account_codes import \
        create_contact

    data, status = create_contact(
        user_id, entity_id, payload.get("name") or payload.get("contact_name") or ""
    )
    resp = jsonify(data)
    resp.status_code = status
    return _cors(resp)


@entity_bp.route("/api/onboarding/xero/disconnect", methods=["POST", "OPTIONS"])
def onboarding_xero_disconnect():
    """Token-authenticated Xero disconnect for the onboarding app (Step 4).

    POST {entity_id} → revokes the entity's connection on Xero
    (DELETE /connections) and clears the local connection + token state, then
    leaves the entity in the onboarding flow with Xero shown as not connected.
    Mirrors the session-authenticated ``disconnect_from_xero`` route. Same
    JWT/CORS contract as the other onboarding endpoints.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    payload = request.get_json(silent=True) or {}
    entity_id = (payload.get("entity_id") or "").strip()
    if not entity_id:
        resp = jsonify({"error": "entity_id is required"})
        resp.status_code = 400
        return _cors(resp)

    from blueprints.entity.services.onboarding_xero import \
        disconnect_entity_xero

    data, status = disconnect_entity_xero(user_id, entity_id)
    resp = jsonify(data)
    resp.status_code = status
    return _cors(resp)


@entity_bp.route("/api/onboarding/bill-codes", methods=["GET", "POST", "OPTIONS"])
def onboarding_bill_codes():
    """Token-authenticated Bill Account Code settings (onboarding Step 7).

    GET  ?entity_id=…  → Xero-sourced bill codes + current active selection.
    POST {entity_id, selected_codes: [...]} → persists which codes appear when
         adding a bill (entity_bill_account_xero.is_active).

    Xero-dependent: returns 409 (connected: false) until the entity has a live
    Xero connection from Step 3. Same JWT/CORS contract as the other endpoints.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    from blueprints.entity.services.onboarding_bill_codes import (
        get_bill_code_options, save_bill_codes)

    if request.method == "GET":
        entity_id = (request.args.get("entity_id") or "").strip()
        if not entity_id:
            resp = jsonify({"error": "entity_id is required"})
            resp.status_code = 400
            return _cors(resp)
        data, status = get_bill_code_options(user_id, entity_id)
        resp = jsonify(data)
        resp.status_code = status
        return _cors(resp)

    payload = request.get_json(silent=True) or {}
    entity_id = (payload.get("entity_id") or "").strip()
    if not entity_id:
        resp = jsonify({"error": "entity_id is required"})
        resp.status_code = 400
        return _cors(resp)

    data, status = save_bill_codes(
        user_id, entity_id, payload.get("selected_codes") or []
    )
    resp = jsonify(data)
    resp.status_code = status
    return _cors(resp)


@entity_bp.route("/api/onboarding/invite", methods=["GET", "POST", "OPTIONS"])
def onboarding_invite():
    """Token-authenticated user invitations for the onboarding app (Step 8).

    GET  ?entity_id=…  → {"invitations": [...]} of pending invites.
    POST {entity_id, email, role} → creates and emails an invitation.

    Same JWT/CORS contract as the other onboarding endpoints; the underlying
    service enforces USER_INVITE permission and role-rank limits for the
    token's user on the entity.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    from blueprints.entity.services.onboarding_invites import (list_invites,
                                                               send_invite)

    if request.method == "GET":
        entity_id = (request.args.get("entity_id") or "").strip()
        if not entity_id:
            resp = jsonify({"error": "entity_id is required"})
            resp.status_code = 400
            return _cors(resp)
        data, status = list_invites(user_id, entity_id)
        resp = jsonify(data)
        resp.status_code = status
        return _cors(resp)

    payload = request.get_json(silent=True) or {}
    entity_id = (payload.get("entity_id") or "").strip()
    if not entity_id:
        resp = jsonify({"error": "entity_id is required"})
        resp.status_code = 400
        return _cors(resp)

    data, status = send_invite(
        user_id,
        entity_id,
        payload.get("email") or "",
        payload.get("role") or "",
        payload.get("first_name") or "",
        payload.get("last_name") or "",
    )
    resp = jsonify(data)
    resp.status_code = status
    return _cors(resp)


@entity_bp.route("/api/onboarding/invite/cancel", methods=["POST", "OPTIONS"])
def onboarding_invite_cancel():
    """Token-authenticated cancellation of a pending onboarding invitation.

    POST {invitation_id} → cancels it. Same JWT/CORS contract as the other
    onboarding endpoints.
    """
    if request.method == "OPTIONS":
        return _cors(make_response("", 204))

    user_id = _user_id_from_bearer()
    if not user_id:
        resp = jsonify({"error": "Unauthorized"})
        resp.status_code = 401
        return _cors(resp)

    payload = request.get_json(silent=True) or {}
    invitation_id = (payload.get("invitation_id") or "").strip()
    if not invitation_id:
        resp = jsonify({"error": "invitation_id is required"})
        resp.status_code = 400
        return _cors(resp)

    from blueprints.entity.services.onboarding_invites import cancel_invite

    data, status = cancel_invite(user_id, invitation_id)
    resp = jsonify(data)
    resp.status_code = status
    return _cors(resp)

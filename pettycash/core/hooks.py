from __future__ import annotations

import os
import time

from flask import (flash, has_request_context, jsonify, redirect,
                   render_template, request, send_from_directory, session,
                   url_for)
from flask_login import current_user, user_logged_in, user_logged_out
from flask_wtf.csrf import CSRFError
from loguru import logger
from werkzeug.exceptions import HTTPException

from models.db import Entity
from services.auth.token_service import (auto_refresh_token,
                                         ensure_valid_token, token_expired)
from blueprints.shared.feature_flags import subscriptions_enabled
from services.user_presence import (SEEN_REFRESH_SECONDS, mark_signed_in,
                                    mark_signed_out, refresh_presence)

# Requests the browser makes on its own, which say nothing about whether a person
# is still there. The Users tab polls for the signed-in list every 20 seconds, so
# a tab left open overnight would otherwise refresh its owner's presence all night
# and keep them listed forever — defeating the whole point of last_seen_at.
PRESENCE_INERT_ENDPOINTS = frozenset({"entity.entity_settings_users_presence"})


def _wants_json():
    """True when the caller is a fetch()/XHR that will try to parse JSON.

    Match "/api/" anywhere in the path, not just as a prefix. Blueprints register
    with no url_prefix, so routes mount at their literal path — and while most sit
    at /api/..., the user_management and invitation ones are declared as
    /minty/api/... A startswith("/api") check missed exactly those, handing
    fetch() an HTML error page that then died in response.json().

    Every route containing "/api/" returns JSON today, so the wider match cannot
    catch an HTML page; if that ever stops being true, key off request.blueprint
    or the Accept/X-Requested-With clauses rather than the path.
    """
    if not has_request_context():
        return False
    return (
        "/api/" in request.path
        or request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in (request.headers.get("Accept") or "").lower()
    )


def init_app(app, db):
    @app.errorhandler(500)
    def handle_500_error(exception):
        import json
        import traceback

        error_info = {
            "error": str(exception),
            "error_type": type(exception).__name__,
            "path": request.path if request else None,
            "method": request.method if request else None,
            "user": (
                current_user.username if current_user.is_authenticated else "anonymous"),
            "user_id": current_user.id if current_user.is_authenticated else None,
            "traceback": traceback.format_exc(),
        }

        logger.error(
            f"INTERNAL SERVER ERROR: {json.dumps(error_info, indent=2)}")

        if request and "/report/expense/submit_all" in request.path:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Something went wrong on my end while submitting your expenses. Mind trying again?",
                    }),
                500,
            )

        # Friendly, non-technical fallback. The technical detail (type,
        # traceback) is already logged above; the user only sees plain guidance.
        friendly_message = (
            "Something interrupted that action. We've logged it on our end — "
            "please try again, and let us know if it keeps happening."
        )
        if _wants_json():
            return jsonify({"status": "error", "message": friendly_message}), 500
        return render_template("errors.html", error=friendly_message), 500

    # Only the 500 and CSRF handlers existed. Nothing handled 400/401/403/404/405,
    # so abort() and every @login_required rejection returned Werkzeug's HTML error
    # page — which a fetch() then died on inside response.json() as
    # "Unexpected token '<'". That string is the single most common unreadable
    # toast in the app, and it is produced here, not in the browser.
    HTTP_ERROR_COPY = {
        400: "That request didn't look right. Mind trying again?",
        401: "Your session has expired. Sign in again to keep going.",
        403: "You don't have access to that.",
        404: "I couldn't find that.",
        405: "That action isn't available here.",
        409: "Someone else changed that first. Reload and try again.",
        413: "That file is too large to upload.",
        429: "That's a lot of requests at once. Give it a moment and try again.",
    }

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        # 500 and CSRF keep their own, more specific handlers; Flask prefers those.
        code = exc.code or 500
        # Redirects are HTTPExceptions too (Werkzeug's trailing-slash
        # RequestRedirect is a 308). Turning one into a JSON body would break
        # the redirect, so only error statuses are rewritten.
        if code < 400 or not _wants_json():
            return exc
        message = HTTP_ERROR_COPY.get(
            code, "Something interrupted that action. Mind trying again?"
        )
        return jsonify({"status": "error", "message": message}), code

    @app.route("/health")
    def health_check():
        """Health check endpoint for Render"""
        return jsonify({"status": "healthy"}), 200

    @app.route("/favicon.ico")
    def favicon():
        """The tab icon for the legacy pages that declare no ``<link rel="icon">`` (and for
        error pages): browsers fall back to this path. The same file the templates link."""
        return send_from_directory(
            os.path.join(app.static_folder, "img"),
            "favicon.ico",
            mimetype="image/x-icon",
            max_age=86400,
        )

    @app.context_processor
    def inject_globals():
        def bills_app_handoff_url(entity_id):
            """Module 2 (Bills) home for this entity — JWT landing with ``next=/``."""
            if not entity_id:
                return url_for("entity.entity_list")
            if not current_user.is_authenticated:
                return url_for("auth.home")
            org = Entity.query.get(entity_id)
            if not org:
                return url_for("entity.module_selector", entity_id=entity_id)
            from blueprints.entity.routes.modules import billing_app_home_url

            return billing_app_home_url(entity_id, org, current_user.id)

        def bills_app_profile_url(entity_id, *, from_bills: bool = False):
            """The profile, opened from inside ``entity_id`` - through ``entity.open_profile``,
            which decides whether that is minty-web's (``MINTY_WEB_HUB``) or the payments
            app's, and mints the token at the click rather than at this page's render.

            ``from_bills`` records WHICH MODULE the user left, so the profile's back link
            can return them to it. It defaults to False because twelve of the sixteen
            templates that link here are the Petty Cash UI — the dashboard, its settings
            pages and every report — and only the four ``*_bills_ui.html`` ones are
            Payment Request, which pass it explicitly.

            It used to default True, which meant a Petty Cash user's profile offered
            "‹ Payments" and dropped them into a module their company may not even have
            bought.
            """
            if not entity_id:
                return url_for("entity.entity_list")
            params = {"entity_id": entity_id}
            if from_bills:
                params["from"] = "bills"
            return url_for("entity.open_profile", **params)

        def bills_app_profile_unscoped_url(*, from_bills: bool = False):
            """The profile with no company in context (the Select Company header) - through
            ``entity.open_profile``, as ``bills_app_profile_url``."""
            return url_for("entity.open_profile", **({"from": "bills"} if from_bills else {}))

        def onboarding_launch_url():
            """Launch URL into the onboarding wizard (Step 1) for the current user.

            fresh=True for the same reason ``entity.entity_create`` passes it: this
            global backs a "create entity" button (the empty-state page), so it must
            start a BRAND-NEW onboarding. Without ``?fresh=1`` the wizard rehydrates
            its single global session blob from localStorage and drops the user back
            into the last in-progress entity. A user with no entities only ever sees
            the empty state, so for them that was every attempt.

            Resuming an in-progress entity is a different path entirely: clicking the
            entity row, which passes ``entity_id`` (see ``entity.entity_detail``).
            """
            if not current_user.is_authenticated:
                return url_for("auth.home")
            from blueprints.entity.routes.create import (
                onboarding_launch_url as _onboarding_launch_url,
            )

            return _onboarding_launch_url(current_user, fresh=True)

        def is_billing_enabled(entity_id):
            """Check if billing module is enabled for the given entity."""
            if not entity_id:
                return True
            try:
                from blueprints.entity.routes.modules import _is_module_enabled
                from blueprints.entity.services.modules import MODULE_BILL

                # MODULE_BILL is PAYMENT_REQUEST since C2; the literal "BILL" this read
                # until 2026-09-18 was an unknown code, which the gate answers NO to, so
                # the Payment Settings tab and the side panel's Payment Request group were
                # never shown to anyone.
                return _is_module_enabled(str(entity_id), MODULE_BILL)
            except Exception as e:
                logger.error(f"Error checking billing enabled for entity {entity_id}: {e}")
                return True

        def is_petty_cash_enabled(entity_id):
            """Check if petty cash module is enabled for the given entity.

            Mirrors is_billing_enabled — returns True on missing entity or any
            lookup error so a transient DB hiccup never silently hides nav.
            """
            if not entity_id:
                return True
            try:
                from blueprints.entity.routes.modules import _is_module_enabled
                return _is_module_enabled(str(entity_id), "PETTY_CASH")
            except Exception as e:
                logger.error(
                    f"Error checking petty cash enabled for entity {entity_id}: {e}"
                )
                return True

        def _entity_currency_symbol():
            """ISO code of the request entity's selected currency
            (entities.currency_id -> currency_info.currency_code, e.g. "HKD").

            Money amounts across the UI render with the ISO code, not the
            symbol. The entity is taken from ``entity_id`` / ``org_id`` in the
            query string or URL view args (never the bare ``id`` view arg — on
            report routes that's a report id). Falls back to "$" when no
            entity or currency resolves. Routes that pass an explicit
            ``currency_symbol`` to render_template override this default.
            """
            # Context processors run for EVERY render_template, including the ones
            # with no request behind them — the billing emails are rendered from
            # `flask subscriptions ...` cron jobs. Touching `request` there raises,
            # and the handler below logs it at ERROR, so a perfectly healthy nightly
            # run filled the log with errors about a value the email never asks for.
            # There is no request entity to resolve outside a request; "$" is the
            # answer, not a failure.
            if not has_request_context():
                return "$"
            try:
                view_args = request.view_args or {}
                entity_id = (
                    request.args.get("entity_id")
                    or request.args.get("org_id")
                    or view_args.get("entity_id")
                    or view_args.get("org_id")
                )
                if not entity_id:
                    return "$"
                org = Entity.query.get(str(entity_id).strip())
                if org and org.currency_id:
                    from models.db import CurrencyInfo

                    currency = CurrencyInfo.query.get(org.currency_id)
                    if currency and currency.currency_code:
                        return currency.currency_code
            except Exception as exc:
                logger.error(f"currency_symbol lookup failed: {exc}")
            return "$"

        def is_readonly_for(entity_id):
            """True when the current user is a superuser viewing an entity
            they have no user_entity row on. Templates should disable any
            action buttons (create/edit/delete/publish) when this is True.
            """
            if not current_user.is_authenticated:
                return False
            try:
                from services.permission_policy import is_superuser_readonly
                return is_superuser_readonly(current_user, entity_id)
            except Exception as exc:
                logger.error(f"is_readonly_for failed entity={entity_id}: {exc}")
                return False

        return {
            "DD_CLIENT_TOKEN": os.environ.get(
                "DD_CLIENT_TOKEN", "pub8127bb0367f2b74cbba93dad6f012b90"
            ),
            "bills_app_handoff_url": bills_app_handoff_url,
            "bills_app_profile_url": bills_app_profile_url,
            "bills_app_profile_unscoped_url": bills_app_profile_unscoped_url,
            "onboarding_launch_url": onboarding_launch_url,
            "is_billing_enabled": is_billing_enabled,
            "is_petty_cash_enabled": is_petty_cash_enabled,
            "is_readonly_for": is_readonly_for,
            "currency_symbol": _entity_currency_symbol(),
            # the subscription feature switch (blueprints/shared/feature_flags.py): a template
            # branches on it where a page would otherwise quote, charge or nag
            "subscriptions_enabled": subscriptions_enabled(),
        }

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        if exception:
            db.session.rollback()
        db.session.remove()

    @app.teardown_request
    def teardown_request(exception=None):
        if exception:
            db.session.rollback()
        db.session.remove()

    @app.before_request
    def block_readonly_superuser_writes():
        """Reject write requests from superusers with no membership on the
        target entity. Backstop for routes that don't use require_permission;
        the helper-decorated routes already enforce this via has_permission.
        """
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return None
        if not current_user.is_authenticated:
            return None
        try:
            from services.permission_policy import (
                is_superuser, is_superuser_readonly,
            )
            if not is_superuser(current_user):
                return None
            # Pull entity_id from URL view args / query / form / json
            view_args = request.view_args or {}
            entity_id = (
                view_args.get("entity_id")
                or view_args.get("org_id")
                or view_args.get("id")
                or request.args.get("entity_id")
                or request.args.get("org_id")
                or request.form.get("entity_id")
                or request.form.get("org_id")
            )
            if not entity_id and request.is_json:
                payload = request.get_json(silent=True) or {}
                entity_id = payload.get("entity_id") or payload.get("org_id")
            if not entity_id:
                # Can't determine entity scope — let it through; the
                # permission/decorator layer will catch what it can.
                return None
            if is_superuser_readonly(current_user, str(entity_id)):
                logger.info(
                    "Blocked readonly-superuser write user=%s entity=%s path=%s",
                    current_user.id, entity_id, request.path,
                )
                if (
                    request.is_json
                    or request.headers.get("X-Requested-With") == "XMLHttpRequest"
                ):
                    return (
                        jsonify({
                            "status": "error",
                            "message": "You have read-only access to this entity - you can look, but not edit.",
                        }),
                        403,
                    )
                flash(
                    "You have read-only access to this entity - you can look, but not edit.",
                    "warning",
                )
                return redirect(request.referrer or url_for("entity.entity_list"))
        except Exception:
            logger.exception("block_readonly_superuser_writes failed")
        return None

    @user_logged_in.connect_via(app)
    def _reset_idle_window_on_login(sender, user, **extra):
        # Start the idle window fresh at every login (password / Xero / OTP).
        # Without this, a stale ``last_activity`` left in a reused session from
        # a previous login would make the very next request look idle and log
        # the user straight back out.
        session["last_activity"] = time.time()
        # Same signal puts the user back on Settings > Users. Hooked here rather
        # than in login.py because every sign-in path — password, Xero callback,
        # OTP, invitation accept — reaches login_user(), and only this signal
        # sees all of them.
        session["presence_seen_at"] = time.time()
        mark_signed_in(user)

    @user_logged_out.connect_via(app)
    def _clear_presence_on_logout(sender, user, **extra):
        # Fires from logout_user(), so /logout, the Xero logout and the idle
        # backstop all take the user off Settings > Users without each having to
        # remember to.
        session.pop("presence_seen_at", None)
        mark_signed_out(user)

    @app.before_request
    def before_request_middleware():
        try:
            user_id_in_session = session.get("_user_id")
            if user_id_in_session and not current_user.is_authenticated:
                logger.info(
                    "Detected expired user session (cookie present, user not "
                    "authenticated) user_id={} endpoint={}",
                    user_id_in_session,
                    request.endpoint,
                )
                # Drop the dead identity. Detecting a session that cannot be
                # used and then LEAVING it in the cookie means the very next
                # request lands in this same branch — and because the redirect
                # target below is itself guarded here, that is an infinite
                # redirect the person can only escape by clearing site data.
                # Clearing is what turns "logged out" back into a state the
                # browser can recover from on its own.
                for key in ("_user_id", "_fresh", "_id"):
                    session.pop(key, None)

                if (
                    request.headers.get("X-Requested-With") == "XMLHttpRequest"
                    or request.is_json
                ):
                    return (
                        jsonify(
                            {
                                "status": "error",
                                "code": "session_expired",
                                "message": "Your session has expired. Please login again.",
                            }),
                        401,
                    )
                # NEVER redirect the login page to itself. ``auth.home`` is
                # "/", and this hook runs on "/" too, so a redirect here is a
                # loop with no exit — the ERR_TOO_MANY_REDIRECTS every URL on
                # the domain used to give once a session went stale. ``static``
                # and unmatched URLs (endpoint is None) are exempt for the same
                # reason: neither should be turned into a trip through login.
                if request.endpoint in (None, "static", "auth.home"):
                    return None
                flash("Your session ran out. Mind logging back in?", "warning")
                return redirect(url_for("auth.home"))

            if current_user.is_authenticated:
                _refresh_presence()
                ensure_valid_token(current_user, application=app)
        except Exception:
            logger.exception(
                "Error validating/refreshing Xero token in before_request")

    def _refresh_presence():
        """Keep the signed-in user on Settings > Users, at most once a minute.

        The throttle marker lives in the session, so it costs no read: a burst of
        requests writes one row, and a browser closed mid-session simply stops
        refreshing and ages out of the presence window on its own.

        A session with no marker is either brand new or predates this feature, and
        both want the same thing — write immediately, so the person appears on the
        list on their very next page rather than a minute into it.
        """
        try:
            if request.endpoint in PRESENCE_INERT_ENDPOINTS:
                return
            entity_id = _request_entity_id()
            last = session.get("presence_seen_at")
            now_ts = time.time()
            if last and (now_ts - float(last)) < SEEN_REFRESH_SECONDS:
                # Throttled — EXCEPT when the company changed. Moving from one
                # company to another must show up at once on both lists, and a
                # minute of "still in the old one" is exactly the stale answer this
                # column was added to stop.
                if not entity_id or entity_id == session.get("presence_entity_id"):
                    return
            session["presence_seen_at"] = now_ts
            if entity_id:
                session["presence_entity_id"] = entity_id
            refresh_presence(current_user, entity_id)
        except Exception:
            logger.exception("Failed to refresh sign-in presence")

    def _request_entity_id():
        """The company this request is about, or None when it is about none.

        Read from the URL the same way the currency resolver does. Never from the
        bare ``id`` view arg — on report routes that is a report id, and stamping it
        as a company would put people in a company that does not exist.

        None is a real answer, not a failure: the entity list, the profile and the
        admin pages are about no company at all, and ``refresh_presence`` leaves the
        recorded one alone rather than treating those as leaving.
        """
        view_args = request.view_args or {}
        value = (
            view_args.get("entity_id")
            or view_args.get("org_id")
            or request.args.get("entity_id")
            or request.args.get("org_id")
        )
        return str(value).strip() if value else None

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        logger.warning(
            f"CSRF error: {getattr(error, 'description', str(error))}")
        if (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or request.is_json
        ):
            return (
                jsonify(
                    {
                        "status": "error",
                        "code": "csrf_expired",
                        "message": getattr(
                            error, "description", "CSRF token missing or expired"
                        ),
                    }
                ),
                400,
            )
        flash(
            "This form went stale while you were away. Refresh and try again?",
            "warning")
        return redirect(request.referrer or url_for("auth.home"))

    @app.after_request
    def after_request_middleware(response):
        try:
            access_expired = False
            refresh_present = False
            if current_user and getattr(
                    current_user, "is_authenticated", False):
                try:
                    expired_check = token_expired(
                        current_user, application=app)
                    access_expired = (
                        bool(expired_check)
                        if not isinstance(expired_check, tuple)
                        else False
                    )
                except Exception as exc:
                    logger.error(
                        f"Error checking access token expiry in after_request: {exc}"
                    )
                    access_expired = False

                refresh_present = bool(
                    getattr(
                        current_user,
                        "refresh_token",
                        None))

                if access_expired:
                    logger.info(
                        "Access token expired after request; attempting silent refresh."
                    )
                    try:
                        refreshed = auto_refresh_token(
                            current_user, application=app)
                        if refreshed:
                            logger.info(
                                "Silent refresh succeeded in after_request.")
                            response.headers["X-Xero-Token-Refreshed"] = "true"
                        else:
                            logger.warning(
                                "Silent refresh failed in after_request.")
                            response.headers["X-Xero-Token-Refreshed"] = "false"
                    except Exception as exc:
                        logger.error(
                            f"Exception during silent refresh in after_request: {exc}"
                        )
                        response.headers["X-Xero-Token-Refreshed"] = "error"
                else:
                    response.headers["X-Xero-Token-Refreshed"] = "false"
            else:
                response.headers["X-Xero-Token-Refreshed"] = "false"

            response.headers["X-Xero-Access-Token-Expired"] = (
                "true" if access_expired else "false"
            )
            response.headers["X-Xero-Refresh-Token-Present"] = (
                "true" if refresh_present else "false"
            )
        except Exception as exc:
            logger.error(f"Error in after_request token check: {exc}")
        return response

    return app

from __future__ import annotations

import os
import time

from flask import (flash, has_request_context, jsonify, redirect,
                   render_template, request, session, url_for)
from flask_login import current_user, user_logged_in
from flask_wtf.csrf import CSRFError
from loguru import logger

from models.db import Entity
from services.auth.token_service import (auto_refresh_token,
                                         ensure_valid_token, token_expired)


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
        # Match "/api/" anywhere in the path, not just as a prefix. Blueprints
        # register with no url_prefix, so routes mount at their literal path —
        # and while most sit at /api/..., the user_management and invitation
        # ones are declared as /minty/api/... A startswith("/api") check missed
        # exactly those, handing fetch() an HTML error page that then died in
        # response.json() as "Unexpected token '<'". Every route containing
        # "/api/" returns JSON today, so the wider match cannot catch an HTML
        # page; if that ever stops being true, key off request.blueprint or the
        # Accept/X-Requested-With clauses below rather than the path.
        wants_json = bool(request) and (
            "/api/" in request.path
            or request.is_json
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or "application/json" in (request.headers.get("Accept") or "").lower()
        )
        if wants_json:
            return jsonify({"status": "error", "message": friendly_message}), 500
        return render_template("errors.html", error=friendly_message), 500

    @app.route("/health")
    def health_check():
        """Health check endpoint for Render"""
        return jsonify({"status": "healthy"}), 200

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

        def bills_app_profile_url(entity_id, *, from_bills: bool = True):
            """Module 2 (Bills) profile page — JWT landing with ``next=/profile``."""
            if not entity_id:
                return url_for("entity.entity_list")
            if not current_user.is_authenticated:
                return url_for("auth.home")
            org = Entity.query.get(entity_id)
            if not org:
                return url_for("entity.module_selector", entity_id=entity_id)
            from blueprints.entity.routes.modules import billing_app_profile_url

            return billing_app_profile_url(
                entity_id, org, current_user.id, from_bills=from_bills
            )

        def bills_app_profile_unscoped_url(*, from_bills: bool = False):
            """Module 2 profile with no selected entity (e.g. Select Company header icon)."""
            if not current_user.is_authenticated:
                return url_for("auth.home")
            from blueprints.entity.routes.modules import (
                billing_app_profile_unscoped_url,
            )

            return billing_app_profile_unscoped_url(
                str(current_user.id), from_bills=from_bills
            )

        def onboarding_launch_url():
            """Launch URL into the onboarding wizard (Step 1) for the current user."""
            if not current_user.is_authenticated:
                return url_for("auth.home")
            from blueprints.entity.routes.create import (
                onboarding_launch_url as _onboarding_launch_url,
            )

            return _onboarding_launch_url(current_user)

        def is_billing_enabled(entity_id):
            """Check if billing module is enabled for the given entity."""
            if not entity_id:
                return True
            try:
                from blueprints.entity.routes.modules import _is_module_enabled
                return _is_module_enabled(str(entity_id), "BILL")
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

    @app.before_request
    def before_request_middleware():
        try:
            user_id_in_session = session.get("_user_id")
            if user_id_in_session and not current_user.is_authenticated:
                logger.info(
                    "Detected expired user session (cookie present, user not authenticated)"
                )
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
                flash("Your session ran out. Mind logging back in?", "warning")
                return redirect(url_for("auth.home"))

            if current_user.is_authenticated:
                ensure_valid_token(current_user, application=app)
        except Exception:
            logger.exception(
                "Error validating/refreshing Xero token in before_request")

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

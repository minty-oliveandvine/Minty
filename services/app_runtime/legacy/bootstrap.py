"""Bootstrap layer for legacy runtime.

This module centralizes legacy app construction and extension wiring so
`legacy_app.py` can be reduced to route/legacy behavior only.
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from collections import defaultdict
from typing import Any, cast

import boto3
import pytz
from botocore.config import Config
from dotenv import load_dotenv
from flask import Flask, session
from flask_cors import CORS
from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from flask_session import Session
from flask_wtf import CSRFProtect
from loguru import logger

from logging_settings import LOG_FORMAT_FIXED_WIDTH, LOG_LEVEL_DEFAULT
from models.db import db
from pettycash.core.blueprint_loader import (register_blueprints,
                                             register_compat_alias)
from pettycash.core.hooks import init_app as init_hooks

load_dotenv()


S3_BUCKET = "pettycash"


def _setup_file_logging() -> str:
    log_file_path = os.path.join(os.path.dirname(__file__), "app.log")
    if not os.path.exists(log_file_path):
        open(log_file_path, "a", encoding="utf-8").close()
    return os.path.abspath(log_file_path)


def _setup_logging() -> None:
    logger.remove()
    level = os.environ.get("LOG_LEVEL", LOG_LEVEL_DEFAULT).upper()
    fixed_width_format = LOG_FORMAT_FIXED_WIDTH

    logger.add(
        sys.stderr,
        level=level,
        format=fixed_width_format,
        backtrace=True,
        diagnose=True,
        enqueue=True,
    )

    logger.add(
        _setup_file_logging(),
        level=level,
        rotation="5 MB",
        retention="10 days",
        compression="zip",
        encoding="utf-8",
        format=fixed_width_format,
        backtrace=True,
        diagnose=True,
        enqueue=True,
    )


def _intercept_standard_logging() -> None:
    class _InterceptHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = str(record.levelno)

            frame, depth = logging.currentframe(), 2
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            logger.opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )

    intercept_handler = _InterceptHandler()

    root_logger = logging.getLogger()
    root_logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    root_logger.handlers = [intercept_handler]

    for logger_name in [
        "werkzeug",
        "requests_oauthlib",
        "xero_python",
        "urllib3",
    ]:
        logging.getLogger(logger_name).handlers = [intercept_handler]
        logging.getLogger(logger_name).propagate = False

    logging.captureWarnings(True)


def _setup_legacy_logging(application: Flask) -> None:
    _setup_logging()
    _intercept_standard_logging()
    application.logger.handlers = []
    application.logger.propagate = True
    application.logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())


def create_app():
    """Create and initialize the legacy Flask app and shared runtime objects."""

    root_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    app = Flask(
        __name__,
        template_folder=os.path.join(root_dir, "templates"),
        static_folder=os.path.join(root_dir, "static"),
    )
    register_blueprints(app)
    register_compat_alias(
        app,
        {
            "entity.entity_settings": ["entity_settings"],
            "entity.entity_settings_users": ["entity_settings_users"],
            "entity.entity_settings_entity": ["entity_settings_entity"],
            "entity.entity_settings_module": ["entity_settings_module"],
            "report.entity_report_history": ["entity_report_history"],
            "entity_report_history": ["report.entity_report_history"],
            "report.delete_report": ["delete_report"],
            "auth.validate_register": ["validate_register"],
            "xero.xero_auth": ["xero_auth"],
            "xero.xero_connect_entity": ["xero_connect_entity"],
            "xero.xero_reconnect": ["xero_reconnect"],
            "xero.disconnect_from_xero": ["disconnect_from_xero"],
            "user_management.admin": ["approve_admins"],
        },
    )
    CORS(app)
    app.config.from_pyfile(os.path.join(os.path.dirname(__file__), "..", "..", "..", "config.py"))

    _setup_legacy_logging(app)

    app.config["CLIENT_ID"] = os.environ.get("XERO_CLIENT_ID")
    app.config["CLIENT_SECRET"] = os.environ.get("XERO_CLIENT_SECRET")
    app.config["REDIRECT_URI"] = os.environ.get("XERO_REDIRECT_URI")
    app.config["SPIRE_KEY"] = os.environ.get("SPIRE_KEY")
    app.config["XERO_API_BASE_URL"] = os.environ.get("XERO_API_BASE_URL")
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_size": 15,
        "max_overflow": 5,
        "pool_timeout": 30,
        "pool_recycle": 280,
        "pool_pre_ping": True,
    }

    required_env_vars = [
        "SECRET_KEY",
        "WTF_CSRF_SECRET_KEY",
        "LOCAL_DATABASE_URI",
        "RDS_DATABASE_URI",
        "S3_BUCKET",
        "S3_KEY",
        "S3_SECRET",
        "S3_REGION",
    ]
    missing_vars = [var for var in required_env_vars if not os.environ.get(var)]
    if missing_vars:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing_vars)}")

    s3 = boto3.client("s3")
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=app.config["S3_KEY"],
        aws_secret_access_key=app.config["S3_SECRET"],
        region_name=app.config["S3_REGION"],
        endpoint_url=f"https://s3.{app.config['S3_REGION']}.backblazeb2.com",
        config=Config(signature_version="s3v4"),
    )

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
    app.config["WTF_CSRF_SECRET_KEY"] = os.environ.get("WTF_CSRF_SECRET_KEY")
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["WTF_CSRF_SSL_STRICT"] = True
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024

    app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER")
    app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", 587))
    app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
    app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
    app.config["MAIL_USE_TLS"] = True
    app.config["MAIL_USE_SSL"] = False
    app.config["MAIL_DEBUG"] = (
        os.environ.get("MAIL_DEBUG", "False").lower() == "true"
    )


    flask_env = os.environ.get("FLASK_ENV", "production")
    if flask_env == "production":
        app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("RDS_DATABASE_URI")
    else:
        app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("LOCAL_DATABASE_URI")

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    init_hooks(app, db)

    login_manager = LoginManager()
    login_manager.init_app(app)
    cast(Any, login_manager).login_view = "auth.home"

    # Per-sign-in state: reset the "already shown" flags, and stamp a new login id.
    #
    # ``logout_user()`` only removes Flask-Login's own session keys — the session
    # COOKIE survives, and with it anything else stored there. So a once-per-login
    # flag written into the session was really once-per-browser-forever: logging out
    # and back in did not clear it, and a DIFFERENT user signing in on the same
    # browser inherited the previous user's flags.
    #
    # The login id is what lets the Module 2 frontend honour the same rule. It cannot
    # read this session, so it gets the id as a JWT claim and keys its own flag by it.
    #
    # Hooking the signal rather than the login route covers every path that
    # authenticates someone — password, OTP, invitation accept, and the JWT
    # re-entry from Module 2 — which is more than any one route could.
    from flask_login import user_logged_in

    from blueprints.entity.services.modules import (LOGIN_SID_SESSION_KEY,
                                                    NOTICE_SEEN_SESSION_KEY)

    from blueprints.legal.services.gate import clear_session_agreement

    @user_logged_in.connect_via(app)
    def _reset_per_login_state(_sender, **_kwargs):
        session.pop(NOTICE_SEEN_SESSION_KEY, None)
        session[LOGIN_SID_SESSION_KEY] = uuid.uuid4().hex
        # Terms acceptance is cached in the session for speed. It MUST be
        # cleared here for exactly the reason described above: the cookie
        # outlives logout, so without this a second person signing in on the
        # same browser would inherit the first person's cached agreement and
        # walk straight past the acceptance gate.
        clear_session_agreement()

    csrf = CSRFProtect(app)
    # Cross-module sync endpoints from Module 2 (billing_backend) authenticate
    # via Bearer JWT, not session cookies — exempt them from CSRF so Django's
    # POST trigger isn't redirected to the login page.
    from blueprints.entity.routes.billing_sync import (
        billing_sync_chart_accounts,
        billing_sync_chart_if_changed,
        billing_sync_contacts_if_changed,
    )
    csrf.exempt(billing_sync_chart_accounts)
    csrf.exempt(billing_sync_chart_if_changed)
    csrf.exempt(billing_sync_contacts_if_changed)
    # Same reason: billing asks for a Xero access token with a signed Bearer
    # assertion and no cookie. Without this the CSRF handler redirects the POST to
    # the login page, `requests` follows it, and billing parses an HTML 200 as JSON.
    from blueprints.xero.routes.routes import internal_xero_access_token
    csrf.exempt(internal_xero_access_token)
    # The payer portal's writes. Module 2's profile posts these with the billing JWT and
    # no session cookie, so CSRF would redirect them to the login page and the client
    # would parse an HTML 200 as JSON. They authenticate on the bearer token, and the four
    # that DO take an id from the request check it: a payment method whose customer isn't
    # the token's payer answers "not found" (see payment_methods._owned), so a forged
    # cross-site POST reaches nothing.
    from blueprints.subscription.routes.portal import (
        my_entity_payment_method_api,
        my_invite_admin_api,
        my_payment_method_confirm_api,
        my_transfer_cancel_api,
        my_transfer_initiate_api,
        my_transfer_respond_api,
        my_payment_method_default_api,
        my_payment_method_remove_api,
        my_payment_method_setup_intent_api,
        my_payment_method_update_api,
    )
    csrf.exempt(my_invite_admin_api)
    csrf.exempt(my_payment_method_setup_intent_api)
    csrf.exempt(my_payment_method_confirm_api)
    csrf.exempt(my_payment_method_default_api)
    csrf.exempt(my_payment_method_update_api)
    csrf.exempt(my_payment_method_remove_api)
    # The per-entity nomination — the one write on this surface with billing consequences,
    # and the one that was missed when it shipped: its POST answered 400 "CSRF token is
    # missing" while its GET, being safe, went on returning 200, so the dialog read fine
    # and only Save failed. Neither of its two proofs depends on this token: the method
    # must belong to the caller's own customer (payment_methods._owned) and the caller
    # must be the entity's PAYER (_payer_of), so a forged cross-site POST nominates
    # nothing.
    csrf.exempt(my_entity_payment_method_api)
    # The handover routes. NO TEST CAN CATCH A MISSING ONE — tests/conftest.py disables
    # CSRF entirely — so these are verified by hand and any new route here must be added
    # deliberately. Each still checks the caller: the service refuses unless the token's
    # user is the entity's payer (initiate/cancel) or the offer's recipient (respond), so
    # a forged cross-site POST reaches nothing even before this.
    csrf.exempt(my_transfer_initiate_api)
    csrf.exempt(my_transfer_respond_api)
    csrf.exempt(my_transfer_cancel_api)
    # Onboarding app (separate origin) creates the entity via Bearer JWT, not a
    # session cookie — exempt it from CSRF too.
    from blueprints.entity.routes.create import (onboarding_account_codes,
                                                  onboarding_bill_codes,
                                                  onboarding_contacts,
                                                  onboarding_contacts_create,
                                                  onboarding_create_entity,
                                                  onboarding_finalize,
                                                  onboarding_invite,
                                                  onboarding_invite_cancel,
                                                  onboarding_billing_authorize,
                                                  onboarding_billing_confirm,
                                                  onboarding_billing_set_default,
                                                  onboarding_billing_setup_intent,
                                                  onboarding_modules,
                                                  onboarding_opening_balance,
                                                  onboarding_payment_method_complete,
                                                  onboarding_payment_method_setup,
                                                  onboarding_sales_methods,
                                                  onboarding_saved_step,
                                                  onboarding_update_entity,
                                                  onboarding_xero_disconnect)
    csrf.exempt(onboarding_create_entity)
    csrf.exempt(onboarding_modules)
    csrf.exempt(onboarding_payment_method_setup)
    csrf.exempt(onboarding_payment_method_complete)
    csrf.exempt(onboarding_sales_methods)
    csrf.exempt(onboarding_opening_balance)
    csrf.exempt(onboarding_account_codes)
    csrf.exempt(onboarding_contacts)
    csrf.exempt(onboarding_contacts_create)
    csrf.exempt(onboarding_invite)
    csrf.exempt(onboarding_invite_cancel)
    csrf.exempt(onboarding_bill_codes)
    csrf.exempt(onboarding_finalize)
    csrf.exempt(onboarding_saved_step)
    csrf.exempt(onboarding_update_entity)
    csrf.exempt(onboarding_xero_disconnect)
    # Step 2's "Buy now": the payer's cards, and consent to bill this entity. Same reason
    # as the payer portal's identical routes above — bearer JWT, no session cookie — and
    # the same protection without CSRF: the two that take an id from the request check it
    # against the token's own user. A payment method whose customer isn't the token's payer
    # answers "not found" (``payment_methods._owned``), and an entity the token's user is
    # not a member of answers 403 (``_entity_for_member``), so a forged cross-site POST
    # reaches nothing.
    csrf.exempt(onboarding_billing_setup_intent)
    csrf.exempt(onboarding_billing_confirm)
    csrf.exempt(onboarding_billing_set_default)
    csrf.exempt(onboarding_billing_authorize)
    # Onboarding /auth and /auth/confirm call these from a different origin
    # (port 3001) — no session cookie, so they need CSRF exemption.
    from blueprints.auth.routes.email_auth import (email_check,
                                                    email_request_code,
                                                    email_verify_code)
    csrf.exempt(email_check)
    csrf.exempt(email_request_code)
    csrf.exempt(email_verify_code)

    mail = Mail(app)
    mail.init_app(app)

    migrate = Migrate(app, db)

    app.config["SESSION_TYPE"] = os.environ.get("SESSION_TYPE", "sqlalchemy")
    app.config["SESSION_SQLALCHEMY"] = db
    app.config["SESSION_SQLALCHEMY_TABLE"] = os.environ.get(
        "SESSION_SQLALCHEMY_TABLE",
        "sessions",
    )
    app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24
    app.config["WTF_CSRF_TIME_LIMIT"] = 24 * 60 * 60
    if not app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
        app.config["SESSION_SQLALCHEMY_SCHEMA"] = "pettycashv2"
    Session(app)

    if app.config["ENV"] != "production":
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    xero_sync_status = defaultdict(lambda: {"status": "idle", "message": ""})

    tz = pytz.timezone("Asia/Hong_Kong")

    # CLI commands — manual ops knobs while a subscription admin UI doesn't exist.
    from cli.modules import modules_cli
    app.cli.add_command(modules_cli)
    # Subscription CLI: live-from-Stripe catalog inspection + access sweep.
    from cli.subscription_access import subscriptions_cli
    from cli.subscription_plans import plans_cli
    app.cli.add_command(subscriptions_cli)
    app.cli.add_command(plans_cli)

    # Re-check every published legal document against its recorded fingerprint.
    # A document edited in place silently invalidates every consent row that
    # points at it, and the damage is only discovered when a record needs to be
    # defended — years later. Checking at startup turns that into a log line on
    # the deploy that caused it. Reported, not raised: a fingerprint mismatch
    # must not take the whole app down, and the acceptance gate is what
    # actually depends on this.
    from legal.registry import verify_pinned_hashes
    verify_pinned_hashes()

    # The daily subscription pass. Nothing else ends a trial or advances
    # ``paid_through``, and Minty has no worker process to put a timer in, so it
    # runs in here. Started last, after the CLI and the blueprints, so a failure
    # to schedule cannot stop the app coming up — a web service that serves
    # nobody is worse than one that bills nobody. No-op unless
    # SUBSCRIPTION_SCHEDULER_ENABLED is set, which is why importing this app in a
    # test or a shell schedules nothing.
    from services.app_runtime.scheduler import start_scheduler
    try:
        start_scheduler(app)
    except Exception:
        logger.exception("scheduler: could not start the daily subscription pass")

    return (
        app,
        db,
        login_manager,
        csrf,
        mail,
        migrate,
        s3,
        s3_client,
        S3_BUCKET,
        xero_sync_status,
        tz,
    )

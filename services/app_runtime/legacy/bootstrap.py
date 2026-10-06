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
from services.app_runtime.mail import Mail
from flask_migrate import Migrate
from flask_session import Session
from flask_wtf import CSRFProtect
from loguru import logger

from logging_settings import LOG_FORMAT_FIXED_WIDTH, LOG_LEVEL_DEFAULT
from models.db import db
from pettycash.core.blueprint_loader import (register_blueprints,
                                             register_compat_alias)
from pettycash.core.hooks import init_app as init_hooks
from blueprints.shared import entity_ref
from blueprints.shared.schema import SCHEMA
from services.app_runtime.env import (database_url, is_development,
                                      parse_s3_url, parse_smtp_url)

load_dotenv()

#: Xero's accounting API. A constant: there is one Xero, and no environment points elsewhere.
XERO_API_BASE_URL = "https://api.xero.com/api.xro/2.0"


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
        # Variable values in tracebacks carry tokens and secrets: development only.
        diagnose=is_development(),
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
        # Variable values in tracebacks carry tokens and secrets: development only.
        diagnose=is_development(),
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
    # Before any blueprint adds a rule: the <entity:...> converter and its resolver
    # (company addresses /entity/<shortid>/<name>, blueprints/shared/entity_ref.py).
    entity_ref.init_app(app)
    register_blueprints(app)
    # Old page addresses, each a 308 to its new one (blueprints/shared/legacy_addresses.py).
    from blueprints.shared.legacy_addresses import legacy_bp
    app.register_blueprint(legacy_bp)
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
            "xero.xero_auth": ["xero_auth"],
            "xero.xero_connect_entity": ["xero_connect_entity"],
            "xero.xero_reconnect": ["xero_reconnect"],
            "user_management.admin": ["approve_admins"],
        },
    )
    CORS(app)
    app.config.from_pyfile(os.path.join(os.path.dirname(__file__), "..", "..", "..", "config.py"))

    _setup_legacy_logging(app)

    app.config["CLIENT_ID"] = os.environ.get("XERO_CLIENT_ID")
    app.config["CLIENT_SECRET"] = os.environ.get("XERO_CLIENT_SECRET")
    app.config["SPIRE_KEY"] = os.environ.get("SPIRE_KEY")
    app.config["XERO_API_BASE_URL"] = XERO_API_BASE_URL
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_size": 15,
        "max_overflow": 5,
        "pool_timeout": 30,
        "pool_recycle": 280,
        "pool_pre_ping": True,
    }

    required_env_vars = [
        "SECRET_KEY",
        "DATABASE_URL",
        "S3_URL",
    ]
    missing_vars = [var for var in required_env_vars if not os.environ.get(var)]
    if missing_vars:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing_vars)}")

    s3 = boto3.client("s3")
    s3_settings = parse_s3_url(app.config["S3_URL"])
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=s3_settings.key,
        aws_secret_access_key=s3_settings.secret,
        region_name=s3_settings.region,
        endpoint_url=s3_settings.endpoint_url,
        config=Config(signature_version="s3v4"),
    )

    # SECRET_KEY comes from config.py; Flask-WTF signs CSRF tokens with it too.
    # Secure everywhere but local development, which is plain http.
    app.config["SESSION_COOKIE_SECURE"] = not is_development()
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["WTF_CSRF_SSL_STRICT"] = True
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024

    # SMTP_URL (services/app_runtime/env.parse_smtp_url) into Flask-Mail's settings. Unset,
    # there is no server and a send fails like any other SMTP error, as it always has.
    smtp_url = os.environ.get("SMTP_URL")
    if smtp_url:
        smtp = parse_smtp_url(smtp_url)
        app.config["MAIL_SERVER"] = smtp.host
        app.config["MAIL_PORT"] = smtp.port
        app.config["MAIL_USERNAME"] = smtp.username
        app.config["MAIL_PASSWORD"] = smtp.password
        app.config["MAIL_USE_TLS"] = smtp.use_tls
        app.config["MAIL_USE_SSL"] = smtp.use_ssl
        # Seconds each SMTP step may take (services/app_runtime/mail.py; SMTP_URL's
        # ?timeout=): without it a mail server that goes quiet hangs the request or the
        # billing pass that is sending.
        app.config["MAIL_TIMEOUT"] = smtp.timeout
    else:
        app.config["MAIL_SERVER"] = None

    # DATABASE_URL, with its ?schema= popped (blueprints/shared/schema.SCHEMA reads it).
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url()

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    init_hooks(app, db)

    login_manager = LoginManager()
    login_manager.init_app(app)
    cast(Any, login_manager).login_view = "auth.home"
    # "Please log in to access this page." is news, not a success: the sign-in page (minty-web,
    # which reads flashes by category) shows it as information.
    cast(Any, login_manager).login_message_category = "info"

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
    # minty-web's My Profile saves the person's own name and email with the module JWT and no
    # session cookie (blueprints/shared/hub_api.py). The write can only ever touch the
    # token's own user row - there is no id in the request to forge.
    from blueprints.user_management.routes.me_api import my_profile_api
    csrf.exempt(my_profile_api)
    # A company's Users and Entity & Integration tabs (minty-web, phase 2): bearer only, the
    # company from ?entity= checked against membership, each action behind its permission and
    # the rank rule (blueprints/entity/routes/hub_settings.py). No session cookie is read.
    from blueprints.entity.routes.hub_settings import (hub_company_integration,
                                                       hub_company_invitation_cancel,
                                                       hub_company_invitation_resend,
                                                       hub_company_invite, hub_company_member,
                                                       hub_company_xero_disconnect)
    for hub_write in (hub_company_invite, hub_company_invitation_cancel,
                      hub_company_invitation_resend, hub_company_member,
                      hub_company_integration, hub_company_xero_disconnect):
        csrf.exempt(hub_write)
    # minty-web's Terms modal records the acceptance the same way: bearer only, and the row
    # can only ever be the token's own user's (blueprints/legal/routes/hub.py).
    from blueprints.legal.routes.hub import hub_terms_accept
    csrf.exempt(hub_terms_accept)
    # Onboarding app (separate origin) creates the entity via Bearer JWT, not a
    # session cookie — exempt it from CSRF too.
    from blueprints.entity.routes.create import (onboarding_account_codes,
                                                  onboarding_bill_codes,
                                                  onboarding_contacts,
                                                  onboarding_contacts_create,
                                                  onboarding_create_entity,
                                                  onboarding_invite,
                                                  onboarding_invite_cancel,
                                                  onboarding_modules,
                                                  onboarding_opening_balance,
                                                  onboarding_sales_methods,
                                                  onboarding_saved_step,
                                                  onboarding_update_entity,
                                                  onboarding_xero_disconnect)
    csrf.exempt(onboarding_create_entity)
    csrf.exempt(onboarding_modules)
    csrf.exempt(onboarding_sales_methods)
    csrf.exempt(onboarding_opening_balance)
    csrf.exempt(onboarding_account_codes)
    csrf.exempt(onboarding_contacts)
    csrf.exempt(onboarding_contacts_create)
    csrf.exempt(onboarding_invite)
    csrf.exempt(onboarding_invite_cancel)
    csrf.exempt(onboarding_bill_codes)
    csrf.exempt(onboarding_saved_step)
    csrf.exempt(onboarding_update_entity)
    csrf.exempt(onboarding_xero_disconnect)
    # minty-web's /login and /login/confirm call these from a different origin (port
    # 3000) — no session cookie, so they need CSRF exemption.
    from blueprints.auth.routes.email_auth import (email_request_code,
                                                    email_verify_code)
    csrf.exempt(email_request_code)
    csrf.exempt(email_verify_code)
    # The invite sign-in screen asks whether the invitee still owes the Terms; the
    # invite token rides in the POST body, never the URL. No session, read-only.
    from blueprints.legal.routes.documents import invite_terms_status
    csrf.exempt(invite_terms_status)

    # Once: Mail(app) already runs init_app, and a second call replaced the state it
    # had just registered.
    mail = Mail(app)

    migrate = Migrate(app, db)

    app.config["SESSION_TYPE"] = os.environ.get("SESSION_TYPE", "sqlalchemy")
    app.config["SESSION_SQLALCHEMY"] = db
    app.config["SESSION_SQLALCHEMY_TABLE"] = os.environ.get(
        "SESSION_SQLALCHEMY_TABLE",
        "sessions",
    )
    app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24
    app.config["WTF_CSRF_TIME_LIMIT"] = 24 * 60 * 60
    app.config["SESSION_SQLALCHEMY_SCHEMA"] = SCHEMA
    Session(app)

    if is_development():
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    xero_sync_status = defaultdict(lambda: {"status": "idle", "message": ""})

    tz = pytz.timezone("Asia/Hong_Kong")

    # CLI commands — manual ops knobs while a subscription admin UI doesn't exist.
    from cli.modules import modules_cli
    app.cli.add_command(modules_cli)
    # Expense AI: the 90-day audit purge, and the Stage 0 round-trip check that
    # has to be run from the application's own network path, not a laptop.
    from cli.expense_ai import expense_ai_cli
    app.cli.add_command(expense_ai_cli)

    # Re-check every published legal document against its recorded fingerprint.
    # A document edited in place silently invalidates every consent row that
    # points at it, and the damage is only discovered when a record needs to be
    # defended — years later. Checking at startup turns that into a log line on
    # the deploy that caused it. Reported, not raised: a fingerprint mismatch
    # must not take the whole app down, and the acceptance gate is what
    # actually depends on this.
    from legal.registry import verify_pinned_hashes
    verify_pinned_hashes()

    return (
        app,
        db,
        login_manager,
        csrf,
        mail,
        migrate,
        s3,
        s3_client,
        s3_settings.bucket,
        xero_sync_status,
        tz,
    )

"""Readers for the environment variables whose values need parsing.

No Flask or app imports: the app, the scripts and the test harness all read the same variables,
and the harness must be able to use these before (and between) app builds - conftest evicts
``services.app_runtime`` along with the rest of the app. The parsers are every backend's
(``minty_shared.config``, which the four Django APIs share); this module adds Flask's own
readers on top.

* ``APP_ENV`` - ``development`` or ``production``; anything else (or unset) is production.
* ``ACCOUNTS_API_URL`` (alias ``PETTY_CASH_URL``) - this app's own public origin; required
  outside development.
* ``DATABASE_URL`` - ``postgresql://user:pass@host:5432/db?schema=pettycashv3[&sslmode=...]``.
  The schema rides in the URL and is popped before the URL reaches a driver; every other
  query parameter is kept.
* ``S3_URL`` - ``https://KEY:SECRET@s3.<region>.backblazeb2.com/<bucket>``.
* ``SMTP_URL`` - ``smtp://user:pass@host:587`` (STARTTLS) or ``smtps://user:pass@host:465``
  (implicit SSL); ``?timeout=`` seconds (default 10), ``?tls=0`` for a local catcher.
"""

from __future__ import annotations

import os
import re

from minty_shared.config import (
    DEFAULT_S3_REGION,
    DEFAULT_SCHEMA,
    DEFAULT_SMTP_TIMEOUT,
    DatabaseUrl,
    S3Settings,
    SmtpSettings,
    app_env,
    flag,
    is_development,
    parse_database_url,
    parse_s3_url,
    parse_smtp_url,
    with_schema,
)
from minty_shared.config import preview_origin_regex as _preview_origin_regex

__all__ = [
    "DEFAULT_S3_REGION",
    "DEFAULT_SCHEMA",
    "DEFAULT_SMTP_TIMEOUT",
    "DatabaseUrl",
    "S3Settings",
    "SmtpSettings",
    "accounts_api_url",
    "app_env",
    "database_schema",
    "database_url",
    "flag",
    "is_development",
    "parse_database_url",
    "parse_s3_url",
    "parse_smtp_url",
    "preview_origin_regex",
    "url_env",
    "with_schema",
]


def url_env(name: str, default: str) -> str:
    """A sibling service's base URL, without a trailing slash."""
    return (os.environ.get(name) or default).rstrip("/")


def accounts_api_url() -> str | None:
    """This app's own public origin (``accounts-api.dailyminty.com``), without a trailing slash.

    ``ACCOUNTS_API_URL``, else ``PETTY_CASH_URL`` - the transitional alias that still means
    Flask while the other services move to the new name. Both unset is None in development
    (emails sent from a request then use its host, and the Xero callback config.py's local
    default) and a ``RuntimeError`` anywhere else: every emailed link and the Xero redirect URI
    are built on it, and a guessed address is worse than none."""
    for name in ("ACCOUNTS_API_URL", "PETTY_CASH_URL"):
        value = (os.environ.get(name) or "").strip().rstrip("/")
        if value:
            return value
    if is_development():
        return None
    raise RuntimeError("ACCOUNTS_API_URL is not set (nor its alias PETTY_CASH_URL): Flask's own public address")


def preview_origin_regex() -> re.Pattern[str] | None:
    """``PREVIEW_ORIGIN_REGEX``: the origins of a branch's preview set, or None (unset = off).

    minty-infra ``services.tf`` writes it onto ONE environment's services. A value that could
    let in any origin outside ``https://pr-…\\.dailyminty\\.com`` raises ``ValueError`` - a typo
    must never open the hand-off to another host. Every backend applies the same rule
    (``minty_shared.config``)."""
    return _preview_origin_regex(os.environ.get("PREVIEW_ORIGIN_REGEX"))


def database_url() -> str:
    """``DATABASE_URL`` as a SQLAlchemy URL. Required: there is no default database."""
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        raise RuntimeError("DATABASE_URL is not set")
    return parse_database_url(raw).sqlalchemy


def database_schema() -> str:
    """The schema every model lives in: ``DATABASE_URL``'s ``?schema=``, else ``pettycashv3``."""
    raw = os.environ.get("DATABASE_URL")
    return parse_database_url(raw).schema if raw else DEFAULT_SCHEMA

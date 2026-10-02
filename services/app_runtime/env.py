"""Readers for the environment variables whose values need parsing.

Plain Python, no Flask or app imports: the app, the scripts and the test harness all read
the same variables, and the harness must be able to use these before (and between) app
builds - conftest evicts ``services.app_runtime`` along with the rest of the app.

* ``APP_ENV`` - ``development`` or ``production``; anything else (or unset) is production.
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
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

_TRUE = {"1", "true", "yes", "on"}

#: The permanent production schema (docs/modernisation/modernisation_plan.md, 2026-09-16).
DEFAULT_SCHEMA = "pettycashv3"
DEFAULT_SMTP_TIMEOUT = 10.0
DEFAULT_S3_REGION = "us-east-1"

_PG_SCHEMES = {"postgres", "postgresql", "postgresql+psycopg2", "postgresql+psycopg"}
# The schema name is spliced into SQL as an identifier, so it is held to one.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_S3_REGION_HOST = re.compile(r"^s3\.([a-z0-9-]+)\.")


def flag(name: str, default: bool, *, blank_is_unset: bool = False) -> bool:
    """An on/off switch: ``1``/``true``/``yes``/``on`` (any case, padded) is on, anything
    else is off, and an unset variable is ``default``. ``blank_is_unset`` also gives the
    default for an empty value (the expense-AI switches always read it that way)."""
    raw = os.environ.get(name)
    if raw is None or (blank_is_unset and raw == ""):
        return default
    return raw.strip().lower() in _TRUE


def app_env() -> str:
    """``development`` only when ``APP_ENV`` says exactly that; otherwise ``production``."""
    raw = (os.environ.get("APP_ENV") or "").strip().lower()
    return "development" if raw == "development" else "production"


def is_development() -> bool:
    return app_env() == "development"


def url_env(name: str, default: str) -> str:
    """A sibling service's base URL, without a trailing slash."""
    return (os.environ.get(name) or default).rstrip("/")


# --------------------------------------------------------------------------- database


@dataclass(frozen=True)
class DatabaseUrl:
    #: for SQLAlchemy: ``postgresql+psycopg2://...``, schema removed, other params kept
    sqlalchemy: str
    #: for psycopg2.connect / psql: ``postgresql://...``, schema removed, other params kept
    libpq: str
    schema: str


def parse_database_url(url: str) -> DatabaseUrl:
    """Split a ``DATABASE_URL`` into its driver URLs and its ``?schema=`` (default
    ``pettycashv3``)."""
    parts = urlsplit(url.strip())
    if parts.scheme not in _PG_SCHEMES:
        raise ValueError(f"DATABASE_URL must be a postgresql:// URL, not {parts.scheme}://")
    query = parse_qsl(parts.query, keep_blank_values=True)
    schema = DEFAULT_SCHEMA
    kept = []
    for key, value in query:
        if key == "schema":
            schema = value or DEFAULT_SCHEMA
        else:
            kept.append((key, value))
    if not _IDENTIFIER.match(schema):
        raise ValueError(f"DATABASE_URL ?schema={schema!r} is not a plain identifier")
    rest = (parts.netloc, parts.path, urlencode(kept), parts.fragment)
    return DatabaseUrl(
        sqlalchemy=urlunsplit(("postgresql+psycopg2", *rest)),
        libpq=urlunsplit(("postgresql", *rest)),
        schema=schema,
    )


def with_schema(url: str, schema: str) -> str:
    """``url`` with its ``?schema=`` set to ``schema`` (any other params kept)."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "schema"]
    query.append(("schema", schema))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


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


# --------------------------------------------------------------------------- S3


@dataclass(frozen=True)
class S3Settings:
    endpoint_url: str
    bucket: str
    key: str
    secret: str
    region: str


def parse_s3_url(url: str) -> S3Settings:
    """``https://KEY:SECRET@s3.<region>.backblazeb2.com/<bucket>[?region=...]``.

    The region is ``?region=`` when given, else the ``s3.<region>.`` label of the host,
    else ``us-east-1``."""
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("S3_URL must look like https://KEY:SECRET@host/bucket")
    bucket = parts.path.strip("/")
    if not bucket or "/" in bucket:
        raise ValueError("S3_URL must name exactly one bucket as its path")
    host = parts.hostname
    netloc = f"{host}:{parts.port}" if parts.port else host
    region = dict(parse_qsl(parts.query)).get("region")
    if not region:
        match = _S3_REGION_HOST.match(host)
        region = match.group(1) if match else DEFAULT_S3_REGION
    return S3Settings(
        endpoint_url=f"{parts.scheme}://{netloc}",
        bucket=bucket,
        key=unquote(parts.username or ""),
        secret=unquote(parts.password or ""),
        region=region,
    )


# --------------------------------------------------------------------------- SMTP


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    username: str | None
    password: str | None
    use_tls: bool  # STARTTLS
    use_ssl: bool  # implicit TLS
    timeout: float


def parse_smtp_url(url: str) -> SmtpSettings:
    """``smtp://user:pass@host:587`` (STARTTLS; ``?tls=0`` turns it off) or
    ``smtps://user:pass@host:465`` (implicit SSL). ``?timeout=`` seconds, default 10."""
    parts = urlsplit(url.strip())
    if parts.scheme not in {"smtp", "smtps"} or not parts.hostname:
        raise ValueError("SMTP_URL must look like smtp://user:pass@host:587 or smtps://...:465")
    ssl = parts.scheme == "smtps"
    query = dict(parse_qsl(parts.query))
    timeout = DEFAULT_SMTP_TIMEOUT
    if query.get("timeout"):
        timeout = float(query["timeout"])
    starttls = not ssl and query.get("tls", "1").strip().lower() not in {"0", "false", "no", "off"}
    return SmtpSettings(
        host=parts.hostname,
        port=parts.port or (465 if ssl else 587),
        username=unquote(parts.username) if parts.username else None,
        password=unquote(parts.password) if parts.password else None,
        use_tls=starttls,
        use_ssl=ssl,
        timeout=timeout,
    )

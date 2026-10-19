"""services/app_runtime/env.py: the parsers behind APP_ENV, ACCOUNTS_API_URL, DATABASE_URL, S3_URL and
SMTP_URL - and config.py's Xero redirect URI, built on ACCOUNTS_API_URL."""

from __future__ import annotations

import pytest

from services.app_runtime import env


# --- flag ------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", " yes ", "on"])
def test_flag_on(monkeypatch, raw):
    monkeypatch.setenv("SOME_FLAG", raw)
    assert env.flag("SOME_FLAG", False) is True


@pytest.mark.parametrize("raw", ["0", "false", "off", "no", "nonsense", ""])
def test_flag_off(monkeypatch, raw):
    monkeypatch.setenv("SOME_FLAG", raw)
    assert env.flag("SOME_FLAG", True) is False


def test_flag_unset_is_the_default(monkeypatch):
    monkeypatch.delenv("SOME_FLAG", raising=False)
    assert env.flag("SOME_FLAG", True) is True
    assert env.flag("SOME_FLAG", False) is False


def test_flag_blank_can_mean_unset(monkeypatch):
    """The expense-AI switches read an empty value as "not set"; the others as off."""
    monkeypatch.setenv("SOME_FLAG", "")
    assert env.flag("SOME_FLAG", True, blank_is_unset=True) is True
    assert env.flag("SOME_FLAG", True) is False


# --- APP_ENV ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("development", "development"),
        (" Development ", "development"),
        ("production", "production"),
        ("staging", "production"),  # unknown means production
        ("", "production"),
        (None, "production"),
    ],
)
def test_app_env(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", raw)
    assert env.app_env() == expected
    assert env.is_development() is (expected == "development")


# --- DATABASE_URL ----------------------------------------------------------------------------


def test_database_url_schema_is_popped_and_other_params_kept():
    parsed = env.parse_database_url(
        "postgresql://u:p@db.example:6543/minty?sslmode=require&schema=pettycash_alt&connect_timeout=5"
    )
    assert parsed.schema == "pettycash_alt"
    assert parsed.sqlalchemy == "postgresql+psycopg2://u:p@db.example:6543/minty?sslmode=require&connect_timeout=5"
    assert parsed.libpq == "postgresql://u:p@db.example:6543/minty?sslmode=require&connect_timeout=5"


def test_database_url_schema_defaults():
    parsed = env.parse_database_url("postgresql://u@localhost/minty")
    assert parsed.schema == "pettycashv3"
    assert parsed.sqlalchemy == "postgresql+psycopg2://u@localhost/minty"


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg2", "postgresql+psycopg"])
def test_database_url_schemes_normalise(scheme):
    parsed = env.parse_database_url(f"{scheme}://u:p@h:5432/d?schema=s1")
    assert parsed.sqlalchemy == "postgresql+psycopg2://u:p@h:5432/d"
    assert parsed.libpq == "postgresql://u:p@h:5432/d"
    assert parsed.schema == "s1"


def test_database_url_keeps_an_encoded_password_encoded():
    """The drivers decode the userinfo themselves; decoding here would break on '@' or '/'."""
    from sqlalchemy.engine import make_url

    parsed = env.parse_database_url("postgresql://user:p%40ss%2Fw0rd@h/d")
    url = make_url(parsed.sqlalchemy)
    assert url.password == "p@ss/w0rd"
    assert url.username == "user" and url.host == "h" and url.database == "d"
    assert url.port is None  # the driver's default, 5432


@pytest.mark.parametrize("url", ["mysql://u@h/d", "sqlite:///x.db"])
def test_database_url_refuses_other_databases(url):
    with pytest.raises(ValueError):
        env.parse_database_url(url)


def test_database_url_refuses_a_schema_that_is_not_an_identifier():
    with pytest.raises(ValueError):
        env.parse_database_url("postgresql://u@h/d?schema=x;drop")


def test_database_url_and_schema_from_the_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u@h/d?schema=pettycash_alt")
    assert env.database_url() == "postgresql+psycopg2://u@h/d"
    assert env.database_schema() == "pettycash_alt"
    monkeypatch.delenv("DATABASE_URL")
    assert env.database_schema() == "pettycashv3"
    with pytest.raises(RuntimeError):
        env.database_url()


def test_with_schema_replaces_the_schema():
    assert env.with_schema("postgresql://u@h/d?schema=a&sslmode=require", "b") == (
        "postgresql://u@h/d?sslmode=require&schema=b"
    )


# --- S3_URL ----------------------------------------------------------------------------------


def test_s3_url_backblaze():
    s3 = env.parse_s3_url("https://KEYID:se%2Fcr%2Bet@s3.us-west-002.backblazeb2.com/pettycash")
    assert s3.endpoint_url == "https://s3.us-west-002.backblazeb2.com"
    assert s3.bucket == "pettycash"
    assert s3.key == "KEYID"
    assert s3.secret == "se/cr+et"
    assert s3.region == "us-west-002"


def test_s3_url_region_query_wins():
    s3 = env.parse_s3_url("https://k:s@s3.us-west-002.backblazeb2.com/b?region=eu-central-003")
    assert s3.region == "eu-central-003"
    assert s3.endpoint_url == "https://s3.us-west-002.backblazeb2.com"


def test_s3_url_region_default_and_port_kept():
    s3 = env.parse_s3_url("http://k:s@minio.local:9000/bucket")
    assert s3.region == "us-east-1"
    assert s3.endpoint_url == "http://minio.local:9000"


@pytest.mark.parametrize("url", ["https://k:s@host/", "https://k:s@host/a/b", "ftp://k:s@host/b"])
def test_s3_url_refuses_a_bad_shape(url):
    with pytest.raises(ValueError):
        env.parse_s3_url(url)


# --- SMTP_URL --------------------------------------------------------------------------------


def test_smtp_url_starttls():
    smtp = env.parse_smtp_url("smtp://me%40brevo:pa%3Ass@smtp-relay.brevo.com:587")
    assert (smtp.host, smtp.port) == ("smtp-relay.brevo.com", 587)
    assert (smtp.username, smtp.password) == ("me@brevo", "pa:ss")
    assert smtp.use_tls is True and smtp.use_ssl is False
    assert smtp.timeout == 10.0


def test_smtp_url_implicit_ssl_and_default_port():
    smtp = env.parse_smtp_url("smtps://u:p@mail.example?timeout=2.5")
    assert smtp.port == 465
    assert smtp.use_ssl is True and smtp.use_tls is False
    assert smtp.timeout == 2.5


def test_smtp_url_local_catcher():
    smtp = env.parse_smtp_url("smtp://localhost:1025?tls=0")
    assert smtp.port == 1025
    assert smtp.use_tls is False and smtp.use_ssl is False
    assert smtp.username is None and smtp.password is None
    assert env.parse_smtp_url("smtp://mail.example").port == 587


def test_smtp_url_refuses_another_scheme():
    with pytest.raises(ValueError):
        env.parse_smtp_url("http://mail.example")


# --- the app's configuration (tests/conftest.py's environment) --------------------------------


def test_the_app_is_configured_from_the_urls(app):
    from blueprints.report.services.s3_storage import get_s3_bucket

    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql+psycopg2://")
    assert "schema=" not in app.config["SQLALCHEMY_DATABASE_URI"]
    assert (app.config["MAIL_SERVER"], app.config["MAIL_PORT"]) == ("localhost", 587)
    assert app.config["MAIL_USE_TLS"] is True and app.config["MAIL_USE_SSL"] is False
    assert app.config["MAIL_TIMEOUT"] == 10.0
    assert app.config["MAIL_DEFAULT_SENDER"] == app.config["MAIL_FROM"] == "noreply@minty.test"
    assert app.config["ACCOUNTS_API_URL"] is None  # conftest leaves both names empty
    assert app.config["REDIRECT_URI"] == "http://localhost:8000/callback"
    assert app.config["XERO_API_BASE_URL"] == "https://api.xero.com/api.xro/2.0"
    assert app.config["APP_ENV"] == "development"
    with app.app_context():
        assert get_s3_bucket() == "dummy-bucket"


# --- ACCOUNTS_API_URL (Flask's own address; PETTY_CASH_URL is its transitional alias) ---------


def _self_url_env(monkeypatch, app_env, accounts=None, petty_cash=None):
    monkeypatch.setenv("APP_ENV", app_env)
    for name, value in (("ACCOUNTS_API_URL", accounts), ("PETTY_CASH_URL", petty_cash)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


@pytest.mark.parametrize(
    ("accounts", "petty_cash", "expected"),
    [
        ("https://accounts-api.minty.test/", "https://old.minty.test", "https://accounts-api.minty.test"),
        (None, "https://old.minty.test/", "https://old.minty.test"),  # the alias, until the rename
        ("", "https://old.minty.test", "https://old.minty.test"),  # empty counts as unset
        ("  ", "https://old.minty.test", "https://old.minty.test"),
    ],
)
@pytest.mark.parametrize("app_env", ["development", "production"])
def test_accounts_api_url_prefers_the_new_name(monkeypatch, app_env, accounts, petty_cash, expected):
    _self_url_env(monkeypatch, app_env, accounts, petty_cash)
    assert env.accounts_api_url() == expected


@pytest.mark.parametrize("blank", [None, ""])
def test_accounts_api_url_unset_is_none_in_development(monkeypatch, blank):
    _self_url_env(monkeypatch, "development", blank, blank)
    assert env.accounts_api_url() is None


@pytest.mark.parametrize("app_env", ["production", "staging"])
def test_accounts_api_url_unset_fails_loudly_outside_development(monkeypatch, app_env):
    _self_url_env(monkeypatch, app_env)
    with pytest.raises(RuntimeError, match="ACCOUNTS_API_URL.*PETTY_CASH_URL"):
        env.accounts_api_url()


def _config(monkeypatch) -> dict:
    """config.py as Flask loads it (``from_pyfile``), with no .env read over the test's env."""
    import pathlib
    import runpy

    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    return runpy.run_path(str(pathlib.Path(__file__).resolve().parents[1] / "config.py"))


@pytest.mark.parametrize(
    ("accounts", "petty_cash", "app_env", "base", "redirect"),
    [
        ("https://accounts-api.dailyminty.com", "https://pettycash.dailyminty.com", "production",
         "https://accounts-api.dailyminty.com", "https://accounts-api.dailyminty.com/callback"),
        (None, "https://pettycash.dailyminty.com/", "production",
         "https://pettycash.dailyminty.com", "https://pettycash.dailyminty.com/callback"),
        (None, None, "development", None, "http://localhost:8000/callback"),
    ],
)
def test_config_builds_the_xero_redirect_uri_on_flasks_own_address(
    monkeypatch, accounts, petty_cash, app_env, base, redirect
):
    _self_url_env(monkeypatch, app_env, accounts, petty_cash)
    config = _config(monkeypatch)
    assert config["ACCOUNTS_API_URL"] == base
    assert config["REDIRECT_URI"] == redirect


def test_config_refuses_to_load_without_flasks_address_in_production(monkeypatch):
    _self_url_env(monkeypatch, "production")
    with pytest.raises(RuntimeError, match="ACCOUNTS_API_URL"):
        _config(monkeypatch)


# --- PREVIEW_ORIGIN_REGEX --------------------------------------------------------------------

PREVIEW = r"^https://pr-[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?-(?:my|payment-request|onboarding)\.dailyminty\.com$"


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_preview_origin_regex_unset_is_off(monkeypatch, raw):
    if raw is None:
        monkeypatch.delenv("PREVIEW_ORIGIN_REGEX", raising=False)
    else:
        monkeypatch.setenv("PREVIEW_ORIGIN_REGEX", raw)
    assert env.preview_origin_regex() is None


def test_preview_origin_regex_reads_the_terraform_value(monkeypatch):
    monkeypatch.setenv("PREVIEW_ORIGIN_REGEX", f" {PREVIEW} ")
    pattern = env.preview_origin_regex()
    assert pattern.fullmatch("https://pr-feat-x-my.dailyminty.com")
    assert not pattern.fullmatch("https://pr-feat-x-www.dailyminty.com")


@pytest.mark.parametrize(
    "raw",
    [
        r".*",
        r"https://pr-.*\.dailyminty\.com$",
        r"^https://pr-.*\.dailyminty\.com",
        r"^http://pr-.*\.dailyminty\.com$",
        r"^https://pr-.*\.vercel\.app$",
        r"^https://pr-a|.*\.dailyminty\.com$",
        r"^https://pr-(.*\.dailyminty\.com$",
    ],
)
def test_a_loose_preview_origin_regex_is_refused(monkeypatch, raw):
    monkeypatch.setenv("PREVIEW_ORIGIN_REGEX", raw)
    with pytest.raises(ValueError, match="PREVIEW_ORIGIN_REGEX"):
        env.preview_origin_regex()

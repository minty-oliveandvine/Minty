"""Country/currency payload resolution for the onboarding Step 1 endpoints.

Regression cover for the asymmetry that let the onboarding wizard save a
currency but not a country: ``_resolve_currency_id`` matched on name as well as
uuid/ISO code, while ``_resolve_country_code`` gated its alpha-2 lookup on
``len == 2`` and exact-matched the registry's long name ("Hong Kong SAR China").
A wizard sending the display label "Hong Kong" therefore resolved the currency
and dropped the country, and the caller's ``if country_code:`` guard skipped the
assignment silently behind a 200.
"""

from __future__ import annotations

import uuid

import pytest

_schema_attached = False


@pytest.fixture
def db_session(app):
    global _schema_attached
    from models.db import db

    with app.app_context():
        if not _schema_attached:
            with db.engine.connect() as conn:
                try:
                    conn.execute(db.text("ATTACH DATABASE ':memory:' AS pettycashv2"))
                    conn.commit()
                except Exception:
                    pass
            _schema_attached = True

        db.session.expire_on_commit = False
        db.create_all()
        _seed_registries(db)
        yield db
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            try:
                db.session.execute(table.delete())
            except Exception:
                pass
        db.session.commit()


def _seed_registries(db):
    """Seed the registry rows the resolvers read, mirroring the migrations."""
    from models.db import CountryInfo, CurrencyInfo

    hkd_id = str(uuid.uuid4())
    db.session.add(
        CurrencyInfo(id=hkd_id, currency_code="HKD", currency_name="Hong Kong Dollar")
    )
    db.session.add_all(
        [
            # The long registry form is what a display label must match against.
            CountryInfo(
                country_code="HK",
                alpha3_code="HKG",
                country_name_en="Hong Kong SAR China",
                currency_id=hkd_id,
            ),
            # Two countries sharing a prefix, so the unique-prefix fallback has
            # something ambiguous to refuse.
            CountryInfo(
                country_code="GS",
                alpha3_code="SGS",
                country_name_en="South Georgia & South Sandwich Islands",
            ),
            CountryInfo(
                country_code="KR", alpha3_code="KOR", country_name_en="South Korea"
            ),
        ]
    )
    db.session.commit()
    return hkd_id


@pytest.mark.parametrize(
    "value, expected",
    [
        ("HK", "HK"),                    # alpha-2, the wizard's normal payload
        ("hk", "HK"),                    # case-insensitive
        ("HKG", "HK"),                   # alpha-3
        ("Hong Kong SAR China", "HK"),   # exact registry name
        ("hong kong sar china", "HK"),   # name, case-insensitive
        ("Hong Kong", "HK"),             # THE BUG: display label, unique prefix
        ("", ""),                        # nothing supplied
        ("Atlantis", ""),                # no match
        ("South", ""),                   # ambiguous prefix -> refuse, don't guess
    ],
)
def test_resolve_country_code(app, db_session, value, expected):
    from blueprints.entity.routes.create import _resolve_country_code

    with app.app_context():
        assert _resolve_country_code(value) == expected


def test_resolve_country_code_wildcards_are_escaped(app, db_session):
    """A user-supplied % must not widen the prefix match into a match-all."""
    from blueprints.entity.routes.create import _resolve_country_code

    with app.app_context():
        assert _resolve_country_code("%") == ""
        assert _resolve_country_code("Hong%") == ""
        assert _resolve_country_code("_ong Kong") == ""


def test_country_and_currency_accept_the_same_payload_forms(app, db_session):
    """The two dropdowns submit together; both must resolve the same shapes."""
    from blueprints.entity.routes.create import (_resolve_country_code,
                                                 _resolve_currency_id)

    with app.app_context():
        # Codes.
        assert _resolve_country_code("HK") == "HK"
        assert _resolve_currency_id("HKD") != ""
        # Display names — the form that used to resolve for currency only.
        assert _resolve_country_code("Hong Kong") == "HK"
        assert _resolve_currency_id("Hong Kong Dollar") != ""

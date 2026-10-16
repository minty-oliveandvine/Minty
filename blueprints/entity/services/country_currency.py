"""The country and currency a company's settings offer (Petty Cash Settings, and minty-web's
Entity & Integration tab through ``routes/hub_settings.py``)."""

from __future__ import annotations

import uuid

from models.db import CountryInfo, CurrencyInfo, db


def country_currency_choices(org):
    """Build the country / currency dropdown lists and the entity's current
    selection in each.

    Returns ``(country_code, currencies, selected_country, selected_currency)``.
    Keys mirror the old pycountry shape so the existing suggestion JS keeps
    working.

    Only ``is_active`` registry rows are listed: country_info and
    currency_info are seeded with the full ISO lists (~250 countries, ~170
    currencies) and the flag narrows them to what this deployment operates in.

    The entity's CURRENT row is always included even when it has since been
    deactivated. Without that, ``selected_*`` would fall to None and the
    template renders the hidden country_code / currency_id inputs as
    ``value=""`` (``settings_entity.html``), so the form shows a blank
    country for an entity that has one. The save path skips empty values
    (xero_account_mapping_post.py:44) so nothing is overwritten, but a blank
    field reads as "unset" and invites someone to change it. Deactivating a
    currency must not silently rewrite the entities already using it.

    Countries order by display_order then name, so common ones can be floated
    above the alphabetical tail; currency_info has no display_order column.
    """
    countries_q = (
        CountryInfo.query.filter(
            db.or_(
                CountryInfo.is_active.is_(True),
                CountryInfo.country_code == org.country_code,
            )
        )
        .order_by(CountryInfo.display_order, CountryInfo.country_name_en)
    )
    country_code = [
        {
            "country_code": c.country_code,
            "country_name": c.country_name_en,
        }
        for c in countries_q.all()
    ]

    currencies_q = (
        CurrencyInfo.query.filter(
            db.or_(
                CurrencyInfo.is_active.is_(True),
                CurrencyInfo.id == org.currency_id,
            )
        )
        .order_by(CurrencyInfo.currency_name)
    )
    currencies = [
        {"currency_id": c.id, "currency_name": c.currency_name}
        for c in currencies_q.all()
    ]

    selected_country = next(
        (c for c in country_code if c["country_code"] == org.country_code), None
    )
    selected_currency = next(
        (c for c in currencies if c["currency_id"] == org.currency_id), None
    )
    return country_code, currencies, selected_country, selected_currency


def checked_country_currency(data) -> tuple[dict, str | None]:
    """The ``country_code`` / ``currency_id`` a save sent, checked against the registries:
    ``(fields for apply_country_currency_selection, None)``, or ``({}, the sentence that refuses
    them)``. An unknown country or currency is refused, never skipped. Shared by minty-web's
    Entities & Integration save and the Petty Cash API's settings save."""
    fields = {}
    country_code = str(data.get("country_code") or "").strip().upper()
    if country_code:
        if db.session.get(CountryInfo, country_code) is None:
            return {}, "Pick one of the countries offered."
        fields["country_code"] = country_code
    currency_id = str(data.get("currency_id") or "").strip()
    if currency_id:
        try:
            uuid.UUID(currency_id)
        except ValueError:
            return {}, "Pick one of the currencies offered."
        if db.session.get(CurrencyInfo, currency_id) is None:
            return {}, "Pick one of the currencies offered."
        fields["currency_id"] = currency_id
    return fields, None

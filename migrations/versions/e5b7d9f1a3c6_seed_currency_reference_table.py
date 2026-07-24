"""Seed currency_info from the 167-row currency reference table (+ SYP = 168).

Brings ``pettycashv2.currency_info`` to EXACTLY the 168 rows below:

  * ``Code`` -> ``currency_code``, ``Currency Name`` -> ``currency_name``,
    both verbatim — including the ``(expiring)`` suffixes and accented
    characters (Colón, Króna, São Tomé, Guaraní, Bolívar);
  * ``symbol`` is set to '' on every row;
  * everything else takes the table defaults (``id`` gen_random_uuid(),
    ``decimal_places`` 2, ``is_active`` true, created_at / updated_at).

Rows already present keep their existing ``id``, so entities / country_info
references survive; only the name and symbol are refreshed. Rows not in the
list are deleted, so the table matches the reference set exactly. A deletion
can touch references:

  * ``entities.currency_id`` has no ON DELETE action, so those entities are
    set to NULL first (each one is logged — nothing is dropped silently);
  * ``country_info.currency_id`` is ON DELETE SET NULL and
    ``entity_bill_currency.currency_info_id`` is ON DELETE CASCADE; both are
    counted and logged before the delete.

Idempotent — re-running converges to the same 168 rows.

Requires the rebuilt registry schema (c8e0a2b4d6f8: id / currency_code /
currency_name / symbol); it raises rather than guess if run earlier.

Revision ID: e5b7d9f1a3c6
Revises: d0f2b4c6e8a0
Create Date: 2026-07-21 00:00:00.000000

"""

from alembic import op
from sqlalchemy import text

revision = "e5b7d9f1a3c6"
down_revision = "d0f2b4c6e8a0"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# (currency_code, currency_name) — verbatim from the reference table, in its
# order; SYP is appended as the 168th row.
CURRENCIES = [
    ("AED", "United Arab Emirates Dirham"),
    ("AFN", "Afghan Afghani"),
    ("ALL", "Albanian Lek"),
    ("AMD", "Armenian Dram"),
    ("ANG", "Netherlands Antillean Guilder"),
    ("AOA", "Angolan Kwanza"),
    ("ARS", "Argentine Peso"),
    ("AUD", "Australian Dollar"),
    ("AWG", "Aruban Guilder"),
    ("AZN", "Azerbaijani Manat"),
    ("BAM", "Bosnia and Herzegovina Convertible Mark"),
    ("BBD", "Barbadian Dollar"),
    ("BDT", "Bangladeshi Taka"),
    ("BGN", "Bulgarian Lev"),
    ("BHD", "Bahraini Dinar"),
    ("BIF", "Burundian Franc"),
    ("BMD", "Bermudian Dollar"),
    ("BND", "Brunei Dollar"),
    ("BOB", "Bolivian Boliviano"),
    ("BRL", "Brazilian Real"),
    ("BSD", "Bahamian Dollar"),
    ("BTN", "Bhutanese Ngultrum"),
    ("BWP", "Botswana Pula"),
    ("BYN", "Belarusian Ruble"),
    ("BYR", "Belarusian Ruble (expiring)"),
    ("BZD", "Belize Dollar"),
    ("CAD", "Canadian Dollar"),
    ("CDF", "Congolese Franc"),
    ("CHF", "Swiss Franc"),
    ("CLF", "Unidad de Fomento"),
    ("CLP", "Chilean Peso"),
    ("CNY", "Chinese Yuan"),
    ("COP", "Colombian Peso"),
    ("CRC", "Costa Rican Colón"),
    ("CUC", "Cuban Convertible Peso (expiring)"),
    ("CUP", "Cuban Peso"),
    ("CVE", "Cape Verdean Escudo"),
    ("CZK", "Czech Koruna"),
    ("DJF", "Djiboutian Franc"),
    ("DKK", "Danish Krone"),
    ("DOP", "Dominican Peso"),
    ("DZD", "Algerian Dinar"),
    ("EEK", "Estonian Kroon (expiring)"),
    ("EGP", "Egyptian Pound"),
    ("ERN", "Eritrean Nakfa"),
    ("ETB", "Ethiopian Birr"),
    ("EUR", "Euro"),
    ("FJD", "Fijian Dollar"),
    ("FKP", "Falkland Island Pound"),
    ("GBP", "British Pound"),
    ("GEL", "Georgian Lari"),
    ("GHS", "Ghanaian Cedi"),
    ("GIP", "Gibraltar Pound"),
    ("GMD", "Gambian Dalasi"),
    ("GNF", "Guinean Franc"),
    ("GTQ", "Guatemalan Quetzal"),
    ("GYD", "Guyanese Dollar"),
    ("HKD", "Hong Kong Dollar"),
    ("HNL", "Honduran Lempira"),
    ("HRK", "Croatian Kuna"),
    ("HTG", "Haitian Gourde"),
    ("HUF", "Hungarian Forint"),
    ("IDR", "Indonesian Rupiah"),
    ("ILS", "Israeli New Sheqel"),
    ("INR", "Indian Rupee"),
    ("IQD", "Iraqi Dinar"),
    ("IRR", "Iranian Rial"),
    ("ISK", "Icelandic Króna"),
    ("JMD", "Jamaican Dollar"),
    ("JOD", "Jordanian Dinar"),
    ("JPY", "Japanese Yen"),
    ("KES", "Kenyan Shilling"),
    ("KGS", "Kyrgyzstani Som"),
    ("KHR", "Cambodian Riel"),
    ("KMF", "Comorian Franc"),
    ("KPW", "North Korean Won"),
    ("KRW", "South Korean Won"),
    ("KWD", "Kuwaiti Dinar"),
    ("KYD", "Cayman Islands Dollar"),
    ("KZT", "Kazakhstani Tenge"),
    ("LAK", "Lao Kip"),
    ("LBP", "Lebanese Pound"),
    ("LKR", "Sri Lankan Rupee"),
    ("LRD", "Liberian Dollar"),
    ("LSL", "Lesotho Loti"),
    ("LTL", "Lithuanian Litas (expiring)"),
    ("LVL", "Latvian Lats (expiring)"),
    ("LYD", "Libyan Dinar"),
    ("MAD", "Moroccan Dirham"),
    ("MDL", "Moldovan Leu"),
    ("MGA", "Malagasy Ariary"),
    ("MKD", "Macedonian Denar"),
    ("MMK", "Myanmar Kyat"),
    ("MNT", "Mongolian Tugrik"),
    ("MOP", "Macanese Pataca"),
    ("MRO", "Mauritanian Ouguiya (expiring)"),
    ("MRU", "Mauritanian Ouguiya"),
    ("MUR", "Mauritian Rupee"),
    ("MVR", "Maldivian Rufiyaa"),
    ("MWK", "Malawian Kwacha"),
    ("MXN", "Mexican Peso"),
    ("MXV", "Mexican Unidad de Inversion (UDI)"),
    ("MYR", "Malaysian Ringgit"),
    ("MZN", "Mozambican Metical"),
    ("NAD", "Namibian Dollar"),
    ("NGN", "Nigerian Naira"),
    ("NIO", "Nicaraguan Córdoba"),
    ("NOK", "Norwegian Krone"),
    ("NPR", "Nepalese Rupee"),
    ("NZD", "New Zealand Dollar"),
    ("OMR", "Omani Rial"),
    ("PAB", "Panamanian Balboa"),
    ("PEN", "Peru Sol"),
    ("PGK", "Papua New Guinean Kina"),
    ("PHP", "Philippine Peso"),
    ("PKR", "Pakistani Rupee"),
    ("PLN", "Polish Zloty"),
    ("PYG", "Paraguayan Guaraní"),
    ("QAR", "Qatari Riyal"),
    ("RON", "Romanian Leu"),
    ("RSD", "Serbian Dinar"),
    ("RUB", "Russian Ruble"),
    ("RWF", "Rwandan Franc"),
    ("SAR", "Saudi Riyal"),
    ("SBD", "Solomon Islands Dollar"),
    ("SCR", "Seychellois Rupee"),
    ("SDG", "Sudanese Pound"),
    ("SEK", "Swedish Krona"),
    ("SGD", "Singapore Dollar"),
    ("SHP", "Saint Helenian Pound"),
    ("SKK", "Slovak Koruna"),
    ("SLE", "Sierra Leonean Leone"),
    ("SLL", "Sierra Leonean Leone (expiring)"),
    ("SOS", "Somali Shilling"),
    ("SRD", "Surinamese Dollar"),
    ("STD", "São Tomé and Príncipe Dobra (expiring)"),
    ("STN", "São Tomé and Príncipe Dobra"),
    ("SVC", "Salvadoran Colón"),
    ("SZL", "Swazi Lilangeni"),
    ("THB", "Thai Baht"),
    ("TJS", "Tajikistani Somoni"),
    ("TMT", "Turkmenistani Manat"),
    ("TND", "Tunisian Dinar"),
    ("TOP", "Tongan Pa'anga"),
    ("TRY", "Turkish Lira"),
    ("TTD", "Trinidad and Tobago Dollar"),
    ("TWD", "Taiwanese New Dollar"),
    ("TZS", "Tanzanian Shilling"),
    ("UAH", "Ukrainian Hryvnia"),
    ("UGX", "Ugandan Shilling"),
    ("USD", "United States Dollar"),
    ("UYU", "Uruguayan Peso"),
    ("UZS", "Uzbekistani Som"),
    ("VEF", "Venezuelan Bolívar Fuerte (expiring)"),
    ("VES", "Venezuelan Bolívar Soberano"),
    ("VND", "Vietnamese Dong"),
    ("VUV", "Vanuatu Vatu"),
    ("WST", "Samoan Tala"),
    ("XAF", "Central African CFA Franc"),
    ("XCD", "East Caribbean Dollar"),
    ("XOF", "West African CFA Franc"),
    ("XPF", "CFP Franc"),
    ("YER", "Yemeni Rial"),
    ("ZAR", "South African Rand"),
    ("ZMK", "Zambian Kwacha (expiring)"),
    ("ZMW", "Zambian Kwacha"),
    ("ZWD", "Zimbabwean Dollar"),
    # Added on top of the reference table.
    ("SYP", "Syrian Pound"),
]


def upgrade():
    bind = op.get_bind()

    codes = [c for c, _ in CURRENCIES]
    if len(CURRENCIES) != 168 or len(set(codes)) != 168:
        raise RuntimeError(
            f"seed list must hold 168 unique codes, got {len(CURRENCIES)} "
            f"rows / {len(set(codes))} unique"
        )

    # This seed writes the rebuilt registry shape only.
    cols = {
        r[0]
        for r in bind.execute(text(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_schema = '{SCHEMA}' AND table_name = 'currency_info'"
        ))
    }
    missing = {"id", "currency_code", "currency_name", "symbol"} - cols
    if missing:
        raise RuntimeError(
            f"currency_info is missing {sorted(missing)} — run the registry "
            "rebuild (c8e0a2b4d6f8) before this seed."
        )

    # 1. Upsert every reference row: name verbatim, empty symbol, defaults.
    inserted = refreshed = 0
    for code, name in CURRENCIES:
        touched = bind.execute(
            text(
                f"UPDATE {SCHEMA}.currency_info "
                "SET currency_name = :name, symbol = '', decimal_places = 2, "
                "    is_active = true, updated_at = CURRENT_TIMESTAMP "
                "WHERE trim(currency_code) = :code"
            ),
            {"name": name, "code": code},
        ).rowcount
        if touched:
            refreshed += touched
        else:
            bind.execute(
                text(
                    f"INSERT INTO {SCHEMA}.currency_info "
                    "(currency_code, currency_name, symbol) "
                    "VALUES (:code, :name, '')"
                ),
                {"code": code, "name": name},
            )
            inserted += 1

    # 2. Drop anything outside the reference set, clearing references first.
    extras = [
        r[0]
        for r in bind.execute(
            text(
                f"SELECT trim(currency_code) FROM {SCHEMA}.currency_info "
                "WHERE trim(currency_code) <> ALL(:codes) ORDER BY 1"
            ),
            {"codes": codes},
        )
    ]
    has_bill_currency = bind.execute(text(
        f"SELECT to_regclass('{SCHEMA}.entity_bill_currency')"
    )).scalar() is not None

    for code in extras:
        cid = bind.execute(
            text(
                f"SELECT id FROM {SCHEMA}.currency_info "
                "WHERE trim(currency_code) = :code"
            ),
            {"code": code},
        ).scalar()

        # entities has no ON DELETE action — clear it or the DELETE fails.
        entity_ids = [
            r[0]
            for r in bind.execute(
                text(
                    f"SELECT id FROM {SCHEMA}.entities WHERE currency_id = :cid"
                ),
                {"cid": cid},
            )
        ]
        if entity_ids:
            bind.execute(
                text(
                    f"UPDATE {SCHEMA}.entities SET currency_id = NULL "
                    "WHERE currency_id = :cid"
                ),
                {"cid": cid},
            )
            print(
                f"WARNING: {code} is used by {len(entity_ids)} entit"
                f"{'y' if len(entity_ids) == 1 else 'ies'} "
                f"({', '.join(entity_ids)}) — currency cleared to NULL"
            )

        countries = bind.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.country_info "
                "WHERE currency_id = :cid"
            ),
            {"cid": cid},
        ).scalar()
        if countries:
            print(
                f"note: {code} unlinked from {countries} countr"
                f"{'y' if countries == 1 else 'ies'} (FK is ON DELETE SET NULL)"
            )

        if has_bill_currency:
            mappings = bind.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.entity_bill_currency "
                    "WHERE currency_info_id::text = CAST(:cid AS text)"
                ),
                {"cid": str(cid)},
            ).scalar()
            if mappings:
                print(
                    f"note: {code} removes {mappings} entity_bill_currency "
                    "row(s) (FK is ON DELETE CASCADE)"
                )

        bind.execute(
            text(f"DELETE FROM {SCHEMA}.currency_info WHERE id = :cid"),
            {"cid": cid},
        )

    total = bind.execute(
        text(f"SELECT count(*) FROM {SCHEMA}.currency_info")
    ).scalar()
    print(
        f"currency_info seed: {inserted} inserted, {refreshed} refreshed, "
        f"{len(extras)} deleted ({', '.join(extras) if extras else 'none'}) "
        f"-> {total} rows"
    )
    if total != 168:
        raise RuntimeError(f"expected 168 rows after seed, found {total}")


def downgrade():
    # Intentional no-op — reverting would delete reference data that entities
    # and country_info point at, with no earlier row set to restore.
    pass

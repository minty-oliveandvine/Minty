"""Currency registry uuid seed + entities.currency_id FK.

Replays the currency half of the registry work as a migration, against the
ORIGINAL local schema (currency_info: currency_id varchar(10) PK,
currency_name, currency_symbol, iso_code UNIQUE; entities.currency_code
varchar(10) holding ISO codes):

  1. widen ``currency_info.currency_id`` to varchar(36) (altered in place —
     the table is never dropped, so row level security / ownership survive);
  2. seed/refresh all 156 currencies keyed by ``iso_code`` — new rows get a
     Python-generated uuid4 primary key, existing rows keep theirs;
  3. convert any legacy non-uuid primary keys (e.g. rows keyed by their ISO
     code) to uuid4;
  4. rename ``entities.currency_code`` -> ``currency_id``, widen to
     varchar(36), remap each entity's ISO value ('HKD') to the matching
     currency's uuid via ``iso_code``, NULL anything unresolvable, and add
     ``fk_entities_currency_id``;
  5. remap a pre-existing ``country_info.currency_id`` the same way. On a
     database that already carries a populated country_info (a restored dump
     or 0001_full_schema, rather than the a2c4e6b8d0f2 seed that runs after
     this migration), that column still holds ISO codes; without this step
     re-adding its FK in 6 fails with "Key (currency_id)=(EUR) is not present
     in table currency_info";
  6. re-create any foreign keys that referenced currency_info (captured
     before the changes, e.g. country_info.currency_id).

Idempotent — re-running is a no-op: the upsert keys on iso_code and keeps
existing uuids, the pk conversion only touches non-uuid keys, the rename is
guarded, already-remapped uuid values match no iso_code, and constraint adds
are existence-checked.

Must run BEFORE a2c4e6b8d0f2 (the country_info rebuild + seed resolves each
country's currency through currency_info.iso_code -> the uuid PK this
migration establishes).

Revision ID: c6e8a0b2d4f6
Revises: d8e0f2a4b6c8
Create Date: 2026-07-16 00:00:00.000000

"""

import uuid

from alembic import op
from sqlalchemy import text

revision = "c6e8a0b2d4f6"
down_revision = "d8e0f2a4b6c8"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

UUID_RE = (
    "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    "[0-9a-f]{4}-[0-9a-f]{12}$"
)

# (iso_code, currency_name, currency_symbol)
# Names from ISO 4217 (iso4217 package); retired codes (ANG, HRK, ZWL)
# carry their standard names.
CURRENCIES = [
    ('AED', 'UAE Dirham', 'د.إ'),
    ('AFN', 'Afghani', '؋'),
    ('ALL', 'Lek', 'L'),
    ('AMD', 'Armenian Dram', '֏'),
    ('ANG', 'Netherlands Antillean Guilder', 'ƒ'),
    ('AOA', 'Kwanza', 'Kz'),
    ('ARS', 'Argentine Peso', '$'),
    ('AUD', 'Australian Dollar', 'A$'),
    ('AWG', 'Aruban Florin', 'ƒ'),
    ('AZN', 'Azerbaijan Manat', '₼'),
    ('BAM', 'Convertible Mark', 'KM'),
    ('BBD', 'Barbados Dollar', 'Bds$'),
    ('BDT', 'Taka', '৳'),
    ('BGN', 'Bulgarian Lev', 'лв'),
    ('BHD', 'Bahraini Dinar', '.د.ب'),
    ('BIF', 'Burundi Franc', 'FBu'),
    ('BMD', 'Bermudian Dollar', '$'),
    ('BND', 'Brunei Dollar', 'B$'),
    ('BOB', 'Boliviano', 'Bs.'),
    ('BRL', 'Brazilian Real', 'R$'),
    ('BSD', 'Bahamian Dollar', 'B$'),
    ('BTN', 'Ngultrum', 'Nu.'),
    ('BWP', 'Pula', 'P'),
    ('BYN', 'Belarusian Ruble', 'Br'),
    ('BZD', 'Belize Dollar', 'BZ$'),
    ('CAD', 'Canadian Dollar', 'C$'),
    ('CDF', 'Congolese Franc', 'FC'),
    ('CHF', 'Swiss Franc', 'CHF'),
    ('CLP', 'Chilean Peso', '$'),
    ('CNY', 'Yuan Renminbi', '¥'),
    ('COP', 'Colombian Peso', '$'),
    ('CRC', 'Costa Rican Colon', '₡'),
    ('CUP', 'Cuban Peso', '$'),
    ('CVE', 'Cabo Verde Escudo', '$'),
    ('CZK', 'Czech Koruna', 'Kč'),
    ('DJF', 'Djibouti Franc', 'Fdj'),
    ('DKK', 'Danish Krone', 'kr'),
    ('DOP', 'Dominican Peso', 'RD$'),
    ('DZD', 'Algerian Dinar', 'دج'),
    ('EGP', 'Egyptian Pound', '£'),
    ('ERN', 'Nakfa', 'Nfk'),
    ('ETB', 'Ethiopian Birr', 'Br'),
    ('EUR', 'Euro', '€'),
    ('FJD', 'Fiji Dollar', 'FJ$'),
    ('FKP', 'Falkland Islands Pound', '£'),
    ('GBP', 'Pound Sterling', '£'),
    ('GEL', 'Lari', '₾'),
    ('GHS', 'Ghana Cedi', '₵'),
    ('GIP', 'Gibraltar Pound', '£'),
    ('GMD', 'Dalasi', 'D'),
    ('GNF', 'Guinean Franc', 'FG'),
    ('GTQ', 'Quetzal', 'Q'),
    ('GYD', 'Guyana Dollar', 'G$'),
    ('HKD', 'Hong Kong Dollar', 'HK$'),
    ('HNL', 'Lempira', 'L'),
    ('HRK', 'Croatian Kuna', 'kn'),
    ('HTG', 'Gourde', 'G'),
    ('HUF', 'Forint', 'Ft'),
    ('IDR', 'Rupiah', 'Rp'),
    ('ILS', 'New Israeli Sheqel', '₪'),
    ('INR', 'Indian Rupee', '₹'),
    ('IQD', 'Iraqi Dinar', 'ع.د'),
    ('IRR', 'Iranian Rial', '﷼'),
    ('ISK', 'Iceland Krona', 'kr'),
    ('JMD', 'Jamaican Dollar', 'J$'),
    ('JOD', 'Jordanian Dinar', 'د.ا'),
    ('JPY', 'Yen', '¥'),
    ('KES', 'Kenyan Shilling', 'KSh'),
    ('KGS', 'Som', 'с'),
    ('KHR', 'Riel', '៛'),
    ('KMF', 'Comorian Franc', 'CF'),
    ('KPW', 'North Korean Won', '₩'),
    ('KRW', 'Won', '₩'),
    ('KWD', 'Kuwaiti Dinar', 'د.ك'),
    ('KYD', 'Cayman Islands Dollar', '$'),
    ('KZT', 'Tenge', '₸'),
    ('LAK', 'Lao Kip', '₭'),
    ('LBP', 'Lebanese Pound', 'ل.ل'),
    ('LKR', 'Sri Lanka Rupee', 'Rs'),
    ('LRD', 'Liberian Dollar', 'L$'),
    ('LSL', 'Loti', 'L'),
    ('LYD', 'Libyan Dinar', 'ل.د'),
    ('MAD', 'Moroccan Dirham', 'د.م.'),
    ('MDL', 'Moldovan Leu', 'L'),
    ('MGA', 'Malagasy Ariary', 'Ar'),
    ('MKD', 'Denar', 'ден'),
    ('MMK', 'Kyat', 'K'),
    ('MNT', 'Tugrik', '₮'),
    ('MOP', 'Pataca', 'MOP$'),
    ('MRU', 'Ouguiya', 'UM'),
    ('MUR', 'Mauritius Rupee', '₨'),
    ('MVR', 'Rufiyaa', '.ރ'),
    ('MWK', 'Malawi Kwacha', 'MK'),
    ('MXN', 'Mexican Peso', '$'),
    ('MYR', 'Malaysian Ringgit', 'RM'),
    ('MZN', 'Mozambique Metical', 'MT'),
    ('NAD', 'Namibia Dollar', 'N$'),
    ('NGN', 'Naira', '₦'),
    ('NIO', 'Cordoba Oro', 'C$'),
    ('NOK', 'Norwegian Krone', 'kr'),
    ('NPR', 'Nepalese Rupee', '₨'),
    ('NZD', 'New Zealand Dollar', 'NZ$'),
    ('OMR', 'Rial Omani', 'ر.ع.'),
    ('PAB', 'Balboa', 'B/.'),
    ('PEN', 'Sol', 'S/'),
    ('PGK', 'Kina', 'K'),
    ('PHP', 'Philippine Peso', '₱'),
    ('PKR', 'Pakistan Rupee', '₨'),
    ('PLN', 'Zloty', 'zł'),
    ('PYG', 'Guarani', '₲'),
    ('QAR', 'Qatari Rial', 'ر.ق'),
    ('RON', 'Romanian Leu', 'lei'),
    ('RSD', 'Serbian Dinar', 'дин'),
    ('RUB', 'Russian Ruble', '₽'),
    ('RWF', 'Rwanda Franc', 'FRw'),
    ('SAR', 'Saudi Riyal', 'ر.س'),
    ('SBD', 'Solomon Islands Dollar', 'SI$'),
    ('SCR', 'Seychelles Rupee', '₨'),
    ('SDG', 'Sudanese Pound', 'ج.س.'),
    ('SEK', 'Swedish Krona', 'kr'),
    ('SGD', 'Singapore Dollar', 'S$'),
    ('SHP', 'Saint Helena Pound', '£'),
    ('SLE', 'Leone', 'Le'),
    ('SOS', 'Somali Shilling', 'Sh'),
    ('SRD', 'Surinam Dollar', '$'),
    ('SSP', 'South Sudanese Pound', '£'),
    ('STN', 'Dobra', 'Db'),
    ('SVC', 'El Salvador Colon', '$'),
    ('SYP', 'Syrian Pound', '£'),
    ('SZL', 'Lilangeni', 'L'),
    ('THB', 'Baht', '฿'),
    ('TJS', 'Somoni', 'ЅМ'),
    ('TMT', 'Turkmenistan New Manat', 'm'),
    ('TND', 'Tunisian Dinar', 'د.ت'),
    ('TOP', 'Pa’anga', 'T$'),
    ('TRY', 'Turkish Lira', '₺'),
    ('TTD', 'Trinidad and Tobago Dollar', 'TT$'),
    ('TWD', 'New Taiwan Dollar', 'NT$'),
    ('TZS', 'Tanzanian Shilling', 'TSh'),
    ('UAH', 'Hryvnia', '₴'),
    ('UGX', 'Uganda Shilling', 'USh'),
    ('USD', 'US Dollar', '$'),
    ('UYU', 'Peso Uruguayo', '$U'),
    ('UZS', 'Uzbekistan Sum', "so'm"),
    ('VES', 'Bolívar Soberano', 'Bs.'),
    ('VND', 'Dong', '₫'),
    ('VUV', 'Vatu', 'VT'),
    ('WST', 'Tala', 'WS$'),
    ('XAF', 'CFA Franc BEAC', 'FCFA'),
    ('XCD', 'East Caribbean Dollar', 'EC$'),
    ('XOF', 'CFA Franc BCEAO', 'CFA'),
    ('XPF', 'CFP Franc', '₣'),
    ('YER', 'Yemeni Rial', '﷼'),
    ('ZAR', 'Rand', 'R'),
    ('ZMW', 'Zambian Kwacha', 'ZK'),
    ('ZWL', 'Zimbabwe Dollar', 'Z$'),
]


def upgrade():
    bind = op.get_bind()

    # 1. Capture + drop FKs referencing currency_info so the PK can change.
    refs = bind.execute(text(f"""
        SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE confrelid = '{SCHEMA}.currency_info'::regclass
    """)).fetchall()
    for tbl, name, _ in refs:
        bind.execute(text(f'ALTER TABLE {tbl} DROP CONSTRAINT "{name}"'))

    # 2. PK column must hold a 36-char uuid (legacy shape was varchar(10)).
    bind.execute(text(
        f"ALTER TABLE {SCHEMA}.currency_info "
        "ALTER COLUMN currency_id TYPE character varying(36)"
    ))

    # 3. Upsert the registry by iso_code. Existing rows keep their PK (so
    #    re-runs never churn uuids); new rows get a fresh uuid4.
    created = updated = 0
    for iso, name, symbol in CURRENCIES:
        row = bind.execute(
            text(
                f"SELECT currency_id FROM {SCHEMA}.currency_info "
                "WHERE iso_code = :iso"
            ),
            {"iso": iso},
        ).fetchone()
        if row:
            bind.execute(
                text(
                    f"UPDATE {SCHEMA}.currency_info "
                    "SET currency_name = :name, currency_symbol = :sym "
                    "WHERE iso_code = :iso"
                ),
                {"name": name, "sym": symbol, "iso": iso},
            )
            updated += 1
        else:
            bind.execute(
                text(
                    f"INSERT INTO {SCHEMA}.currency_info "
                    "(currency_id, currency_name, currency_symbol, iso_code) "
                    "VALUES (:cid, :name, :sym, :iso)"
                ),
                {"cid": str(uuid.uuid4()), "name": name, "sym": symbol,
                 "iso": iso},
            )
            created += 1

    # 4. Convert legacy non-uuid primary keys (rows keyed by their ISO code
    #    from the pre-uuid design) to uuid4.
    legacy = bind.execute(text(
        f"SELECT currency_id FROM {SCHEMA}.currency_info "
        f"WHERE currency_id !~* '{UUID_RE}'"
    )).fetchall()
    for (old_pk,) in legacy:
        bind.execute(
            text(
                f"UPDATE {SCHEMA}.currency_info "
                "SET currency_id = :new WHERE currency_id = :old"
            ),
            {"new": str(uuid.uuid4()), "old": old_pk},
        )
    print(
        f"currency_info: {created} created, {updated} refreshed, "
        f"{len(legacy)} legacy pks converted to uuid"
    )

    # 5. entities.currency_code -> currency_id (uuid FK).
    cols = {
        r[0]
        for r in bind.execute(text(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_schema = '{SCHEMA}' AND table_name = 'entities'"
        ))
    }
    if "currency_code" in cols and "currency_id" not in cols:
        bind.execute(text(
            f"ALTER TABLE {SCHEMA}.entities "
            "RENAME COLUMN currency_code TO currency_id"
        ))
    bind.execute(text(
        f"ALTER TABLE {SCHEMA}.entities "
        "ALTER COLUMN currency_id TYPE character varying(36)"
    ))
    remapped = bind.execute(text(f"""
        UPDATE {SCHEMA}.entities e
        SET currency_id = ci.currency_id
        FROM {SCHEMA}.currency_info ci
        WHERE e.currency_id = ci.iso_code
    """)).rowcount
    cleared = bind.execute(text(f"""
        UPDATE {SCHEMA}.entities e
        SET currency_id = NULL
        WHERE e.currency_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM {SCHEMA}.currency_info ci
              WHERE ci.currency_id = e.currency_id
          )
    """)).rowcount
    print(f"entities currency remap: {remapped} remapped, {cleared} cleared")
    bind.execute(text(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_entities_currency_id'
                  AND conrelid = '{SCHEMA}.entities'::regclass
            ) THEN
                ALTER TABLE {SCHEMA}.entities
                ADD CONSTRAINT fk_entities_currency_id
                FOREIGN KEY (currency_id)
                REFERENCES {SCHEMA}.currency_info(currency_id);
            END IF;
        END $$;
    """))

    # 6. country_info.currency_id -> uuid, when the table already exists here.
    #    a2c4e6b8d0f2 seeds country_info with resolved uuids, but it runs AFTER
    #    this migration; a database that already has a populated country_info
    #    (restored dump / 0001_full_schema) still holds ISO codes in this
    #    column, and step 7 would fail re-adding its FK. Mirrors step 5.
    country_cols = {
        r[0]
        for r in bind.execute(text(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_schema = '{SCHEMA}' AND table_name = 'country_info'"
        ))
    }
    if "currency_id" in country_cols:
        # Widen first — the legacy column is too narrow to hold a uuid.
        bind.execute(text(
            f"ALTER TABLE {SCHEMA}.country_info "
            "ALTER COLUMN currency_id TYPE character varying(36)"
        ))
        co_remapped = bind.execute(text(f"""
            UPDATE {SCHEMA}.country_info co
            SET currency_id = ci.currency_id
            FROM {SCHEMA}.currency_info ci
            WHERE co.currency_id = ci.iso_code
        """)).rowcount

        # Anything still unresolved can't satisfy the FK. Clear it when the
        # column allows NULL; otherwise stop with a message naming the values
        # rather than failing later on an opaque constraint error.
        unresolved = bind.execute(text(f"""
            SELECT DISTINCT currency_id FROM {SCHEMA}.country_info co
            WHERE co.currency_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM {SCHEMA}.currency_info ci
                  WHERE ci.currency_id = co.currency_id
              )
        """)).fetchall()
        co_cleared = 0
        if unresolved:
            nullable = bind.execute(text(
                "SELECT is_nullable FROM information_schema.columns "
                f"WHERE table_schema = '{SCHEMA}' "
                "AND table_name = 'country_info' AND column_name = 'currency_id'"
            )).scalar() == "YES"
            if not nullable:
                raise RuntimeError(
                    "country_info.currency_id holds values with no matching "
                    "currency and the column is NOT NULL: "
                    f"{', '.join(sorted(str(v[0]) for v in unresolved))}. "
                    "Add those currencies to currency_info (or make the column "
                    "nullable) and re-run."
                )
            co_cleared = bind.execute(text(f"""
                UPDATE {SCHEMA}.country_info co
                SET currency_id = NULL
                WHERE co.currency_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM {SCHEMA}.currency_info ci
                      WHERE ci.currency_id = co.currency_id
                  )
            """)).rowcount
        print(
            f"country_info currency remap: {co_remapped} remapped, "
            f"{co_cleared} cleared"
        )

    # 7. Restore the captured FKs (referencing values were NULL or handled).
    for tbl, name, defn in refs:
        bind.execute(text(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = '{name}'
                      AND conrelid = '{tbl}'::regclass
                ) THEN
                    ALTER TABLE {tbl} ADD CONSTRAINT "{name}" {defn};
                END IF;
            END $$;
        """))


def downgrade():
    # Intentional no-op — reverting would swap uuid FKs back to raw ISO codes
    # and delete reference data other tables now depend on.
    pass

"""Rebuild currency_info and country_info to the new registry DDL.

Target shape (exact, including column order and constraint names):

    pettycashv2.currency_info
        id              uuid PRIMARY KEY DEFAULT gen_random_uuid()
        currency_code   char(3)  NOT NULL UNIQUE  (was iso_code varchar(3))
        currency_name   varchar(100) NOT NULL     (was varchar(50))
        symbol          varchar(10) NOT NULL DEFAULT ''  (was currency_symbol, nullable)
        decimal_places  integer NOT NULL DEFAULT 2       (new)
        is_active       boolean NOT NULL DEFAULT true    (new)
        created_at      timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP (new)
        updated_at      timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP (new)

    pettycashv2.country_info
        country_code    char(2) PRIMARY KEY       (was varchar(3) UNIQUE, PK was country_id)
        alpha3_code     char(3) NOT NULL          (new, backfilled from ISO 3166-1)
        country_name_en varchar(100) NOT NULL     (was varchar(50))
        currency_id     uuid NULL FK -> currency_info(id) ON DELETE SET NULL
        phone_code      varchar(10) NULL          (new)
        is_active       boolean NOT NULL DEFAULT true    (new)
        display_order   integer NOT NULL DEFAULT 999     (new)
        + chk_country_code_length, chk_alpha3_code_length,
          idx_country_info_currency_id

Both tables are rebuilt (create-new / copy / drop-old / rename) so the column
order and constraint names match the DDL exactly. FKs other tables hold on the
registries (e.g. cash_info.country_code -> country_info.country_code) are
captured before the drop and re-created afterwards; without that the DROP
fails with "cannot drop table ... because other objects depend on it". Existing uuids are kept, so
references stay stable. Row level security is re-enabled on both rebuilt
tables (no policies existed).

The dropped columns are recoverable from the repo:
  * country_info.country_name_ko lives in the a2c4e6b8d0f2 seed data;
  * country_info.country_id uuids only existed to serve as PK.

entities is minimally adjusted so its two FKs survive the new shape:
  * entities.currency_id varchar(36) -> uuid, FK re-created against
    currency_info(id) (same uuids, so purely a type change);
  * entities.country_id values are remapped from the old country uuid to the
    2-letter country_code, the column becomes char(2), and the FK re-created
    against the new country_info PK.

Idempotent — a guard skips the whole upgrade once currency_info.id exists.

Downgrade restores the previous shape (varchar(36) uuid PKs, iso_code /
currency_symbol names, entities uuid links) but country_name_ko comes back
NULL — re-run the a2c4e6b8d0f2 seed upsert to repopulate it.

Revision ID: c8e0a2b4d6f8
Revises: b4d6f8a0c2e4
Create Date: 2026-07-17 00:00:00.000000

"""

import re
import uuid

from alembic import op
from sqlalchemy import text

revision = "c8e0a2b4d6f8"
down_revision = "b4d6f8a0c2e4"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# ISO 3166-1 alpha-2 -> alpha-3 (generated from pycountry; covers every code
# seeded by a2c4e6b8d0f2).
ALPHA2_TO_ALPHA3 = {
    'AD': 'AND', 'AE': 'ARE', 'AF': 'AFG', 'AG': 'ATG', 'AI': 'AIA', 'AL': 'ALB', 'AM': 'ARM', 'AO': 'AGO',
    'AQ': 'ATA', 'AR': 'ARG', 'AS': 'ASM', 'AT': 'AUT', 'AU': 'AUS', 'AW': 'ABW', 'AX': 'ALA', 'AZ': 'AZE',
    'BA': 'BIH', 'BB': 'BRB', 'BD': 'BGD', 'BE': 'BEL', 'BF': 'BFA', 'BG': 'BGR', 'BH': 'BHR', 'BI': 'BDI',
    'BJ': 'BEN', 'BL': 'BLM', 'BM': 'BMU', 'BN': 'BRN', 'BO': 'BOL', 'BQ': 'BES', 'BR': 'BRA', 'BS': 'BHS',
    'BT': 'BTN', 'BV': 'BVT', 'BW': 'BWA', 'BY': 'BLR', 'BZ': 'BLZ', 'CA': 'CAN', 'CC': 'CCK', 'CD': 'COD',
    'CF': 'CAF', 'CG': 'COG', 'CH': 'CHE', 'CI': 'CIV', 'CK': 'COK', 'CL': 'CHL', 'CM': 'CMR', 'CN': 'CHN',
    'CO': 'COL', 'CR': 'CRI', 'CU': 'CUB', 'CV': 'CPV', 'CW': 'CUW', 'CX': 'CXR', 'CY': 'CYP', 'CZ': 'CZE',
    'DE': 'DEU', 'DJ': 'DJI', 'DK': 'DNK', 'DM': 'DMA', 'DO': 'DOM', 'DZ': 'DZA', 'EC': 'ECU', 'EE': 'EST',
    'EG': 'EGY', 'EH': 'ESH', 'ER': 'ERI', 'ES': 'ESP', 'ET': 'ETH', 'FI': 'FIN', 'FJ': 'FJI', 'FK': 'FLK',
    'FM': 'FSM', 'FO': 'FRO', 'FR': 'FRA', 'GA': 'GAB', 'GB': 'GBR', 'GD': 'GRD', 'GE': 'GEO', 'GF': 'GUF',
    'GG': 'GGY', 'GH': 'GHA', 'GI': 'GIB', 'GL': 'GRL', 'GM': 'GMB', 'GN': 'GIN', 'GP': 'GLP', 'GQ': 'GNQ',
    'GR': 'GRC', 'GS': 'SGS', 'GT': 'GTM', 'GU': 'GUM', 'GW': 'GNB', 'GY': 'GUY', 'HK': 'HKG', 'HM': 'HMD',
    'HN': 'HND', 'HR': 'HRV', 'HT': 'HTI', 'HU': 'HUN', 'ID': 'IDN', 'IE': 'IRL', 'IL': 'ISR', 'IM': 'IMN',
    'IN': 'IND', 'IO': 'IOT', 'IQ': 'IRQ', 'IR': 'IRN', 'IS': 'ISL', 'IT': 'ITA', 'JE': 'JEY', 'JM': 'JAM',
    'JO': 'JOR', 'JP': 'JPN', 'KE': 'KEN', 'KG': 'KGZ', 'KH': 'KHM', 'KI': 'KIR', 'KM': 'COM', 'KN': 'KNA',
    'KP': 'PRK', 'KR': 'KOR', 'KW': 'KWT', 'KY': 'CYM', 'KZ': 'KAZ', 'LA': 'LAO', 'LB': 'LBN', 'LC': 'LCA',
    'LI': 'LIE', 'LK': 'LKA', 'LR': 'LBR', 'LS': 'LSO', 'LT': 'LTU', 'LU': 'LUX', 'LV': 'LVA', 'LY': 'LBY',
    'MA': 'MAR', 'MC': 'MCO', 'MD': 'MDA', 'ME': 'MNE', 'MF': 'MAF', 'MG': 'MDG', 'MH': 'MHL', 'MK': 'MKD',
    'ML': 'MLI', 'MM': 'MMR', 'MN': 'MNG', 'MO': 'MAC', 'MP': 'MNP', 'MQ': 'MTQ', 'MR': 'MRT', 'MS': 'MSR',
    'MT': 'MLT', 'MU': 'MUS', 'MV': 'MDV', 'MW': 'MWI', 'MX': 'MEX', 'MY': 'MYS', 'MZ': 'MOZ', 'NA': 'NAM',
    'NC': 'NCL', 'NE': 'NER', 'NF': 'NFK', 'NG': 'NGA', 'NI': 'NIC', 'NL': 'NLD', 'NO': 'NOR', 'NP': 'NPL',
    'NR': 'NRU', 'NU': 'NIU', 'NZ': 'NZL', 'OM': 'OMN', 'PA': 'PAN', 'PE': 'PER', 'PF': 'PYF', 'PG': 'PNG',
    'PH': 'PHL', 'PK': 'PAK', 'PL': 'POL', 'PM': 'SPM', 'PN': 'PCN', 'PR': 'PRI', 'PS': 'PSE', 'PT': 'PRT',
    'PW': 'PLW', 'PY': 'PRY', 'QA': 'QAT', 'RE': 'REU', 'RO': 'ROU', 'RS': 'SRB', 'RU': 'RUS', 'RW': 'RWA',
    'SA': 'SAU', 'SB': 'SLB', 'SC': 'SYC', 'SD': 'SDN', 'SE': 'SWE', 'SG': 'SGP', 'SH': 'SHN', 'SI': 'SVN',
    'SJ': 'SJM', 'SK': 'SVK', 'SL': 'SLE', 'SM': 'SMR', 'SN': 'SEN', 'SO': 'SOM', 'SR': 'SUR', 'SS': 'SSD',
    'ST': 'STP', 'SV': 'SLV', 'SX': 'SXM', 'SY': 'SYR', 'SZ': 'SWZ', 'TC': 'TCA', 'TD': 'TCD', 'TF': 'ATF',
    'TG': 'TGO', 'TH': 'THA', 'TJ': 'TJK', 'TK': 'TKL', 'TL': 'TLS', 'TM': 'TKM', 'TN': 'TUN', 'TO': 'TON',
    'TR': 'TUR', 'TT': 'TTO', 'TV': 'TUV', 'TW': 'TWN', 'TZ': 'TZA', 'UA': 'UKR', 'UG': 'UGA', 'UM': 'UMI',
    'US': 'USA', 'UY': 'URY', 'UZ': 'UZB', 'VA': 'VAT', 'VC': 'VCT', 'VE': 'VEN', 'VG': 'VGB', 'VI': 'VIR',
    'VN': 'VNM', 'VU': 'VUT', 'WF': 'WLF', 'WS': 'WSM', 'YE': 'YEM', 'YT': 'MYT', 'ZA': 'ZAF', 'ZM': 'ZMB',
    'ZW': 'ZWE',
}


def _column_exists(bind, table, column):
    return bind.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = :s AND table_name = :t AND column_name = :c"
    ), {"s": SCHEMA, "t": table, "c": column}).scalar() is not None


def upgrade():
    bind = op.get_bind()

    # Guard: already on the new shape.
    if _column_exists(bind, "currency_info", "id"):
        print("currency_info already restructured — skipping")
        return

    # ------------------------------------------------------------------
    # 1. New currency_info (temp constraint names: index names collide
    #    schema-wide with the old table's until it is dropped).
    # ------------------------------------------------------------------
    bind.execute(text(f"""
        CREATE TABLE {SCHEMA}.currency_info_new (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            currency_code CHARACTER(3) NOT NULL,
            currency_name CHARACTER VARYING(100) NOT NULL,
            symbol CHARACTER VARYING(10) NOT NULL DEFAULT ''::character varying,
            decimal_places INTEGER NOT NULL DEFAULT 2,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT currency_info_new_pkey PRIMARY KEY (id),
            CONSTRAINT currency_info_new_currency_code_key UNIQUE (currency_code)
        ) TABLESPACE pg_default
    """))
    copied = bind.execute(text(f"""
        INSERT INTO {SCHEMA}.currency_info_new (id, currency_code, currency_name, symbol)
        SELECT currency_id::uuid, iso_code, currency_name, COALESCE(currency_symbol, '')
        FROM {SCHEMA}.currency_info
    """)).rowcount
    print(f"currency_info: copied {copied} rows")

    # ------------------------------------------------------------------
    # 2. New country_info. alpha3_code backfills from the ISO map; every
    #    seeded code must resolve or the migration aborts (count check).
    # ------------------------------------------------------------------
    bind.execute(text(f"""
        CREATE TABLE {SCHEMA}.country_info_new (
            country_code CHARACTER(2) NOT NULL,
            alpha3_code CHARACTER(3) NOT NULL,
            country_name_en CHARACTER VARYING(100) NOT NULL,
            currency_id UUID NULL,
            phone_code CHARACTER VARYING(10) NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            display_order INTEGER NOT NULL DEFAULT 999,
            CONSTRAINT country_info_new_pkey PRIMARY KEY (country_code),
            CONSTRAINT country_info_new_currency_fk FOREIGN KEY (currency_id)
                REFERENCES {SCHEMA}.currency_info_new (id) ON DELETE SET NULL,
            CONSTRAINT country_info_new_chk_cc CHECK (length(country_code) = 2),
            CONSTRAINT country_info_new_chk_a3 CHECK (length(alpha3_code) = 3)
        ) TABLESPACE pg_default
    """))
    values = ", ".join(f"('{a2}', '{a3}')" for a2, a3 in sorted(ALPHA2_TO_ALPHA3.items()))
    copied = bind.execute(text(f"""
        INSERT INTO {SCHEMA}.country_info_new
            (country_code, alpha3_code, country_name_en, currency_id)
        SELECT co.country_code, m.a3, co.country_name_en, co.currency_id::uuid
        FROM {SCHEMA}.country_info co
        JOIN (VALUES {values}) AS m(a2, a3) ON m.a2 = co.country_code
    """)).rowcount
    total = bind.execute(text(f"SELECT count(*) FROM {SCHEMA}.country_info")).scalar()
    if copied != total:
        raise RuntimeError(
            f"alpha3 backfill incomplete: {copied}/{total} countries mapped — aborting"
        )
    print(f"country_info: copied {copied} rows (alpha3 backfilled)")

    # ------------------------------------------------------------------
    # 3. entities: drop both FKs first (the old country FK would reject
    #    codes), then remap country uuid -> country_code while the old
    #    registry still exists, and retype the columns.
    # ------------------------------------------------------------------
    bind.execute(text(f"ALTER TABLE {SCHEMA}.entities DROP CONSTRAINT IF EXISTS fk_entities_currency_id"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.entities DROP CONSTRAINT IF EXISTS fk_entities_country_id"))

    remapped = bind.execute(text(f"""
        UPDATE {SCHEMA}.entities e
        SET country_id = co.country_code
        FROM {SCHEMA}.country_info co
        WHERE e.country_id = co.country_id
    """)).rowcount
    cleared = bind.execute(text(f"""
        UPDATE {SCHEMA}.entities e
        SET country_id = NULL
        WHERE e.country_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM {SCHEMA}.country_info_new cn
              WHERE cn.country_code = e.country_id
          )
    """)).rowcount
    print(f"entities country links: {remapped} remapped, {cleared} cleared")

    bind.execute(text(f"""
        ALTER TABLE {SCHEMA}.entities
        ALTER COLUMN currency_id TYPE uuid USING NULLIF(currency_id, '')::uuid
    """))
    bind.execute(text(f"""
        ALTER TABLE {SCHEMA}.entities
        ALTER COLUMN country_id TYPE character(2) USING NULLIF(country_id, '')
    """))

    # ------------------------------------------------------------------
    # 4. Swap: drop old tables, rename new ones, restore the DDL's
    #    constraint/index names, re-enable RLS, re-point entities FKs.
    # ------------------------------------------------------------------
    # Other tables may point at the registries (e.g. cash_info.country_code
    # -> country_info.country_code), which would block the DROPs. Capture
    # those FKs, drop them here, and re-create them after the swap. entities
    # is excluded — its two FKs are dropped and re-pointed explicitly above
    # and below, since its referenced columns change.
    external_fks = bind.execute(text(f"""
        SELECT c.conrelid::regclass::text, c.conname,
               pg_get_constraintdef(c.oid), c.confrelid::regclass::text
        FROM pg_constraint c
        WHERE c.contype = 'f'
          AND c.confrelid IN (
              '{SCHEMA}.country_info'::regclass,
              '{SCHEMA}.currency_info'::regclass
          )
          AND c.conrelid NOT IN (
              '{SCHEMA}.country_info'::regclass,
              '{SCHEMA}.currency_info'::regclass,
              '{SCHEMA}.entities'::regclass
          )
    """)).fetchall()
    for tbl, name, _defn, _target in external_fks:
        bind.execute(text(f'ALTER TABLE {tbl} DROP CONSTRAINT "{name}"'))
    if external_fks:
        print(
            "captured external FKs: "
            + ", ".join(f"{t}.{n}" for t, n, _d, _r in external_fks)
        )

    bind.execute(text(f"DROP TABLE {SCHEMA}.country_info"))
    bind.execute(text(f"DROP TABLE {SCHEMA}.currency_info"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.currency_info_new RENAME TO currency_info"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.country_info_new RENAME TO country_info"))

    bind.execute(text(f"ALTER TABLE {SCHEMA}.currency_info RENAME CONSTRAINT currency_info_new_pkey TO currency_info_pkey"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.currency_info RENAME CONSTRAINT currency_info_new_currency_code_key TO currency_info_currency_code_key"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.country_info RENAME CONSTRAINT country_info_new_pkey TO country_info_pkey"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.country_info RENAME CONSTRAINT country_info_new_currency_fk TO fk_country_info_currency_id"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.country_info RENAME CONSTRAINT country_info_new_chk_cc TO chk_country_code_length"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.country_info RENAME CONSTRAINT country_info_new_chk_a3 TO chk_alpha3_code_length"))

    bind.execute(text(f"CREATE INDEX idx_country_info_currency_id ON {SCHEMA}.country_info (currency_id)"))

    # Postgres >= 18 catalogs NOT NULL constraints; strip the temp '_new'
    # marker from their auto-generated names (no-op on older versions).
    leftovers = bind.execute(text("""
        SELECT c.conrelid::regclass::text, c.conname
        FROM pg_constraint c
        JOIN pg_namespace n ON n.oid = c.connamespace
        WHERE n.nspname = :s AND c.contype = 'n' AND c.conname LIKE '%\\_new\\_%'
    """), {"s": SCHEMA}).fetchall()
    for table, conname in leftovers:
        bind.execute(text(
            f"ALTER TABLE {table} RENAME CONSTRAINT {conname} "
            f"TO {conname.replace('_new_', '_')}"
        ))

    bind.execute(text(f"ALTER TABLE {SCHEMA}.currency_info ENABLE ROW LEVEL SECURITY"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.country_info ENABLE ROW LEVEL SECURITY"))

    bind.execute(text(f"""
        ALTER TABLE {SCHEMA}.entities
        ADD CONSTRAINT fk_entities_currency_id
        FOREIGN KEY (currency_id) REFERENCES {SCHEMA}.currency_info (id)
    """))
    bind.execute(text(f"""
        ALTER TABLE {SCHEMA}.entities
        ADD CONSTRAINT fk_entities_country_id
        FOREIGN KEY (country_id) REFERENCES {SCHEMA}.country_info (country_code)
    """))

    # Re-create the captured external FKs. country_info.country_code survives
    # the rebuild (it is the new PK), so an FK like cash_info's is restored
    # verbatim — varchar -> char(2) is a valid reference. Anything that
    # pointed at a key the rebuild removed (country_id, currency_info's old
    # currency_id) cannot be restored; that is reported, never silently lost.
    for tbl, name, defn, target in external_fks:
        target_table = target.split(".")[-1]
        match = re.search(r"REFERENCES\s+[^(]+\(([^)]+)\)", defn)
        ref_col = match.group(1).strip().strip('"') if match else ""
        if not ref_col or not _column_exists(bind, target_table, ref_col):
            print(
                f"WARNING: not restoring {tbl}.{name} — "
                f"{target_table}.{ref_col or '?'} no longer exists after the "
                "rebuild; re-point it manually if that table is still in use"
            )
            continue
        bind.execute(text(f'ALTER TABLE {tbl} ADD CONSTRAINT "{name}" {defn}'))
        print(f"restored external FK: {tbl}.{name}")


def downgrade():
    bind = op.get_bind()

    if _column_exists(bind, "currency_info", "currency_id"):
        print("currency_info already on the old shape — skipping")
        return

    # Old-shape currency_info (varchar(36) uuid PK, iso_code, nullable symbol).
    bind.execute(text(f"""
        CREATE TABLE {SCHEMA}.currency_info_old (
            currency_id CHARACTER VARYING(36) NOT NULL,
            currency_name CHARACTER VARYING(50) NOT NULL,
            currency_symbol CHARACTER VARYING(10),
            iso_code CHARACTER VARYING(3),
            CONSTRAINT currency_info_old_pkey PRIMARY KEY (currency_id),
            CONSTRAINT currency_info_old_iso_code_key UNIQUE (iso_code)
        )
    """))
    bind.execute(text(f"""
        INSERT INTO {SCHEMA}.currency_info_old (currency_id, currency_name, currency_symbol, iso_code)
        SELECT id::text, left(currency_name, 50), symbol, trim(currency_code)
        FROM {SCHEMA}.currency_info
    """))

    # Old-shape country_info; country_id uuids are regenerated, and
    # country_name_ko is restored as NULL (see module docstring).
    bind.execute(text(f"""
        CREATE TABLE {SCHEMA}.country_info_old (
            country_id CHARACTER VARYING(36) NOT NULL,
            country_code CHARACTER VARYING(3) NOT NULL,
            country_name_en CHARACTER VARYING(50) NOT NULL,
            country_name_ko CHARACTER VARYING(50),
            currency_id CHARACTER VARYING(36),
            CONSTRAINT country_info_old_pkey PRIMARY KEY (country_id),
            CONSTRAINT country_info_old_country_code_key UNIQUE (country_code),
            CONSTRAINT country_info_old_currency_fk FOREIGN KEY (currency_id)
                REFERENCES {SCHEMA}.currency_info_old (currency_id)
        )
    """))
    rows = bind.execute(text(
        f"SELECT trim(country_code), country_name_en, currency_id::text FROM {SCHEMA}.country_info"
    )).fetchall()
    for code, name_en, currency_id in rows:
        bind.execute(text(f"""
            INSERT INTO {SCHEMA}.country_info_old
                (country_id, country_code, country_name_en, currency_id)
            VALUES (:cid, :code, :name_en, :cur)
        """), {"cid": str(uuid.uuid4()), "code": code, "name_en": left50(name_en), "cur": currency_id})

    # entities back to varchar(36) uuid links.
    bind.execute(text(f"ALTER TABLE {SCHEMA}.entities DROP CONSTRAINT IF EXISTS fk_entities_currency_id"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.entities DROP CONSTRAINT IF EXISTS fk_entities_country_id"))
    bind.execute(text(f"""
        ALTER TABLE {SCHEMA}.entities
        ALTER COLUMN currency_id TYPE character varying(36) USING currency_id::text
    """))
    bind.execute(text(f"""
        ALTER TABLE {SCHEMA}.entities
        ALTER COLUMN country_id TYPE character varying(36) USING trim(country_id)
    """))
    bind.execute(text(f"""
        UPDATE {SCHEMA}.entities e
        SET country_id = co.country_id
        FROM {SCHEMA}.country_info_old co
        WHERE e.country_id = co.country_code
    """))

    # Swap and restore original constraint names + RLS + entities FKs.
    bind.execute(text(f"DROP TABLE {SCHEMA}.country_info"))
    bind.execute(text(f"DROP TABLE {SCHEMA}.currency_info"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.currency_info_old RENAME TO currency_info"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.country_info_old RENAME TO country_info"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.currency_info RENAME CONSTRAINT currency_info_old_pkey TO currency_info_pkey"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.currency_info RENAME CONSTRAINT currency_info_old_iso_code_key TO currency_info_iso_code_key"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.country_info RENAME CONSTRAINT country_info_old_pkey TO country_info_pkey"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.country_info RENAME CONSTRAINT country_info_old_country_code_key TO country_info_country_code_key"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.country_info RENAME CONSTRAINT country_info_old_currency_fk TO fk_country_info_currency_id"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.currency_info ENABLE ROW LEVEL SECURITY"))
    bind.execute(text(f"ALTER TABLE {SCHEMA}.country_info ENABLE ROW LEVEL SECURITY"))
    bind.execute(text(f"""
        ALTER TABLE {SCHEMA}.entities
        ADD CONSTRAINT fk_entities_currency_id
        FOREIGN KEY (currency_id) REFERENCES {SCHEMA}.currency_info (currency_id)
    """))
    bind.execute(text(f"""
        ALTER TABLE {SCHEMA}.entities
        ADD CONSTRAINT fk_entities_country_id
        FOREIGN KEY (country_id) REFERENCES {SCHEMA}.country_info (country_id)
    """))


def left50(value):
    return value if value is None or len(value) <= 50 else value[:50]

"""Rebuild country_info around a country_id uuid PK and seed the registry.

Final table shape (column order matters — the table is rebuilt to get it):

    country_id      varchar(36) PRIMARY KEY   -- uuid4
    country_code    varchar(3)  NOT NULL UNIQUE
    country_name_en varchar(50) NOT NULL
    country_name_ko varchar(50)
    currency_id     varchar(36) FK -> currency_info(currency_id)

Seeds/refreshes all ISO 3166-1 countries with English and Korean names. Each
country links to its currency by resolving the currency's 3-letter ISO code
against ``currency_info.iso_code`` at migration time, so
``country_info.currency_id`` always points at the correct
``currency_info.currency_id`` uuid regardless of which uuids the currency
seed generated.

``country_code`` keeps a UNIQUE constraint so existing FKs that reference it
(e.g. cash_info.country_code) stay valid; any FK found referencing
country_info is captured before the rebuild and re-created afterwards.
Row level security is re-enabled on the rebuilt table.

Idempotent — re-running is a no-op:
  * the rebuild only runs while the primary key is not yet country_id;
  * country rows upsert by ``country_code`` (names + currency refresh, the
    existing ``country_id`` uuid is preserved).

Currencies not in the registry resolve to NULL (only Antarctica). UUIDs are
generated in Python, not by the DB, for the same portability reasons as the
module seed migration (b8f3a2c1d4e5).

Revision ID: a2c4e6b8d0f2
Revises: c6e8a0b2d4f6
Create Date: 2026-07-15 00:00:00.000000

"""

import uuid

from alembic import op
from sqlalchemy import text

revision = "a2c4e6b8d0f2"
down_revision = "c6e8a0b2d4f6"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# (country_code, country_name_en, country_name_ko, currency_iso_code | None)
# Generated from pycountry (ISO 3166-1) + babel (names, territory currencies).
# CW / SX map to ANG: their successor code XCG is not in the currency registry.
COUNTRIES = [
    ('AD', 'Andorra', '안도라', 'EUR'),
    ('AE', 'United Arab Emirates', '아랍에미리트', 'AED'),
    ('AF', 'Afghanistan', '아프가니스탄', 'AFN'),
    ('AG', 'Antigua & Barbuda', '앤티가 바부다', 'XCD'),
    ('AI', 'Anguilla', '앵귈라', 'XCD'),
    ('AL', 'Albania', '알바니아', 'ALL'),
    ('AM', 'Armenia', '아르메니아', 'AMD'),
    ('AO', 'Angola', '앙골라', 'AOA'),
    ('AQ', 'Antarctica', '남극 대륙', None),
    ('AR', 'Argentina', '아르헨티나', 'ARS'),
    ('AS', 'American Samoa', '아메리칸 사모아', 'USD'),
    ('AT', 'Austria', '오스트리아', 'EUR'),
    ('AU', 'Australia', '오스트레일리아', 'AUD'),
    ('AW', 'Aruba', '아루바', 'AWG'),
    ('AX', 'Åland Islands', '올란드 제도', 'EUR'),
    ('AZ', 'Azerbaijan', '아제르바이잔', 'AZN'),
    ('BA', 'Bosnia & Herzegovina', '보스니아 헤르체고비나', 'BAM'),
    ('BB', 'Barbados', '바베이도스', 'BBD'),
    ('BD', 'Bangladesh', '방글라데시', 'BDT'),
    ('BE', 'Belgium', '벨기에', 'EUR'),
    ('BF', 'Burkina Faso', '부르키나파소', 'XOF'),
    ('BG', 'Bulgaria', '불가리아', 'BGN'),
    ('BH', 'Bahrain', '바레인', 'BHD'),
    ('BI', 'Burundi', '부룬디', 'BIF'),
    ('BJ', 'Benin', '베냉', 'XOF'),
    ('BL', 'St. Barthélemy', '생바르텔레미', 'EUR'),
    ('BM', 'Bermuda', '버뮤다', 'BMD'),
    ('BN', 'Brunei', '브루나이', 'BND'),
    ('BO', 'Bolivia', '볼리비아', 'BOB'),
    ('BQ', 'Caribbean Netherlands', '네덜란드령 카리브', 'USD'),
    ('BR', 'Brazil', '브라질', 'BRL'),
    ('BS', 'Bahamas', '바하마', 'BSD'),
    ('BT', 'Bhutan', '부탄', 'INR'),
    ('BV', 'Bouvet Island', '부베섬', 'NOK'),
    ('BW', 'Botswana', '보츠와나', 'BWP'),
    ('BY', 'Belarus', '벨라루스', 'BYN'),
    ('BZ', 'Belize', '벨리즈', 'BZD'),
    ('CA', 'Canada', '캐나다', 'CAD'),
    ('CC', 'Cocos (Keeling) Islands', '코코스 제도', 'AUD'),
    ('CD', 'Congo - Kinshasa', '콩고-킨샤사', 'CDF'),
    ('CF', 'Central African Republic', '중앙 아프리카 공화국', 'XAF'),
    ('CG', 'Congo - Brazzaville', '콩고-브라자빌', 'XAF'),
    ('CH', 'Switzerland', '스위스', 'CHF'),
    ('CI', 'Côte d’Ivoire', '코트디부아르', 'XOF'),
    ('CK', 'Cook Islands', '쿡 제도', 'NZD'),
    ('CL', 'Chile', '칠레', 'CLP'),
    ('CM', 'Cameroon', '카메룬', 'XAF'),
    ('CN', 'China', '중국', 'CNY'),
    ('CO', 'Colombia', '콜롬비아', 'COP'),
    ('CR', 'Costa Rica', '코스타리카', 'CRC'),
    ('CU', 'Cuba', '쿠바', 'CUP'),
    ('CV', 'Cape Verde', '카보베르데', 'CVE'),
    ('CW', 'Curaçao', '퀴라소', 'ANG'),
    ('CX', 'Christmas Island', '크리스마스섬', 'AUD'),
    ('CY', 'Cyprus', '키프로스', 'EUR'),
    ('CZ', 'Czechia', '체코', 'CZK'),
    ('DE', 'Germany', '독일', 'EUR'),
    ('DJ', 'Djibouti', '지부티', 'DJF'),
    ('DK', 'Denmark', '덴마크', 'DKK'),
    ('DM', 'Dominica', '도미니카', 'XCD'),
    ('DO', 'Dominican Republic', '도미니카 공화국', 'DOP'),
    ('DZ', 'Algeria', '알제리', 'DZD'),
    ('EC', 'Ecuador', '에콰도르', 'USD'),
    ('EE', 'Estonia', '에스토니아', 'EUR'),
    ('EG', 'Egypt', '이집트', 'EGP'),
    ('EH', 'Western Sahara', '서사하라', 'MAD'),
    ('ER', 'Eritrea', '에리트리아', 'ERN'),
    ('ES', 'Spain', '스페인', 'EUR'),
    ('ET', 'Ethiopia', '에티오피아', 'ETB'),
    ('FI', 'Finland', '핀란드', 'EUR'),
    ('FJ', 'Fiji', '피지', 'FJD'),
    ('FK', 'Falkland Islands', '포클랜드 제도', 'FKP'),
    ('FM', 'Micronesia', '미크로네시아', 'USD'),
    ('FO', 'Faroe Islands', '페로 제도', 'DKK'),
    ('FR', 'France', '프랑스', 'EUR'),
    ('GA', 'Gabon', '가봉', 'XAF'),
    ('GB', 'United Kingdom', '영국', 'GBP'),
    ('GD', 'Grenada', '그레나다', 'XCD'),
    ('GE', 'Georgia', '조지아', 'GEL'),
    ('GF', 'French Guiana', '프랑스령 기아나', 'EUR'),
    ('GG', 'Guernsey', '건지', 'GBP'),
    ('GH', 'Ghana', '가나', 'GHS'),
    ('GI', 'Gibraltar', '지브롤터', 'GIP'),
    ('GL', 'Greenland', '그린란드', 'DKK'),
    ('GM', 'Gambia', '감비아', 'GMD'),
    ('GN', 'Guinea', '기니', 'GNF'),
    ('GP', 'Guadeloupe', '과들루프', 'EUR'),
    ('GQ', 'Equatorial Guinea', '적도 기니', 'XAF'),
    ('GR', 'Greece', '그리스', 'EUR'),
    ('GS', 'South Georgia & South Sandwich Islands', '사우스조지아 사우스샌드위치 제도', 'GBP'),
    ('GT', 'Guatemala', '과테말라', 'GTQ'),
    ('GU', 'Guam', '괌', 'USD'),
    ('GW', 'Guinea-Bissau', '기니비사우', 'XOF'),
    ('GY', 'Guyana', '가이아나', 'GYD'),
    ('HK', 'Hong Kong SAR China', '홍콩(중국 특별행정구)', 'HKD'),
    ('HM', 'Heard & McDonald Islands', '허드 맥도널드 제도', 'AUD'),
    ('HN', 'Honduras', '온두라스', 'HNL'),
    ('HR', 'Croatia', '크로아티아', 'EUR'),
    ('HT', 'Haiti', '아이티', 'HTG'),
    ('HU', 'Hungary', '헝가리', 'HUF'),
    ('ID', 'Indonesia', '인도네시아', 'IDR'),
    ('IE', 'Ireland', '아일랜드', 'EUR'),
    ('IL', 'Israel', '이스라엘', 'ILS'),
    ('IM', 'Isle of Man', '맨섬', 'GBP'),
    ('IN', 'India', '인도', 'INR'),
    ('IO', 'British Indian Ocean Territory', '영국령 인도양 지역', 'USD'),
    ('IQ', 'Iraq', '이라크', 'IQD'),
    ('IR', 'Iran', '이란', 'IRR'),
    ('IS', 'Iceland', '아이슬란드', 'ISK'),
    ('IT', 'Italy', '이탈리아', 'EUR'),
    ('JE', 'Jersey', '저지', 'GBP'),
    ('JM', 'Jamaica', '자메이카', 'JMD'),
    ('JO', 'Jordan', '요르단', 'JOD'),
    ('JP', 'Japan', '일본', 'JPY'),
    ('KE', 'Kenya', '케냐', 'KES'),
    ('KG', 'Kyrgyzstan', '키르기스스탄', 'KGS'),
    ('KH', 'Cambodia', '캄보디아', 'KHR'),
    ('KI', 'Kiribati', '키리바시', 'AUD'),
    ('KM', 'Comoros', '코모로', 'KMF'),
    ('KN', 'St. Kitts & Nevis', '세인트키츠 네비스', 'XCD'),
    ('KP', 'North Korea', '북한', 'KPW'),
    ('KR', 'South Korea', '대한민국', 'KRW'),
    ('KW', 'Kuwait', '쿠웨이트', 'KWD'),
    ('KY', 'Cayman Islands', '케이맨 제도', 'KYD'),
    ('KZ', 'Kazakhstan', '카자흐스탄', 'KZT'),
    ('LA', 'Laos', '라오스', 'LAK'),
    ('LB', 'Lebanon', '레바논', 'LBP'),
    ('LC', 'St. Lucia', '세인트루시아', 'XCD'),
    ('LI', 'Liechtenstein', '리히텐슈타인', 'CHF'),
    ('LK', 'Sri Lanka', '스리랑카', 'LKR'),
    ('LR', 'Liberia', '라이베리아', 'LRD'),
    ('LS', 'Lesotho', '레소토', 'ZAR'),
    ('LT', 'Lithuania', '리투아니아', 'EUR'),
    ('LU', 'Luxembourg', '룩셈부르크', 'EUR'),
    ('LV', 'Latvia', '라트비아', 'EUR'),
    ('LY', 'Libya', '리비아', 'LYD'),
    ('MA', 'Morocco', '모로코', 'MAD'),
    ('MC', 'Monaco', '모나코', 'EUR'),
    ('MD', 'Moldova', '몰도바', 'MDL'),
    ('ME', 'Montenegro', '몬테네그로', 'EUR'),
    ('MF', 'St. Martin', '생마르탱', 'EUR'),
    ('MG', 'Madagascar', '마다가스카르', 'MGA'),
    ('MH', 'Marshall Islands', '마셜 제도', 'USD'),
    ('MK', 'North Macedonia', '북마케도니아', 'MKD'),
    ('ML', 'Mali', '말리', 'XOF'),
    ('MM', 'Myanmar (Burma)', '미얀마', 'MMK'),
    ('MN', 'Mongolia', '몽골', 'MNT'),
    ('MO', 'Macao SAR China', '마카오(중국 특별행정구)', 'MOP'),
    ('MP', 'Northern Mariana Islands', '북마리아나제도', 'USD'),
    ('MQ', 'Martinique', '마르티니크', 'EUR'),
    ('MR', 'Mauritania', '모리타니', 'MRU'),
    ('MS', 'Montserrat', '몬트세라트', 'XCD'),
    ('MT', 'Malta', '몰타', 'EUR'),
    ('MU', 'Mauritius', '모리셔스', 'MUR'),
    ('MV', 'Maldives', '몰디브', 'MVR'),
    ('MW', 'Malawi', '말라위', 'MWK'),
    ('MX', 'Mexico', '멕시코', 'MXN'),
    ('MY', 'Malaysia', '말레이시아', 'MYR'),
    ('MZ', 'Mozambique', '모잠비크', 'MZN'),
    ('NA', 'Namibia', '나미비아', 'ZAR'),
    ('NC', 'New Caledonia', '뉴칼레도니아', 'XPF'),
    ('NE', 'Niger', '니제르', 'XOF'),
    ('NF', 'Norfolk Island', '노퍽섬', 'AUD'),
    ('NG', 'Nigeria', '나이지리아', 'NGN'),
    ('NI', 'Nicaragua', '니카라과', 'NIO'),
    ('NL', 'Netherlands', '네덜란드', 'EUR'),
    ('NO', 'Norway', '노르웨이', 'NOK'),
    ('NP', 'Nepal', '네팔', 'NPR'),
    ('NR', 'Nauru', '나우루', 'AUD'),
    ('NU', 'Niue', '니우에', 'NZD'),
    ('NZ', 'New Zealand', '뉴질랜드', 'NZD'),
    ('OM', 'Oman', '오만', 'OMR'),
    ('PA', 'Panama', '파나마', 'PAB'),
    ('PE', 'Peru', '페루', 'PEN'),
    ('PF', 'French Polynesia', '프랑스령 폴리네시아', 'XPF'),
    ('PG', 'Papua New Guinea', '파푸아뉴기니', 'PGK'),
    ('PH', 'Philippines', '필리핀', 'PHP'),
    ('PK', 'Pakistan', '파키스탄', 'PKR'),
    ('PL', 'Poland', '폴란드', 'PLN'),
    ('PM', 'St. Pierre & Miquelon', '생피에르 미클롱', 'EUR'),
    ('PN', 'Pitcairn Islands', '핏케언 제도', 'NZD'),
    ('PR', 'Puerto Rico', '푸에르토리코', 'USD'),
    ('PS', 'Palestinian Territories', '팔레스타인 지구', 'ILS'),
    ('PT', 'Portugal', '포르투갈', 'EUR'),
    ('PW', 'Palau', '팔라우', 'USD'),
    ('PY', 'Paraguay', '파라과이', 'PYG'),
    ('QA', 'Qatar', '카타르', 'QAR'),
    ('RE', 'Réunion', '레위니옹', 'EUR'),
    ('RO', 'Romania', '루마니아', 'RON'),
    ('RS', 'Serbia', '세르비아', 'RSD'),
    ('RU', 'Russia', '러시아', 'RUB'),
    ('RW', 'Rwanda', '르완다', 'RWF'),
    ('SA', 'Saudi Arabia', '사우디아라비아', 'SAR'),
    ('SB', 'Solomon Islands', '솔로몬 제도', 'SBD'),
    ('SC', 'Seychelles', '세이셸', 'SCR'),
    ('SD', 'Sudan', '수단', 'SDG'),
    ('SE', 'Sweden', '스웨덴', 'SEK'),
    ('SG', 'Singapore', '싱가포르', 'SGD'),
    ('SH', 'St. Helena', '세인트헬레나', 'SHP'),
    ('SI', 'Slovenia', '슬로베니아', 'EUR'),
    ('SJ', 'Svalbard & Jan Mayen', '스발바르제도-얀마웬섬', 'NOK'),
    ('SK', 'Slovakia', '슬로바키아', 'EUR'),
    ('SL', 'Sierra Leone', '시에라리온', 'SLE'),
    ('SM', 'San Marino', '산마리노', 'EUR'),
    ('SN', 'Senegal', '세네갈', 'XOF'),
    ('SO', 'Somalia', '소말리아', 'SOS'),
    ('SR', 'Suriname', '수리남', 'SRD'),
    ('SS', 'South Sudan', '남수단', 'SSP'),
    ('ST', 'São Tomé & Príncipe', '상투메 프린시페', 'STN'),
    ('SV', 'El Salvador', '엘살바도르', 'USD'),
    ('SX', 'Sint Maarten', '신트마르턴', 'ANG'),
    ('SY', 'Syria', '시리아', 'SYP'),
    ('SZ', 'Eswatini', '에스와티니', 'SZL'),
    ('TC', 'Turks & Caicos Islands', '터크스 케이커스 제도', 'USD'),
    ('TD', 'Chad', '차드', 'XAF'),
    ('TF', 'French Southern Territories', '프랑스령 남방 지역', 'EUR'),
    ('TG', 'Togo', '토고', 'XOF'),
    ('TH', 'Thailand', '태국', 'THB'),
    ('TJ', 'Tajikistan', '타지키스탄', 'TJS'),
    ('TK', 'Tokelau', '토켈라우', 'NZD'),
    ('TL', 'Timor-Leste', '동티모르', 'USD'),
    ('TM', 'Turkmenistan', '투르크메니스탄', 'TMT'),
    ('TN', 'Tunisia', '튀니지', 'TND'),
    ('TO', 'Tonga', '통가', 'TOP'),
    ('TR', 'Türkiye', '튀르키예', 'TRY'),
    ('TT', 'Trinidad & Tobago', '트리니다드 토바고', 'TTD'),
    ('TV', 'Tuvalu', '투발루', 'AUD'),
    ('TW', 'Taiwan', '대만', 'TWD'),
    ('TZ', 'Tanzania', '탄자니아', 'TZS'),
    ('UA', 'Ukraine', '우크라이나', 'UAH'),
    ('UG', 'Uganda', '우간다', 'UGX'),
    ('UM', 'U.S. Outlying Islands', '미국령 해외 제도', 'USD'),
    ('US', 'United States', '미국', 'USD'),
    ('UY', 'Uruguay', '우루과이', 'UYU'),
    ('UZ', 'Uzbekistan', '우즈베키스탄', 'UZS'),
    ('VA', 'Vatican City', '바티칸 시국', 'EUR'),
    ('VC', 'St. Vincent & Grenadines', '세인트빈센트그레나딘', 'XCD'),
    ('VE', 'Venezuela', '베네수엘라', 'VES'),
    ('VG', 'British Virgin Islands', '영국령 버진아일랜드', 'USD'),
    ('VI', 'U.S. Virgin Islands', '미국령 버진아일랜드', 'USD'),
    ('VN', 'Vietnam', '베트남', 'VND'),
    ('VU', 'Vanuatu', '바누아투', 'VUV'),
    ('WF', 'Wallis & Futuna', '왈리스-푸투나 제도', 'XPF'),
    ('WS', 'Samoa', '사모아', 'WST'),
    ('YE', 'Yemen', '예멘', 'YER'),
    ('YT', 'Mayotte', '마요트', 'EUR'),
    ('ZA', 'South Africa', '남아프리카', 'ZAR'),
    ('ZM', 'Zambia', '잠비아', 'ZMW'),
    ('ZW', 'Zimbabwe', '짐바브웨', 'USD'),
]


def upgrade():
    bind = op.get_bind()

    # 1. Make sure country_id exists and every row has a uuid — the rebuild
    #    below copies it verbatim so pre-assigned ids survive re-runs.
    bind.execute(text(
        f"ALTER TABLE {SCHEMA}.country_info "
        "ADD COLUMN IF NOT EXISTS country_id VARCHAR(36)"
    ))
    for row in bind.execute(text(
        f"SELECT country_code FROM {SCHEMA}.country_info WHERE country_id IS NULL"
    )).fetchall():
        bind.execute(
            text(
                f"UPDATE {SCHEMA}.country_info "
                "SET country_id = :cid WHERE country_code = :code"
            ),
            {"cid": str(uuid.uuid4()), "code": row[0]},
        )

    # 2. Rebuild unless country_id is already the primary key. Postgres cannot
    #    reorder columns or swap a PK in place, so: new table -> copy -> swap.
    pk_cols = bind.execute(text(f"""
        SELECT string_agg(a.attname, ',' ORDER BY x.n)
        FROM pg_constraint c
        JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS x(attnum, n) ON TRUE
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = x.attnum
        WHERE c.conrelid = '{SCHEMA}.country_info'::regclass
          AND c.contype = 'p'
    """)).scalar()
    if pk_cols != "country_id":
        # FKs pointing at country_info must come off before the old table can
        # be dropped; they are re-created verbatim against the rebuilt table
        # (country_code stays UNIQUE, so code-referencing FKs remain valid).
        refs = bind.execute(text(f"""
            SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE confrelid = '{SCHEMA}.country_info'::regclass
        """)).fetchall()
        for tbl, name, _ in refs:
            bind.execute(text(f'ALTER TABLE {tbl} DROP CONSTRAINT "{name}"'))

        bind.execute(text(f"""
            CREATE TABLE {SCHEMA}.country_info_rebuild (
                country_id character varying(36) NOT NULL,
                country_code character varying(3) NOT NULL,
                country_name_en character varying(50) NOT NULL,
                country_name_ko character varying(50),
                currency_id character varying(36),
                CONSTRAINT country_info_rebuild_pkey PRIMARY KEY (country_id),
                CONSTRAINT country_info_rebuild_country_code_key UNIQUE (country_code),
                CONSTRAINT fk_country_info_currency_id
                    FOREIGN KEY (currency_id)
                    REFERENCES {SCHEMA}.currency_info(currency_id)
            )
        """))
        bind.execute(text(f"""
            INSERT INTO {SCHEMA}.country_info_rebuild
                (country_id, country_code, country_name_en, country_name_ko, currency_id)
            SELECT country_id, country_code, country_name_en, country_name_ko,
                   currency_id
            FROM {SCHEMA}.country_info
        """))
        bind.execute(text(f"DROP TABLE {SCHEMA}.country_info"))
        bind.execute(text(
            f"ALTER TABLE {SCHEMA}.country_info_rebuild RENAME TO country_info"
        ))
        bind.execute(text(
            f"ALTER TABLE {SCHEMA}.country_info "
            "RENAME CONSTRAINT country_info_rebuild_pkey TO country_info_pkey"
        ))
        bind.execute(text(
            f"ALTER TABLE {SCHEMA}.country_info "
            "RENAME CONSTRAINT country_info_rebuild_country_code_key "
            "TO country_info_country_code_key"
        ))
        # Postgres 17+ tracks NOT NULL as named constraints; strip the
        # temporary _rebuild_ prefix there too (absent on older versions).
        for cname, target in (
            ("country_info_rebuild_country_id_not_null",
             "country_info_country_id_not_null"),
            ("country_info_rebuild_country_code_not_null",
             "country_info_country_code_not_null"),
            ("country_info_rebuild_country_name_en_not_null",
             "country_info_country_name_en_not_null"),
        ):
            bind.execute(text(f"""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = '{cname}'
                          AND conrelid = '{SCHEMA}.country_info'::regclass
                    ) THEN
                        ALTER TABLE {SCHEMA}.country_info
                        RENAME CONSTRAINT "{cname}" TO "{target}";
                    END IF;
                END $$;
            """))
        bind.execute(text(
            f"ALTER TABLE {SCHEMA}.country_info ENABLE ROW LEVEL SECURITY"
        ))
        for tbl, name, defn in refs:
            bind.execute(text(f'ALTER TABLE {tbl} ADD CONSTRAINT "{name}" {defn}'))

    # 3. Upsert the registry. The currency link resolves through
    #    currency_info.iso_code -> currency_id (uuid) at execution time.
    upsert = text(f"""
        INSERT INTO {SCHEMA}.country_info
            (country_id, country_code, country_name_en, country_name_ko, currency_id)
        VALUES (
            :cid, :code, :en, :ko,
            (SELECT ci.currency_id
             FROM {SCHEMA}.currency_info ci
             WHERE ci.iso_code = :iso)
        )
        ON CONFLICT (country_code) DO UPDATE
        SET country_name_en = EXCLUDED.country_name_en,
            country_name_ko = EXCLUDED.country_name_ko,
            currency_id     = EXCLUDED.currency_id
    """)
    for code, name_en, name_ko, iso in COUNTRIES:
        bind.execute(upsert, {
            "cid": str(uuid.uuid4()),
            "code": code,
            "en": name_en,
            "ko": name_ko,
            "iso": iso,
        })


def downgrade():
    # Intentional no-op — the rebuilt shape and seeded reference data are the
    # baseline other tables (entities, cash_info) now depend on; reverting
    # would orphan their references.
    pass

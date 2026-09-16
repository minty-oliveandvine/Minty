"""Seed (or reset) the identity the Minty browser tests sign in as.

    .venv/Scripts/python.exe scripts/e2e_seed.py            # against the database .env points at
    .venv/Scripts/python.exe scripts/e2e_seed.py --print    # show the ids/env the specs need

Idempotent and narrow: it only ever touches rows it created — the user
``e2e@minty.test``, the entity named ``E2E Petty Cash Shop`` and that entity's reports,
expenses and sale settings. Everything else in the database is left alone, which is
what makes it safe to run against ``minty_cleanse`` (production data) as well as the
old-shape ``postgres`` database.

Each run:

* creates the user if missing, sets the password from ``E2E_MINTY_PASSWORD`` (required),
  approved, normal system role, and REMOVES the user's terms consent so the first
  browser journey always sees the terms modal;
* creates the entity if missing (HKD, HK, Petty Cash module on) with the user as admin,
  seeds the sales methods through the real service (``replace_sales_methods``);
* deletes the entity's reports, expenses, sale detail rows and cash counts so the wizard
  can start from an empty history on every run.

Goes through the app's own models, so it works on whichever schema the code currently
matches - it is re-run at the end of every phase C unit (docs/modernisation_plan.md).
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

E2E_EMAIL = "e2e@minty.test"
E2E_ENTITY_NAME = "E2E Petty Cash Shop"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--print", action="store_true", help="print the ids and the env block the specs need")
    args = parser.parse_args()

    password = os.environ.get("E2E_MINTY_PASSWORD")
    if not password:
        print("E2E_MINTY_PASSWORD is not set; refusing to seed a user with an unknown password.", file=sys.stderr)
        return 2

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    os.environ.setdefault("FLASK_ENV", "development")
    from werkzeug.security import generate_password_hash

    from main import app
    from models.db import (CashInfo, CountryInfo, CurrencyInfo, Entity, EntityFunction,
                           EntityFunctionMap, User, UserEntity, db)

    with app.app_context():
        uri = app.config["SQLALCHEMY_DATABASE_URI"]
        print("database:", uri.rsplit("@", 1)[-1])

        # --- reference data the wizard needs (HKD + denominations, HK) -------------
        hkd = CurrencyInfo.query.filter_by(currency_code="HKD").first()
        if hkd is None:
            hkd = CurrencyInfo(id=str(uuid.uuid4()), currency_code="HKD", currency_name="Hong Kong Dollar",
                               symbol="$", decimal_places=2, is_active=True)
            db.session.add(hkd)
            db.session.flush()
        if not CashInfo.query.filter_by(currency_id=hkd.id).count():
            for order, value in enumerate((1000, 500, 100, 50, 20, 10, 5, 2, 1, 0.5, 0.2, 0.1), start=1):
                db.session.add(CashInfo(currency_id=hkd.id, cash_value=value, type="note" if value >= 10 else "coin",
                                        cash_name=str(value), display_order=order, is_active=True))
        hk = CountryInfo.query.filter_by(country_code="HK").first()
        if hk is None:
            db.session.add(CountryInfo(country_code="HK", alpha3_code="HKG", country_name_en="Hong Kong",
                                       currency_id=hkd.id, is_active=True, display_order=1))
        def module(code, name, description):
            row = EntityFunction.query.filter_by(function_code=code).first()
            if row is None:
                row = EntityFunction(id=str(uuid.uuid4()), function_code=code, function_name=name,
                                     description=description, is_active=True,
                                     created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
                db.session.add(row)
                db.session.flush()
            return row

        petty = module("PETTY_CASH", "Petty Cash", "Petty cash reports")
        bill = module("PAYMENT_REQUEST", "Payment Request", "Bills and payments (Module 2)")
        db.session.commit()

        # --- the user --------------------------------------------------------------
        user = User.query.filter_by(username=E2E_EMAIL).first()
        if user is None:
            user = User(id=str(uuid.uuid4()), email=E2E_EMAIL, username=E2E_EMAIL, first_name="Eve",
                        last_name="Tester", password=generate_password_hash(password, method="pbkdf2:sha256"),
                        system_role=User.SYSTEM_ROLE_NORMAL, approved=True)
            db.session.add(user)
        else:
            user.password = generate_password_hash(password, method="pbkdf2:sha256")
            user.approved = True
        db.session.commit()

        from blueprints.legal.models.terms_consent import TermsConsent

        TermsConsent.query.filter_by(user_id=user.id).delete()
        db.session.commit()

        # --- the entity ------------------------------------------------------------
        entity = Entity.query.filter_by(name=E2E_ENTITY_NAME).first()
        if entity is None:
            entity = Entity(id=str(uuid.uuid4()), name=E2E_ENTITY_NAME, status="disconnected",
                            currency_id=hkd.id, country_code="HK")
            db.session.add(entity)
            db.session.flush()
        if UserEntity.query.filter_by(user_id=user.id, entity_id=entity.id).first() is None:
            db.session.add(UserEntity(user_id=user.id, entity_id=entity.id, role="admin", approved=True))
        for fn in (petty, bill):  # both modules on: the Minty wizard AND the payment-request app
            if EntityFunctionMap.query.filter_by(entity_id=entity.id, entity_function_id=fn.id).first() is None:
                now = datetime.now(timezone.utc)
                db.session.add(EntityFunctionMap(entity_id=entity.id, entity_function_id=fn.id,
                                                 is_enabled=True, created_by=user.id, enabled_at=now,
                                                 created_at=now, updated_at=now))
        db.session.commit()

        # --- petty-cash settings: the dashboard shows "Setup Required" (and hides the wizard)
        #     until the entity has its Xero account/contact mapping. No Xero here: the rows
        #     are local placeholders named E2E-*, enough for the mapping to be complete.
        from models.db import AccountInfo, EntityPettycashSettings, XeroContactSync

        def account(name, kind):
            row = AccountInfo.query.filter_by(entity_id=entity.id, name=name).first()
            if row is None:
                row = AccountInfo(id=str(uuid.uuid4()), entity_id=entity.id, type=kind, name=name,
                                  xero_account_id=str(uuid.uuid4()), xero_code=name.split()[-1], status="ACTIVE")
                db.session.add(row)
                db.session.flush()
            return row

        def contact(name):
            row = XeroContactSync.query.filter_by(entity_id=entity.id, name=name).first()
            if row is None:
                row = XeroContactSync(id=str(uuid.uuid4()), entity_id=entity.id, xero_contact_id=str(uuid.uuid4()),
                                      name=name, category="E2E")
                db.session.add(row)
                db.session.flush()
            return row

        settings = EntityPettycashSettings.query.filter_by(entity_id=entity.id).first()
        if settings is None:
            settings = EntityPettycashSettings(entity_id=entity.id)
            db.session.add(settings)
        settings.pettycash_account_id = account("E2E Petty Cash 090", "BANK").id
        settings.bank_account_id = account("E2E Bank 091", "BANK").id
        settings.cash_sale_account_id = account("E2E Cash Sales 200", "REVENUE").id
        settings.discrepancy_bank_account_id = account("E2E Discrepancy Bank 092", "BANK").id
        settings.discrepancy_account_id = account("E2E Cash Discrepancy 499", "EXPENSE").id
        settings.director_account_id = account("E2E Director Loan 835", "CURRLIAB").id
        settings.cash_sale_contact_id = contact("E2E Cash Customer").id
        settings.director_contact_id = contact("E2E Director").id
        settings.discrepancy_contact_id = contact("E2E Discrepancy").id
        # the expense form's account dropdown reads entity_account_xero (is_active) joined to
        # account_info; its supplier dropdown reads xero_contact_sync (already seeded above)
        from models.db import EntityAccountXero

        for name in ("E2E Office Expenses 429", "E2E Cleaning 408"):
            acc = account(name, "EXPENSE")
            if EntityAccountXero.query.filter_by(account_id=acc.id).first() is None:
                db.session.add(EntityAccountXero(id=str(uuid.uuid4()), account_id=acc.id, name=acc.name,
                                                 type=acc.type, xero_account_id=acc.xero_account_id, is_active=True))
        contact("E2E Stationery Supplier")
        db.session.commit()

        # the payment-request app's "Account Code" picker reads entity_bill_account_xero, a
        # billing-backend table with no Minty model - raw SQL, schema-qualified as always
        from sqlalchemy import text as sql

        for code, name in (("429", "E2E Office Expenses"), ("408", "E2E Cleaning")):
            exists = db.session.execute(sql(
                "SELECT 1 FROM pettycashv2.entity_bill_account_xero WHERE entity_id = :e AND account_code = :c"
            ), {"e": entity.id, "c": code}).first()
            if exists is None:
                db.session.execute(sql(
                    "INSERT INTO pettycashv2.entity_bill_account_xero "
                    "(id, entity_id, account_code, account_name, account_type, is_default, is_active, is_deleted, "
                    " xero_account_id, sort_order, created_by, created_at, updated_at) "
                    "VALUES (:id, :e, :c, :n, 'EXPENSE', false, true, false, :x, 0, :u, now(), now())"
                ), {"id": str(uuid.uuid4()), "e": entity.id, "c": code, "n": name, "x": str(uuid.uuid4()), "u": user.id})
        db.session.commit()

        # --- wipe the entity's report history so the wizard starts clean ----------
        from models.db import Report, ReportCashCount, ReportHistory, ReportSaleDetail, ShareLink, ShopExpense

        report_ids = [r.id for r in Report.query.filter_by(company=entity.id).all()]
        if report_ids:
            ShopExpense.query.filter(ShopExpense.report_id.in_(report_ids)).delete(synchronize_session=False)
            ReportSaleDetail.query.filter(ReportSaleDetail.report_id.in_(report_ids)).delete(synchronize_session=False)
            ReportCashCount.query.filter(ReportCashCount.report_id.in_(report_ids)).delete(synchronize_session=False)
            ReportHistory.query.filter(ReportHistory.report_id.in_(report_ids)).delete(synchronize_session=False)
            ShareLink.query.filter_by(entity_id=entity.id).delete(synchronize_session=False)
            Report.query.filter(Report.id.in_(report_ids)).delete(synchronize_session=False)
            db.session.commit()

        # --- sales methods through the real service --------------------------------
        from blueprints.entity.services.payment_methods import replace_sales_methods

        result = replace_sales_methods(user.id, entity.id, ["Visa", "Alipay"], ["Foodpanda"])
        payload, status = result if isinstance(result, tuple) else (result, 200)
        if status != 200:
            print("sales methods:", payload, file=sys.stderr)
            return 1

        print(f"user    {user.id}  {E2E_EMAIL}")
        print(f"entity  {entity.id}  {E2E_ENTITY_NAME}  (reports wiped: {len(report_ids)})")
        if args.print:
            print()
            print("export E2E_MINTY_USER=" + user.id)
            print("export E2E_MINTY_ENTITY=" + entity.id)
            print("export E2E_MINTY_EMAIL=" + E2E_EMAIL)
            print("export E2E_MINTY_PASSWORD=<the value you seeded with>")
    return 0


if __name__ == "__main__":
    sys.exit(main())

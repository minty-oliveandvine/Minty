# Database and model definitions for report and entity flows.
# Use: db.init_app(app) in app.py after app creation and config.
from __future__ import annotations

import pytz
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
tz = pytz.timezone("Asia/Hong_Kong")

from blueprints.auth.models.user import User  # noqa: E402
from blueprints.auth.models.user_token import UserToken  # noqa: E402
from blueprints.entity.models.cash_info import CashInfo  # noqa: E402
from blueprints.entity.models.entity_cash_setting import EntityCashSetting  # noqa: E402
from blueprints.entity.models.country_info import CountryInfo  # noqa: E402
from blueprints.entity.models.currency_info import CurrencyInfo  # noqa: E402
from blueprints.entity.models.entity import Entity  # noqa: E402
from blueprints.entity.models.entity_cash_detail_v2 import EntityCashDetailV2  # noqa: E402
from blueprints.entity.models.entity_function import EntityFunction, EntityFunctionMap  # noqa: E402  (Django-owned tables; read-only mirror)
from blueprints.entity.models.entity_pettycash_settings import EntityPettycashSettings  # noqa: E402
from blueprints.entity.models.entity_sale_setting import EntitySaleSetting  # noqa: E402
from blueprints.entity.models.sale_info import SaleInfo  # noqa: E402
from blueprints.entity.models.user_entity import UserEntity  # noqa: E402
from blueprints.report.models.report import Report  # noqa: E402
from blueprints.report.models.report_cash_count_draft import ReportCashCountDraft  # noqa: E402
from blueprints.report.models.report_cash_count import ReportCashCount  # noqa: E402
from blueprints.report.models.report_detail import ReportDetail  # noqa: E402
from blueprints.report.models.report_draft import ReportDraft  # noqa: E402
from blueprints.report.models.report_expense_detail import ReportExpenseDetail  # noqa: E402
from blueprints.report.models.report_history import ReportHistory  # noqa: E402
from blueprints.report.models.report_history_draft import ReportHistoryDraft  # noqa: E402
from blueprints.report.models.report_sale_detail import ReportSaleDetail  # noqa: E402
from blueprints.report.models.report_v2 import ReportV2  # noqa: E402
from blueprints.report.models.share_link import ShareLink  # noqa: E402
from blueprints.report.models.shop_expense import ShopExpense  # noqa: E402
from blueprints.report.models.shop_expense_draft import ShopExpenseDraft  # noqa: E402
from blueprints.invitation.models.invitation import Invitation  # noqa: E402
from blueprints.user_management.models.permissions import Permissions  # noqa: E402
from blueprints.user_management.models.role_permissions import RolePermissions  # noqa: E402
from blueprints.user_management.models.roles import Roles  # noqa: E402
from blueprints.xero.models.account_info import AccountInfo  # noqa: E402
from blueprints.xero.models.entity_account_xero import EntityAccountXero  # noqa: E402
from blueprints.xero.models.xero_bank_transaction import XeroBankTransaction  # noqa: E402
from blueprints.xero.models.xero_bank_transfer import XeroBankTransfer  # noqa: E402
from blueprints.xero.models.xero_contact_sync import XeroContactSync  # noqa: E402
from blueprints.xero.models.xero_report_sync import XeroReportSync  # noqa: E402

__all__ = [
    "db",
    "tz",
    "User",
    "Entity",
    "UserEntity",
    "CountryInfo",
    "CurrencyInfo",
    "CashInfo",
    "EntityCashSetting",
    "EntityCashDetailV2",
    "EntityFunction",
    "EntityFunctionMap",
    "EntityPettycashSettings",
    "EntitySaleSetting",
    "SaleInfo",
    "Report",
    "ReportDraft",
    "ShopExpense",
    "ShopExpenseDraft",
    "ReportHistory",
    "ReportHistoryDraft",
    "ReportCashCountDraft",
    "ReportV2",
    "ReportDetail",
    "ReportExpenseDetail",
    "ReportSaleDetail",
    "ShareLink",
    "ReportCashCount",
    "AccountInfo",
    "EntityAccountXero",
    "XeroContactSync",
    "XeroReportSync",
    "XeroBankTransfer",
    "XeroBankTransaction",
    "Roles",
    "Permissions",
    "RolePermissions",
    "Invitation",
]

# --- report_draft -> report mirror (TEMPORARY, Stage 4b) --------------------
# Keeps the paired `report` row current while the wizard still writes to
# report_draft, so reads can be migrated to `report` a module at a time.
# Registered here because this module is the single point every entry path
# imports. Deleted in Stage 5 along with report_draft itself.
from blueprints.report.services.draft_report_mirror import (  # noqa: E402
    register_draft_report_mirror)

register_draft_report_mirror()

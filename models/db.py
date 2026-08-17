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
from blueprints.report.models.report_cash_count import ReportCashCount  # noqa: E402
from blueprints.report.models.report_history import ReportHistory  # noqa: E402
from blueprints.report.models.report_sale_detail import ReportSaleDetail  # noqa: E402
from blueprints.report.models.share_link import ShareLink  # noqa: E402
from blueprints.report.models.shop_expense import ShopExpense  # noqa: E402
from blueprints.invitation.models.invitation import Invitation  # noqa: E402
from blueprints.legal.models.terms_consent import TermsConsent  # noqa: E402
from blueprints.user_management.models.permissions import Permissions  # noqa: E402
from blueprints.user_management.models.role_permissions import RolePermissions  # noqa: E402
from blueprints.user_management.models.roles import Roles  # noqa: E402
from blueprints.xero.models.account_info import AccountInfo  # noqa: E402
from blueprints.xero.models.entity_account_xero import EntityAccountXero  # noqa: E402
from blueprints.xero.models.xero_bank_transaction import XeroBankTransaction  # noqa: E402
from blueprints.xero.models.xero_bank_transfer import XeroBankTransfer  # noqa: E402
from blueprints.xero.models.xero_contact_sync import XeroContactSync  # noqa: E402
from blueprints.xero.models.xero_report_sync import XeroReportSync  # noqa: E402
from blueprints.subscription.models.user_stripe_customer import UserStripeCustomer  # noqa: E402
from blueprints.subscription.models.entity_module_subscription import EntityModuleSubscription  # noqa: E402
from blueprints.subscription.models.entity_billing_consent import EntityBillingConsent  # noqa: E402
from blueprints.subscription.models.billing_plan import BillingPlan  # noqa: E402
from blueprints.subscription.models.billing_policy import BillingPolicy  # noqa: E402
from blueprints.subscription.models.subscription_audit_log import SubscriptionAuditLog  # noqa: E402
from blueprints.subscription.models.subscription_invoice import SubscriptionInvoice, SubscriptionInvoiceLine  # noqa: E402
from blueprints.subscription.models.subscription_email_log import SubscriptionEmailLog  # noqa: E402
from blueprints.subscription.models.subscription_transfer import SubscriptionTransfer  # noqa: E402

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
    "ShopExpense",
    "ReportHistory",
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
    "UserStripeCustomer",
    "EntityModuleSubscription",
    "EntityBillingConsent",
    "BillingPlan",
    "BillingPolicy",
    "SubscriptionAuditLog",
    "SubscriptionInvoice",
    "SubscriptionInvoiceLine",
    "SubscriptionEmailLog",
    "SubscriptionTransfer",
    "TermsConsent",
]


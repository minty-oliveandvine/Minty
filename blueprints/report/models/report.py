import uuid
from datetime import datetime
from typing import Any, cast

from models.db import db, tz


class Report(db.Model):
    __tablename__ = "report"
    __table_args__ = {"schema": "pettycashv2"}
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    transaction_date = db.Column(db.Date, nullable=False)
    next_transaction_date = db.Column(db.Date, nullable=True)
    date = db.Column(db.DateTime, default=lambda: datetime.now(tz))
    opening_balance = db.Column(db.Float, nullable=False)
    cash_addition = db.Column(db.Float, nullable=False, default=0.0)
    adjusted_opening_balance = db.Column(db.Float, nullable=True, default=None)
    cash_sales = db.Column(db.Float, nullable=False, default=0.0)
    visa_sales = db.Column(db.Float, nullable=False, default=0.0)
    alipay_sales = db.Column(db.Float, nullable=False, default=0.0)
    wechat_sales = db.Column(db.Float, nullable=False, default=0.0)
    master_sales = db.Column(db.Float, nullable=False, default=0.0)
    unionpay_sales = db.Column(db.Float, nullable=False, default=0.0)
    amex_sales = db.Column(db.Float, nullable=False, default=0.0)
    octopus_sales = db.Column(db.Float, nullable=False, default=0.0)
    deliveroo_sales = db.Column(db.Float, nullable=False, default=0.0)
    foodpanda_sales = db.Column(db.Float, nullable=False, default=0.0)
    keeta_sales = db.Column(db.Float, nullable=False, default=0.0)
    openrice_sales = db.Column(db.Float, nullable=False, default=0.0)
    shop_sales = db.Column(db.Float, nullable=False, default=0.0)
    delivery_sales = db.Column(db.Float, nullable=False, default=0.0)
    total_sales = db.Column(db.Float, nullable=False, default=0.0)
    expenses = db.Column(db.Float, nullable=False)
    bank_deposit = db.Column(db.Float, nullable=False, default=0.0)
    closing_balance = db.Column(db.Float, nullable=False)
    receipt_files = db.Column(db.Text)
    uploaded_by = db.Column(
        db.String(150), db.ForeignKey("pettycashv2.user.username"), nullable=True
    )
    company = db.Column(db.String(150), nullable=False)
    shop_expenses = db.relationship("ShopExpense", backref="report", lazy=True)
    report_histories = db.relationship(
        "ReportHistory", back_populates="report", cascade="all, delete-orphan"
    )
    xero_integrated_yes = db.Column(db.Boolean, default=False)
    safe_box_balance = db.Column(db.Float, nullable=True)
    discrepancy_amount = db.Column(db.Float, nullable=True, default=0.0)
    discrepancy_reason = db.Column(db.String(300), nullable=True)
    discrepancy_type = db.Column(db.String(20), nullable=True, default="none")
    publishing_status = db.Column(db.String(20), nullable=True, default=None)

    @property
    def total_expenses(self):
        return sum(expense.amount for expense in cast(Any, self.shop_expenses))

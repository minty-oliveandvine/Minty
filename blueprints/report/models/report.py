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
    def sales_by_method(self):
        """Per-method amounts for this report, keyed by catalog code.

        The template-facing replacement for reading ``report.visa_sales`` and
        friends directly: a method added to the ``sales_method`` catalog shows
        up here with no template or model change.

        Falls back to the entity's sale_info row, then to the detail row's own
        type, so amounts whose catalog link predates the migration (or whose
        method has since been deleted) are still returned rather than dropped.
        """
        from blueprints.report.services.shared import sales_by_method_for

        return sales_by_method_for(self.id)

    @property
    def total_expenses(self):
        return sum(expense.amount for expense in cast(Any, self.shop_expenses))

import uuid
from datetime import datetime
from typing import Any, cast

from models.db import db, tz


class ReportDraft(db.Model):
    __tablename__ = "report_draft"
    __table_args__ = {"schema": "pettycashv2"}
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    transaction_date = db.Column(db.Date, nullable=False)
    next_transaction_date = db.Column(db.Date, nullable=True)
    date = db.Column(db.DateTime, default=lambda: datetime.now(tz))
    opening_balance = db.Column(db.Float, nullable=True)
    cash_addition = db.Column(db.Float, nullable=True, default=0.0)
    adjusted_opening_balance = db.Column(db.Float, nullable=True, default=None)
    cash_sales = db.Column(db.Float, nullable=True, default=0.0)
    shop_sales = db.Column(db.Float, nullable=True, default=0.0)
    delivery_sales = db.Column(db.Float, nullable=True, default=0.0)
    total_sales = db.Column(db.Float, nullable=True, default=0.0)
    expenses = db.Column(db.Float, nullable=True)
    bank_deposit = db.Column(db.Float, nullable=True, default=0.0)
    closing_balance = db.Column(db.Float, nullable=True)
    receipt_files = db.Column(db.Text)
    current_section = db.Column(db.String(20), nullable=True, default="opening")
    completed_sections = db.Column(db.JSON, default=list)
    uploaded_by = db.Column(
        db.String(150), db.ForeignKey("pettycashv2.user.username"), nullable=True
    )
    company = db.Column(db.String(150), nullable=False)
    shop_expense_drafts = db.relationship(
        "ShopExpenseDraft", back_populates="report_draft", cascade="all, delete-orphan"
    )
    report_history_drafts = db.relationship(
        "ReportHistoryDraft",
        back_populates="report_draft",
        cascade="all, delete-orphan",
    )
    cashcount_draft = db.relationship(
        "ReportCashCountDraft", back_populates="report_draft"
    )
    status = db.Column(db.String(20), nullable=True, default="draft")
    withdrawal_type = db.Column(db.String(20), nullable=True)
    withdrawal_bank_account = db.Column(db.String(36), nullable=True)
    xero_integrated_yes = db.Column(db.Boolean, default=False)
    # Carried over from Report when a submitted report is reverted to draft, so
    # the "was previously published" signal survives the Report row's deletion
    # and re-submitting can warn about creating duplicates in Xero.
    publishing_status = db.Column(db.String(20), nullable=True, default=None)
    safe_box_balance = db.Column(db.Float, nullable=True)
    discrepancy_amount = db.Column(db.Float, nullable=True, default=0.0)
    discrepancy_reason = db.Column(db.String(300), nullable=True)
    discrepancy_type = db.Column(db.String(20), nullable=True, default="none")

    @property
    def sales_by_method(self):
        """Per-method amounts for this draft, keyed by catalog code.

        Same contract as Report.sales_by_method — see that docstring. A draft
        and its submitted report share an id (ending.py creates the revert
        draft with ``id=full_report.id``), so both resolve the same detail rows.
        """
        from blueprints.report.services.shared import sales_by_method_for

        return sales_by_method_for(self.id)

    @property
    def total_expenses(self):
        return sum(expense.amount for expense in cast(Any, self.shop_expense_drafts))

import uuid
from typing import Any, cast

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import synonym

from blueprints.shared.column_types import MintyUuid, Money, cents, pg_enum
from blueprints.shared.enums import DiscrepancyType, PublishStatus, ReportStatus
from models.db import db


class Report(db.Model):
    """One day's petty-cash report for one company (``report`` in the rebased schema).

    Since C4 the columns are the schema's. The names the code grew up with stay usable as
    synonyms (they compile to the real column in queries too): ``company`` -> ``entity_id``,
    ``cash_sales`` -> ``cashsale_total``, ``expenses`` -> ``expense_total``,
    ``xero_integrated_yes`` -> ``xero_integrated``, ``withdrawal_type`` -> ``cash_addition_type``,
    ``date`` -> ``created_at``. Two figures the old row stored are derived now: ``shop_sales``
    (cash + electronic) and ``delivery_sales`` come from ``report_sale`` rows; the cash-count
    total is the sum of the ``report_cash_count`` rows (``actual_cash_total``). Gone:
    ``receipt_files`` (receipts hang off expense lines), ``withdrawal_bank_account`` (the
    account is the one configured on ``entity_pettycash_settings``, schema item 13).

    ``status`` is the ``report_status`` enum: ``draft`` -> ``submitted`` when the wizard
    finishes, ``published`` when the Xero publish succeeds.
    """

    __tablename__ = "report"
    __table_args__ = (
        db.UniqueConstraint("entity_id", "transaction_date", name="report_entity_date_key"),
        {"schema": "pettycashv3"},
    )

    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id = db.Column(MintyUuid(), db.ForeignKey("pettycashv3.entities.id", ondelete="CASCADE"), nullable=False)
    transaction_date = db.Column(db.Date, nullable=False)
    next_transaction_date = db.Column(db.Date, nullable=True)
    status = db.Column(pg_enum(ReportStatus), nullable=False, default=ReportStatus.DRAFT)
    publishing_status = db.Column(pg_enum(PublishStatus), nullable=False, default=PublishStatus.UNPUBLISHED)
    opening_balance = db.Column(Money(), nullable=True)
    cash_addition = db.Column(Money(), nullable=True, default=0.0)
    adjusted_opening_balance = db.Column(Money(), nullable=True)
    cashsale_total = db.Column(Money(), nullable=True, default=0.0)
    nocashsale_total = db.Column(Money(), nullable=True, default=0.0)
    total_sales = db.Column(Money(), nullable=True, default=0.0)
    # NULL means "not entered yet" - 0.0 would be indistinguishable from genuinely-zero
    # expenses. Readers coalesce.
    expense_total = db.Column(Money(), nullable=True)
    bank_deposit = db.Column(Money(), nullable=True, default=0.0)
    closing_balance = db.Column(Money(), nullable=True)
    safe_box_balance = db.Column(Money(), nullable=True)
    discrepancy_amount = db.Column(Money(), nullable=True, default=0.0)
    discrepancy_type = db.Column(pg_enum(DiscrepancyType), nullable=False, default=DiscrepancyType.NONE)
    discrepancy_reason = db.Column(db.String(300), nullable=True)
    current_section = db.Column(db.String(20), nullable=True)
    completed_sections = db.Column(db.JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    xero_integrated = db.Column(db.Boolean, nullable=True, default=False)
    # 'personal' | 'company': where the money ADDED to the float came from (schema item 13)
    cash_addition_type = db.Column(db.String(20), nullable=True)
    created_by = db.Column(MintyUuid(), db.ForeignKey("pettycashv3.user.id", ondelete="SET NULL"), nullable=True)
    submitted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    published_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    # the pre-C4 names, usable in queries and as attributes
    company = synonym("entity_id")
    cash_sales = synonym("cashsale_total")
    expenses = synonym("expense_total")
    xero_integrated_yes = synonym("xero_integrated")
    withdrawal_type = synonym("cash_addition_type")
    date = synonym("created_at")

    creator = db.relationship("User", foreign_keys=[created_by], lazy="joined")
    shop_expenses = db.relationship("ReportExpense", backref="report", lazy=True)
    report_histories = db.relationship(
        "ReportHistory", back_populates="report", cascade="all, delete-orphan"
    )

    # ---- who ---------------------------------------------------------------------------
    @hybrid_property
    def uploaded_by(self):
        """The creator's username - what the old ``uploaded_by`` column held. Usable in
        queries too (``Report.uploaded_by == name`` and in ``with_entities``): the
        expression is the username looked up from ``user``."""
        return self.creator.username if self.creator is not None else None

    @uploaded_by.inplace.setter
    def _uploaded_by_setter(self, username):
        """Writers still hand over a username; it is resolved to the person's id."""
        if not username:
            self.created_by = None
            return
        from blueprints.auth.models.user import User

        user = User.query.filter_by(username=username).first()
        self.created_by = user.id if user is not None else None

    @uploaded_by.inplace.expression
    @classmethod
    def _uploaded_by_expression(cls):
        from blueprints.auth.models.user import User

        # labelled, so a with_entities() Row carries the attribute's name on every database
        return (
            db.select(User.username).where(User.id == cls.created_by).correlate(cls).scalar_subquery()
            .label("uploaded_by")
        )

    # ---- derived figures ---------------------------------------------------------------
    # The old row stored these; now they are sums over the child tables. As hybrids they
    # stay selectable (``with_entities(Report.shop_sales, ...)``) - the expression is the
    # same sum as a correlated subquery.
    def _sales_by_type(self):
        from blueprints.report.services.shared import sum_sales_by_type

        return sum_sales_by_type(self.id)

    @hybrid_property
    def delivery_sales(self):
        """Sum of the delivery-platform lines (``report_sale`` rows of type ``delivery``)."""
        return self._sales_by_type()["delivery"]

    @delivery_sales.inplace.expression
    @classmethod
    def _delivery_sales_expression(cls):
        from blueprints.entity.models.sale_info import SaleInfo
        from blueprints.report.models.report_sale_detail import ReportSale
        from blueprints.shared.enums import SaleType

        return (
            db.select(db.func.coalesce(db.func.sum(ReportSale.amount), 0.0))
            .select_from(ReportSale)
            .join(SaleInfo, ReportSale.sale_id == SaleInfo.id)
            .where(ReportSale.report_id == cls.id, SaleInfo.type == SaleType.DELIVERY)
            .correlate(cls)
            .scalar_subquery()
            .label("delivery_sales")
        )

    @hybrid_property
    def shop_sales(self):
        """Cash + electronic: everything that is not a delivery platform."""
        return (self.total_sales or 0.0) - self.delivery_sales

    @shop_sales.inplace.expression
    @classmethod
    def _shop_sales_expression(cls):
        return (db.func.coalesce(cls.total_sales, 0.0) - cls.delivery_sales).label("shop_sales")

    @hybrid_property
    def actual_cash_total(self):
        """What the cash count added up to: the sum of the counted denominations.

        ``None`` means "never counted" - which the old column also said with NULL. A
        denomination counted as zero stores no row, so an all-zero count has no rows;
        the wizard marking ``cash_count`` complete is what tells it apart from no count.
        """
        from blueprints.report.models.report_cash_count import ReportCashCount

        total = (
            db.session.query(db.func.sum(ReportCashCount.quantity * ReportCashCount.cash_value))
            .filter(ReportCashCount.report_id == self.id)
            .scalar()
        )
        if total is not None:
            return float(total)
        if "cash_count" in (self.completed_sections or []):
            return 0.0
        return None

    @actual_cash_total.inplace.expression
    @classmethod
    def _actual_cash_total_expression(cls):
        from blueprints.report.models.report_cash_count import ReportCashCount

        counted = (
            db.select(db.func.sum(ReportCashCount.quantity * ReportCashCount.cash_value))
            .where(ReportCashCount.report_id == cls.id)
            .correlate(cls)
            .scalar_subquery()
        )
        # completed_sections is JSON; its text form is the same on both databases
        marked = db.cast(cls.completed_sections, db.Text).like('%"cash_count"%')
        return db.func.coalesce(counted, db.case((marked, 0.0), else_=None)).label("actual_cash_total")

    @property
    def sales_by_method(self):
        """Per-method amounts for this report, keyed by the method's form-field name."""
        from blueprints.report.services.shared import sales_by_method_for

        return sales_by_method_for(self.id)

    @property
    def total_expenses(self):
        return cents(sum(expense.amount or 0 for expense in cast(Any, self.shop_expenses)))

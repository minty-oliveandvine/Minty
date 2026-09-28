"""An expense line and its receipts: ``report_expense``, ``attachment``,
``report_expense_attachment`` in the rebased schema.

Was ``ShopExpense`` / ``shop_expense``; the old class name stays importable. What moved:

* ``account_id`` / ``contact_id`` are FKs to the company's ``account_info`` /
  ``xero_contact_sync`` rows now, not the Xero AccountID / ContactID the old row stored.
  The code still hands over Xero ids (they come straight from the Xero dropdowns), so the
  attributes ``account_id`` / ``contact_id`` are properties: reading gives the Xero id the
  publish payload needs, assigning resolves the Xero id to the company's sync row.
  ``account_code`` and ``contact_name`` read through the sync rows; assigning them resolves
  by code / name. ``item_code`` is gone (schema ERA 3 item 11); it reads as ``""`` and is
  accepted and dropped on write so the expense form's field keeps posting.
* ``files`` (comma-separated S3 keys) and ``s3_key`` became ``Attachment`` rows linked
  through ``ReportExpenseAttachment``. ``files`` still reads as the comma-joined keys and
  still accepts a comma-joined string or a list of keys, so every reader that called
  ``normalize_expense_files(expense.files, expense.s3_key)`` sees what it used to; behind it
  the rows are the record, and they go with the line (CASCADE) - which is what closes F2.
"""

from __future__ import annotations

import mimetypes
import os
from uuid import uuid4

from loguru import logger
from sqlalchemy.orm import synonym

from blueprints.shared.column_types import MintyUuid, Money, pg_enum
from blueprints.report.services.receipt_keys import split_receipt_keys
from blueprints.shared.enums import ExpenseAttachmentRole
from models.db import db
from blueprints.shared.schema import SCHEMA


class Attachment(db.Model):
    """A stored file (``attachment``). Shared with the payment-request app, which keeps
    its own Django model of the same table; Minty only ever creates rows for receipts."""

    __tablename__ = "attachment"
    __table_args__ = {"schema": SCHEMA}
    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid4()))
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.Text, nullable=False)  # the S3 key
    file_extension = db.Column(db.String(20), nullable=False, default="")
    mime_type = db.Column(db.String(100), nullable=False)
    file_size = db.Column(db.BigInteger, nullable=True)
    storage_provider = db.Column(db.String(50), nullable=False, default="s3")
    checksum_sha256 = db.Column(db.String(128), nullable=False, default="")
    uploaded_by = db.Column(MintyUuid(), nullable=True)  # no FK: schema, "the service boundary"
    is_deleted = db.Column(db.Boolean, nullable=False, default=False)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    @property
    def s3_key(self) -> str:
        return self.file_path

    @classmethod
    def for_key(cls, key: str, *, display_name: str | None = None, mime_type: str | None = None,
                uploaded_by=None) -> "Attachment":
        """The row for an S3 key - reused if one exists (the loader does the same), else
        built the way the migration's receipt load (end of 03_data_reports_rebased.sql) builds them."""
        row = cls.query.filter_by(file_path=key).first()
        if row is not None:
            return row
        base = os.path.basename(key) or key
        ext = os.path.splitext(base)[1].lstrip(".").lower()[:20]
        return cls(
            original_name=(display_name or base)[:255],
            stored_name=base[:255],
            file_path=key,
            file_extension=ext,
            mime_type=(mime_type or mimetypes.guess_type(base)[0] or "application/octet-stream")[:100],
            storage_provider="s3",
            checksum_sha256="",
            uploaded_by=uploaded_by,
        )


class ReportExpenseAttachment(db.Model):
    """One file on one expense line (``report_expense_attachment``), in ``sort_order``."""

    __tablename__ = "report_expense_attachment"
    __table_args__ = (
        db.UniqueConstraint("report_expense_id", "attachment_id", name="report_expense_attachment_key"),
        {"schema": SCHEMA},
    )
    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid4()))
    report_expense_id = db.Column(
        MintyUuid(), db.ForeignKey(f"{SCHEMA}.report_expense.id", ondelete="CASCADE"), nullable=False,
    )
    attachment_id = db.Column(
        MintyUuid(), db.ForeignKey(f"{SCHEMA}.attachment.id", ondelete="CASCADE"), nullable=False,
    )
    attachment_role = db.Column(pg_enum(ExpenseAttachmentRole), nullable=False, default=ExpenseAttachmentRole.RECEIPT)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    xero_attachment_id = db.Column(db.String(36), nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.current_timestamp())

    attachment = db.relationship("Attachment", lazy="joined")


class ReportExpense(db.Model):
    __tablename__ = "report_expense"
    __table_args__ = {"schema": SCHEMA}
    id = db.Column(MintyUuid(), primary_key=True, default=lambda: str(uuid4()))
    report_id = db.Column(MintyUuid(), db.ForeignKey(f"{SCHEMA}.report.id", ondelete="CASCADE"), nullable=False)
    # the company's synced rows, not the Xero ids - see the module docstring
    account_row_id = db.Column(
        "account_id", MintyUuid(), db.ForeignKey(f"{SCHEMA}.account_info.id", ondelete="SET NULL"), nullable=True,
    )
    contact_row_id = db.Column(
        "contact_id", MintyUuid(), db.ForeignKey(f"{SCHEMA}.xero_contact_sync.id", ondelete="SET NULL"), nullable=True,
    )
    item = db.Column(db.String(150), nullable=True)
    amount = db.Column(Money(), nullable=False, default=0)
    remarks = db.Column(db.String(300), nullable=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.current_timestamp())

    account = db.relationship("AccountInfo", foreign_keys=[account_row_id], lazy="joined")
    contact = db.relationship("XeroContactSync", foreign_keys=[contact_row_id], lazy="joined")
    attachment_links = db.relationship(
        "ReportExpenseAttachment", cascade="all, delete-orphan", lazy="joined",
        order_by="ReportExpenseAttachment.sort_order",
    )

    # ---- the company this line belongs to (needed to resolve Xero ids) -----------------
    def _entity_id(self):
        if self.report is not None:
            return self.report.entity_id
        if self.report_id:
            from blueprints.report.models.report import Report

            row = db.session.get(Report, self.report_id)
            return row.entity_id if row is not None else None
        return None

    # ---- account -----------------------------------------------------------------------
    @property
    def account_id(self):
        """The Xero AccountID (what the publish payload and the dropdown use)."""
        return self.account.xero_account_id if self.account is not None else None

    @account_id.setter
    def account_id(self, xero_account_id):
        from blueprints.xero.models.account_info import AccountInfo

        if not xero_account_id:
            self.account = None
            return
        entity_id = self._entity_id()
        row = None
        if entity_id:
            row = AccountInfo.query.filter_by(entity_id=entity_id, xero_account_id=str(xero_account_id)).first()
        if row is None:
            logger.warning("report_expense: no account_info row for Xero account %s (entity %s)", xero_account_id, entity_id)
        self.account = row

    @property
    def account_code(self):
        return self.account.xero_code if self.account is not None else None

    @account_code.setter
    def account_code(self, code):
        """Only resolves when no account is linked yet - the id, when given, wins."""
        if self.account is not None or not code:
            return
        from blueprints.xero.models.account_info import AccountInfo

        entity_id = self._entity_id()
        if entity_id:
            self.account = AccountInfo.query.filter_by(entity_id=entity_id, xero_code=str(code)).first()

    # ---- contact -----------------------------------------------------------------------
    @property
    def contact_id(self):
        """The Xero ContactID."""
        return self.contact.xero_contact_id if self.contact is not None else None

    @contact_id.setter
    def contact_id(self, xero_contact_id):
        from blueprints.xero.models.xero_contact_sync import XeroContactSync

        if not xero_contact_id:
            self.contact = None
            return
        entity_id = self._entity_id()
        row = None
        if entity_id:
            row = XeroContactSync.query.filter_by(entity_id=entity_id, xero_contact_id=str(xero_contact_id)).first()
        if row is None:
            logger.warning("report_expense: no xero_contact_sync row for Xero contact %s (entity %s)", xero_contact_id, entity_id)
        self.contact = row

    @property
    def contact_name(self):
        return self.contact.name if self.contact is not None else None

    @contact_name.setter
    def contact_name(self, name):
        """Only resolves when no contact is linked yet - the id, when given, wins."""
        if self.contact is not None or not name:
            return
        from blueprints.xero.models.xero_contact_sync import XeroContactSync

        entity_id = self._entity_id()
        if entity_id:
            self.contact = (
                XeroContactSync.query.filter(
                    XeroContactSync.entity_id == entity_id,
                    db.func.lower(XeroContactSync.name) == str(name).strip().lower(),
                ).first()
            )

    # ---- item_code: gone --------------------------------------------------------------
    @property
    def item_code(self):
        return ""

    @item_code.setter
    def item_code(self, value):  # the form still posts it; the schema has no column for it
        return

    # ---- receipts ----------------------------------------------------------------------
    @property
    def attachments(self) -> list[Attachment]:
        return [link.attachment for link in self.attachment_links if link.attachment is not None]

    @property
    def files(self) -> str:
        """Comma-joined S3 keys, the shape the old column had."""
        return ",".join(a.file_path for a in self.attachments)

    @files.setter
    def files(self, value):
        """Replace the line's receipts with these S3 keys (a comma-joined string or a list)."""
        if isinstance(value, str):
            keys = split_receipt_keys(value)  # commas inside a filename are not separators
        else:
            keys = [str(k).strip() for k in (value or []) if str(k).strip()]
        self.set_receipt_keys(keys)

    def set_receipt_keys(self, keys, *, uploaded_by=None) -> None:
        self.set_receipts([(key, None, None) for key in keys], uploaded_by=uploaded_by)

    def set_receipts(self, uploads, *, uploaded_by=None) -> None:
        """Replace the line's receipts. ``uploads`` are ``(key, original_name, mime_type)``
        triples - the name and type the person uploaded, when the caller has them."""
        current = {link.attachment.file_path: link for link in self.attachment_links if link.attachment is not None}
        new_links = []
        for order, (key, original_name, mime_type) in enumerate(uploads):
            link = current.get(key)
            if link is None:
                link = ReportExpenseAttachment(
                    attachment=Attachment.for_key(key, display_name=original_name, mime_type=mime_type, uploaded_by=uploaded_by)
                )
            link.sort_order = order
            new_links.append(link)
        self.attachment_links = new_links

    def add_receipt(self, key, *, original_name=None, mime_type=None, file_size=None, uploaded_by=None) -> Attachment:
        """Append one receipt (an uploaded file already stored under ``key``)."""
        attachment = Attachment.for_key(key, display_name=original_name, mime_type=mime_type, uploaded_by=uploaded_by)
        if file_size is not None:
            attachment.file_size = file_size
        self.attachment_links.append(
            ReportExpenseAttachment(attachment=attachment, sort_order=len(self.attachment_links))
        )
        return attachment

    @property
    def receipt(self) -> Attachment | None:
        """The first receipt (the old single-file ``s3_key`` / ``files`` JSON meta)."""
        attachments = self.attachments
        return attachments[0] if attachments else None

    @property
    def s3_key(self):
        """The first receipt's key (the old single-file column)."""
        first = self.attachments
        return first[0].file_path if first else None

    @s3_key.setter
    def s3_key(self, value):
        if value and value not in [a.file_path for a in self.attachments]:
            self.set_receipt_keys([value, *[a.file_path for a in self.attachments]])

    @property
    def receipt_keys(self) -> list[str]:
        return [a.file_path for a in self.attachments]


ShopExpense = ReportExpense

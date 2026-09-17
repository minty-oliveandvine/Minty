from uuid import uuid4

from blueprints.shared.column_types import MintyUuid
from models.db import db


class ReportSaleDetail(db.Model):
    __tablename__ = "report_sale_detail"
    __table_args__ = {"schema": "pettycashv2"}
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    # The catalogue row (sale_info.id) - since C3 that is also what entity_sale_setting.sale_id
    # holds, so joining either way names the same method. (C4 renames this table report_sale.)
    sale_id = db.Column(MintyUuid(), db.ForeignKey("pettycashv2.sale_info.id", ondelete="RESTRICT"))
    # Re-pointed at report.id in r4a04 (Stage 3). Formerly FK'd
    # report_v2.report_id; the value never changed, only the parent it is
    # checked against. A draft-shaped report row now exists from draft
    # creation (ensure_report_row_for_draft), so this resolves during entry
    # and not just after submit.
    report_id = db.Column(
        db.String(36), db.ForeignKey("pettycashv2.report.id", ondelete="CASCADE")
    )
    # Catalog link, denormalized on purpose. Resolving the method via
    # sale_id -> sale_info breaks for historical reports: ending.py outer-joins
    # EntitySaleSetting "to include deleted/disabled sale types", so once an entity
    # removes a method the amount survives with no way to tell what it was for.
    # Carrying the catalog id here keeps every report self-describing.
    sale_info_id = db.Column(
        db.String(36),
        db.ForeignKey("pettycashv2.sale_info.id", ondelete="RESTRICT"),
        nullable=True,
    )
    type = db.Column(db.String(50))
    amount = db.Column(db.Float)
    create_at = db.Column(db.DateTime)
    sale_info = db.relationship("SaleInfo", foreign_keys=[sale_info_id], lazy="joined")
    method = db.relationship("SaleInfo", foreign_keys=[sale_id], lazy="joined")


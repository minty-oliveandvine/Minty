"""A company's cash denominations follow its currency.

When a company's currency is set or changed, ``entity_cash_setting`` gets one row per ACTIVE
``cash_info`` row of that currency (``is_active`` true, the catalogue's ``display_order``).
Rows for any other currency are deleted, because a company counts one currency's cash. Rows
already present for the new currency are left alone, so a company's own on/off and order
survive a re-save - the sync is idempotent.

minty-onboarding-api's ``onboarding/services/cash_settings.py`` is the same rule for the
wizard; change the two together.
"""
from loguru import logger

from models.db import CashInfo, EntityCashSetting, db


def sync_cash_settings(entity_id, currency_id) -> None:
    """Make ``entity_cash_setting`` hold the active denominations of ``currency_id``.

    Adds and deletes in the caller's session; the caller commits.
    """
    if not currency_id:
        return
    entity_id = str(entity_id)
    wanted = {
        str(cash_id): order
        for cash_id, order in db.session.query(CashInfo.id, CashInfo.display_order).filter(
            CashInfo.currency_id == str(currency_id),
            CashInfo.is_active.is_(True),
        )
    }
    existing = {
        str(row.cash_id): row
        for row in EntityCashSetting.query.filter_by(entity_id=entity_id).all()
    }
    stale = [row for cash_id, row in existing.items() if cash_id not in wanted]
    for row in stale:
        db.session.delete(row)
    for cash_id, order in wanted.items():
        if cash_id not in existing:
            db.session.add(EntityCashSetting(
                entity_id=entity_id, cash_id=cash_id, is_active=True, display_order=order,
            ))

    if not wanted:
        # A currency with no catalogue leaves the company nothing to count; the cash count
        # reports the same gap when it renders (resolve_denominations_for_entity).
        logger.warning(
            "cash settings: currency {} has no active denominations (entity {})",
            currency_id, entity_id,
        )
    logger.info(
        "cash settings: entity={} currency={} rows={} removed={}",
        entity_id, currency_id, len(wanted), len(stale),
    )

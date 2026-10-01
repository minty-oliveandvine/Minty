"""Entity settings and contact routes."""

import threading
from uuid import uuid4

from flask import current_app, jsonify
from loguru import logger
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from blueprints.xero.services.settings import \
    check_entity_xero_settings_complete
from models.db import (AccountInfo, Entity, EntityAccountXero,
                       EntityPettycashSettings, XeroContactSync, db)
from blueprints.shared.schema import SCHEMA

# Columns on entity_pettycash_settings naming a row in account_info or
# xero_contact_sync. Both parents are FK'd ON DELETE SET NULL, so the deletes
# in invalidate_entity_xero_cache would null these anyway; clearing them
# explicitly keeps the consequence visible rather than leaving it to a
# constraint the reader has to go and look up.
_ORG_SCOPED_SETTINGS_COLUMNS = (
    "pettycash_account_id",
    "bank_account_id",
    "cash_sale_account_id",
    "discrepancy_bank_account_id",
    "discrepancy_account_id",
    "director_account_id",
    "cash_sale_contact_id",
    "director_contact_id",
    "discrepancy_contact_id",
)


def invalidate_entity_xero_cache(entity_id, old_org_id):
    """Drop every cached Xero object belonging to ``old_org_id``.

    Called when an entity moves to a DIFFERENT Xero organisation. Contact ids,
    account ids and account codes are all tenant-scoped: an id issued by the
    old org means nothing in the new one, so leaving these rows behind makes
    publishing target contacts and accounts that do not exist there.

    Must run BEFORE ``entity.xero_org_id`` is overwritten and before
    ``sync_all_accounts_and_contacts_background`` starts, or the sync thread
    layers new-org rows on top of the old ones with no way to tell them apart.

    Does not commit -- the caller does, so the invalidation and the org write
    land in one transaction.

    This is the ONLY path that deletes contact rows. Do not call it from a
    sync: ``sync_contacts_if_changed`` deliberately never deletes, because a
    contact merely missing from a Xero fetch is not a contact that is gone
    (see tests/test_xero_contact_sync_no_mass_delete.py). An org change is a
    different thing entirely, and is the one case where deleting is correct.
    """
    if not entity_id or not old_org_id:
        return  # first connect, or nothing cached to invalidate

    logger.info(
        f"Entity {entity_id} is leaving Xero org {old_org_id}: clearing "
        "cached contacts, accounts and account mappings"
    )

    # 1. Account and contact mappings, explicitly (see the note above).
    settings_row = EntityPettycashSettings.query.filter_by(
        entity_id=entity_id
    ).first()
    if settings_row is not None:
        for column in _ORG_SCOPED_SETTINGS_COLUMNS:
            setattr(settings_row, column, None)

    # 2. Contacts for the org being left. Scoped to old_org_id so any row
    #    already written for the incoming org survives.
    contacts_removed = XeroContactSync.query.filter_by(
        entity_id=entity_id, xero_org_id=str(old_org_id)
    ).delete(synchronize_session=False)

    # 3. Accounts. account_info carries no org column, so it can only be
    #    cleared wholesale; the post-connect sync repopulates it from the new
    #    org. entity_account_xero FKs account_info.id ON DELETE CASCADE and
    #    goes with it.
    accounts_removed = AccountInfo.query.filter_by(entity_id=entity_id).delete(
        synchronize_session=False
    )

    # 4. entity_bill_account_xero is NOT entity_account_xero, despite the
    #    name. It holds no FK to account_info, so step 3's cascade does not
    #    reach it. It is backfilled FROM account_info, so deleting it lets
    #    that backfill rebuild it against the new org. Raw SQL because Minty
    #    has no model for this table (billing-backend owns it).
    #    Guarded: billing-backend owns this table's DDL, so Minty must not
    #    assume it exists. A missing table here must not take down the OAuth
    #    callback that called us.
    try:
        bill_accounts_removed = db.session.execute(
            text(
                f"DELETE FROM {SCHEMA}.entity_bill_account_xero "
                "WHERE entity_id = :entity_id"
            ),
            {"entity_id": str(entity_id)},
        ).rowcount
    except Exception as exc:  # pragma: no cover - depends on deployment state
        bill_accounts_removed = 0
        logger.warning(
            f"Could not clear entity_bill_account_xero for entity "
            f"{entity_id}: {exc}. Bill account codes from the old org may "
            "still be offered until the next sync rebuilds them."
        )

    logger.info(
        f"Entity {entity_id} Xero cache cleared: {contacts_removed} contacts, "
        f"{accounts_removed} accounts, {bill_accounts_removed} bill accounts. "
        "Account and contact mappings are now unset and must be re-selected."
    )


# Columns refreshed when an account_info row already exists for an
# (entity_id, xero_account_id) pair. id / entity_id / xero_account_id are the
# identity and are never updated.
_ACCOUNT_INFO_UPSERT_COLS = (
    "name", "type", "xero_code", "status", "class_type",
    "bank_account_number", "bank_account_type", "description",
)


def _run_in_background(label, target, *args, entity_id, flask_app=None,
                       thread_name=None):
    """Run ``target(*args)`` in a daemon thread under an app context.

    Shared by the ``*_background`` fire-and-forget wrappers below. If the work
    raises, the thread logs and exits silently — callers are page renders that
    must still succeed from cached DB data when Xero is unreachable.

    ``label`` is the wrapper's own name, used verbatim in both log lines so
    existing log greps keep working.
    """
    if flask_app is None:
        flask_app = current_app._get_current_object()

    def _run():
        with flask_app.app_context():
            try:
                target(*args)
            except Exception as exc:
                logger.error("%s failed entity=%s: %s", label, entity_id, exc)

    kwargs = {"target": _run, "daemon": True}
    if thread_name:
        kwargs["name"] = thread_name
    threading.Thread(**kwargs).start()
    logger.info("%s: started entity=%s", label, entity_id)


def _upsert_account_info(values: dict):
    """Insert an account_info row, or update it on an (entity_id,
    xero_account_id) conflict.

    Idempotent under concurrent background syncs: the unique constraint
    ``uq_account_entity_xero`` (the schema's name; C5) turns what used to be a
    duplicate-producing race into a no-op update. Falls back to a plain insert when
    xero_account_id is missing (NULLs don't participate in the constraint). On any
    other database (the SQLite test path) it is a get-or-update, which has the same
    result without the race protection.
    """
    if not values.get("xero_account_id"):
        db.session.add(AccountInfo(**values))
        return
    set_ = {c: values[c] for c in _ACCOUNT_INFO_UPSERT_COLS if c in values}
    if db.engine.dialect.name != "postgresql":
        row = AccountInfo.query.filter_by(
            entity_id=values["entity_id"], xero_account_id=values["xero_account_id"]
        ).first()
        if row is None:
            db.session.add(AccountInfo(**values))
        else:
            for column, value in set_.items():
                setattr(row, column, value)
        return
    stmt = (
        pg_insert(AccountInfo.__table__)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_account_entity_xero",
            set_=set_,
        )
    )
    db.session.execute(stmt)

def _norm_account_code(raw) -> str:
    if raw is None:
        return ""
    s = str(raw).strip()
    return s




def reconcile_account_info_status(entity_id, access_token, xero_org_id):
    """Fetch ACTIVE accounts from Xero and reconcile account_info for an entity.

    - Rows present in Xero's ACTIVE snapshot → status='ACTIVE' (re-activates INACTIVE).
    - Rows absent from the ACTIVE snapshot → hard-deleted.
    - Rows currently marked status='ARCHIVED' → hard-deleted unconditionally
      (stale-data sweep; account_info should never hold archived accounts).

    Returns (activated_count, deleted_count).
    """
    from blueprints.xero.services.integration import get_accounts_from_xero

    if not access_token or not xero_org_id:
        logger.warning(
            "reconcile_account_info_status skipped: missing token or xero_org_id "
            "entity=%s", entity_id,
        )
        return 0, 0

    logger.info("reconcile_account_info_status: fetching ACTIVE accounts from Xero entity=%s", entity_id)
    try:
        xero_accounts = get_accounts_from_xero(
            access_token,
            xero_org_id,
            where='Status=="ACTIVE"',
            token_validated=True,
        )
    except Exception as exc:
        logger.error(
            "reconcile_account_info_status: Xero fetch failed entity=%s: %s",
            entity_id, exc,
        )
        return 0, 0

    if xero_accounts is None:
        xero_accounts = []

    active_xero_ids = {
        acc.get("AccountID") for acc in xero_accounts if acc.get("AccountID")
    }
    logger.info(
        "reconcile_account_info_status: entity=%s xero_active_count=%s",
        entity_id, len(active_xero_ids),
    )

    db_accounts = AccountInfo.query.filter_by(entity_id=entity_id).all()

    activated = 0
    deleted = 0
    for db_acc in db_accounts:
        # Sweep stale ARCHIVED rows unconditionally. account_info should
        # never hold archived accounts; if the underlying account is still
        # ACTIVE in Xero, the row is recreated by sync_xero_accounts_to_db
        # on the next pass.
        if db_acc.status == "ARCHIVED":
            logger.info(
                "reconcile_account_info_status: deleting stale ARCHIVED account "
                "%s (code=%s) entity=%s",
                db_acc.xero_account_id, db_acc.xero_code, entity_id,
            )
            db.session.delete(db_acc)
            deleted += 1
            continue
        if not db_acc.xero_account_id:
            continue
        if db_acc.xero_account_id in active_xero_ids:
            # Re-activate accounts that were INACTIVE.
            # When syncing, if the account is ACTIVE in Xero, the database
            # should match Xero's state (override user preference).
            if db_acc.status == "INACTIVE":
                logger.info(
                    "reconcile_account_info_status: activating account %s (code=%s) "
                    "old_status=%s entity=%s",
                    db_acc.xero_account_id, db_acc.xero_code, db_acc.status, entity_id,
                )
                db_acc.status = "ACTIVE"
                activated += 1
        elif active_xero_ids:
            # Not in the ACTIVE Xero snapshot → hard delete (cascades
            # entity_account_xero; SET NULLs entity_pettycash_settings refs).
            # Guarded by a non-empty snapshot so a failed/empty Xero fetch
            # can't wipe the table.
            logger.info(
                "reconcile_account_info_status: deleting account %s (code=%s) "
                "no longer ACTIVE in Xero entity=%s",
                db_acc.xero_account_id, db_acc.xero_code, entity_id,
            )
            db.session.delete(db_acc)
            deleted += 1

    if activated or deleted:
        db.session.commit()
        logger.info(
            "reconcile_account_info_status: entity=%s activated=%s deleted=%s",
            entity_id, activated, deleted,
        )
    else:
        logger.info("reconcile_account_info_status: entity=%s no changes needed", entity_id)

    return activated, deleted


def sync_xero_accounts_to_db(entity_id, access_token, xero_org_id):
    """Fetch ACTIVE accounts from Xero and reconcile account_info for an entity.

    This is the sync used on the Xero settings page GET. It fetches only
    Status==ACTIVE accounts (archived accounts are not synced):

    - Account in the ACTIVE snapshot → set DB status='ACTIVE'
      (reactivates a row previously ARCHIVED/INACTIVE)
    - Account in DB but absent from the ACTIVE snapshot → HARD DELETE the row
      (cascades entity_account_xero; SET NULLs entity_pettycash_settings refs)
    - Account in Xero but not yet in DB → upsert as a new account_info row

    The type-based allowlist filter (owners_account, etc.) is NOT applied here;
    that filter is only applied when building template context for display.

    Returns (upserted_count, activated_count, deleted_count).
    """
    from blueprints.xero.services.integration import get_accounts_from_xero

    if not access_token or not xero_org_id:
        logger.warning(
            "sync_xero_accounts_to_db skipped: missing token or xero_org_id entity=%s",
            entity_id,
        )
        return 0, 0, 0

    logger.info(
        "sync_xero_accounts_to_db: fetching ALL accounts from Xero entity=%s",
        entity_id,
    )
    try:
        # Only ACTIVE accounts — archived accounts are not synced.
        xero_accounts = get_accounts_from_xero(
            access_token,
            xero_org_id,
            where='Status=="ACTIVE"',
            token_validated=True,
        )
    except Exception as exc:
        logger.error(
            "sync_xero_accounts_to_db: Xero fetch failed entity=%s: %s",
            entity_id,
            exc,
        )
        return 0, 0, 0

    if not xero_accounts:
        logger.info(
            "sync_xero_accounts_to_db: no accounts returned from Xero entity=%s",
            entity_id,
        )
        return 0, 0, 0

    # Build lookup: xero_account_id → xero status string ('ACTIVE' or other)
    xero_by_id: dict[str, str] = {}
    for acc in xero_accounts:
        aid = acc.get("AccountID")
        if not aid:
            continue
        raw_status = acc.get("Status")
        xero_status = (
            str(raw_status).strip().upper()
            if raw_status is not None and str(raw_status).strip()
            else "ACTIVE"
        )
        xero_by_id[aid] = xero_status

    logger.info(
        "sync_xero_accounts_to_db: entity=%s xero_total=%s",
        entity_id,
        len(xero_by_id),
    )

    # Load all existing DB rows for this entity.
    db_accounts = AccountInfo.query.filter_by(entity_id=entity_id).all()
    existing_by_xero_id = {
        acc.xero_account_id: acc
        for acc in db_accounts
        if acc.xero_account_id
    }

    activated = 0
    deleted = 0
    upserted = 0

    # --- Reconcile existing DB rows ---
    # A row whose account is no longer in the ACTIVE Xero snapshot is hard-
    # deleted (archived accounts are not kept). Deleting cascades to
    # entity_account_xero (FK ON DELETE CASCADE) and SET NULLs any
    # entity_pettycash_settings references.
    for db_acc in db_accounts:
        # Sweep stale ARCHIVED rows unconditionally — account_info should
        # never hold archived accounts. The upsert loop below recreates the
        # row if Xero still has it ACTIVE.
        if db_acc.status == "ARCHIVED":
            logger.info(
                "sync_xero_accounts_to_db: deleting stale ARCHIVED account %s "
                "(code=%s) entity=%s",
                db_acc.xero_account_id,
                db_acc.xero_code,
                entity_id,
            )
            if db_acc.xero_account_id:
                existing_by_xero_id.pop(db_acc.xero_account_id, None)
            db.session.delete(db_acc)
            deleted += 1
            continue
        if not db_acc.xero_account_id:
            continue
        if db_acc.xero_account_id in xero_by_id:
            # Still ACTIVE in Xero → ensure DB status is ACTIVE.
            if db_acc.status != "ACTIVE":
                logger.info(
                    "sync_xero_accounts_to_db: activating account %s (code=%s) "
                    "old_status=%s entity=%s",
                    db_acc.xero_account_id,
                    db_acc.xero_code,
                    db_acc.status,
                    entity_id,
                )
                db_acc.status = "ACTIVE"
                activated += 1
        else:
            logger.info(
                "sync_xero_accounts_to_db: deleting account %s (code=%s) "
                "no longer ACTIVE in Xero entity=%s",
                db_acc.xero_account_id,
                db_acc.xero_code,
                entity_id,
            )
            db.session.delete(db_acc)
            deleted += 1

    # --- Upsert new accounts from Xero not yet in DB ---
    # The Xero fetch is filtered to Status=="ACTIVE", so every row inserted
    # here is necessarily ACTIVE — archived accounts never reach account_info.
    for xero_acc in xero_accounts:
        aid = xero_acc.get("AccountID")
        if not aid or aid in existing_by_xero_id:
            continue
        _upsert_account_info({
            "id": str(uuid4()),
            "entity_id": entity_id,
            "xero_account_id": aid,
            "name": _trunc(xero_acc.get("Name", ""), 80),
            "type": _trunc(xero_acc.get("Type", ""), 50),
            "xero_code": _trunc(xero_acc.get("Code", ""), 50),
            "status": "ACTIVE",
            "class_type": _trunc(xero_acc.get("Class", ""), 50),
            "bank_account_number": _trunc(xero_acc.get("BankAccountNumber", ""), 50),
            "bank_account_type": _trunc(xero_acc.get("BankAccountType", ""), 50),
            "description": _trunc(xero_acc.get("Description", ""), 255),
        })
        existing_by_xero_id[aid] = True  # prevent duplicates in same loop
        upserted += 1
        logger.info(
            "sync_xero_accounts_to_db: inserted new account %s (code=%s "
            "type=%s) entity=%s",
            aid,
            xero_acc.get("Code"),
            xero_acc.get("Type"),
            entity_id,
        )

    if activated or deleted or upserted:
        db.session.commit()
        logger.info(
            "sync_xero_accounts_to_db: entity=%s upserted=%s activated=%s deleted=%s",
            entity_id,
            upserted,
            activated,
            deleted,
        )
    else:
        logger.info(
            "sync_xero_accounts_to_db: entity=%s no changes needed", entity_id
        )

    # Mirror the freshly-reconciled account_info rows into
    # entity_account_xero so the petty cash CoA table stays in sync. Guarded
    # so an EAX failure can't undo the account_info sync above.
    try:
        sync_xero_coa_pettycash(entity_id, xero_org_id)
    except Exception as eax_exc:
        db.session.rollback()  # a failed statement leaves the transaction aborted
        logger.warning(
            "sync_xero_accounts_to_db: entity_account_xero sync skipped "
            "entity=%s: %s",
            entity_id,
            eax_exc,
        )

    # Same idea for Module 2 (bills): backfill entity_bill_account_xero from
    # the reconciled account_info rows. Independent try so a bill failure can't
    # affect the petty cash sync above (or vice versa).
    try:
        sync_xero_coa_bill(entity_id)
    except Exception as bill_exc:
        db.session.rollback()
        logger.warning(
            "sync_xero_accounts_to_db: entity_bill_account_xero sync skipped "
            "entity=%s: %s",
            entity_id,
            bill_exc,
        )

    return upserted, activated, deleted


def sync_xero_coa_pettycash(entity_id, xero_org_id=None):
    """Ensure every petty-cash-eligible account_info row has an
    entity_account_xero row for this entity.

    Reads the already-synced account_info table (no Xero API call) and inserts
    a matching entity_account_xero row for any eligible account that does not
    have one yet. Eligible == account type in COA_INCLUDED_TYPES (the petty
    cash CoA allowlist).

    Insert-only with respect to is_active: existing EAX rows keep their
    is_active flag (preserving the user's saved CoA tick selection) and only
    have their denormalized fields refreshed. Newly inserted rows default
    is_active from the account's status (ACTIVE -> True). Nothing is deleted.

    Designed to run together with sync_xero_accounts_to_db on the settings
    page GET. Returns (inserted, refreshed).
    """
    eligible_accounts = AccountInfo.query.filter(
        AccountInfo.entity_id == entity_id,
        AccountInfo.type.in_(list(COA_INCLUDED_TYPES)),
    ).all()

    existing_eax = (
        db.session.query(EntityAccountXero)
        .join(AccountInfo, EntityAccountXero.account_id == AccountInfo.id)
        .filter(AccountInfo.entity_id == entity_id)
        .all()
    )
    existing_by_account_id = {eax.account_id: eax for eax in existing_eax}

    inserted = 0
    refreshed = 0

    for acc in eligible_accounts:
        eax = existing_by_account_id.get(acc.id)
        if eax is None:
            db.session.add(
                EntityAccountXero(
                    id=str(uuid4()),
                    account_id=acc.id,
                    name=acc.name,
                    type=acc.type,
                    xero_org_id=xero_org_id,
                    xero_account_id=acc.xero_account_id,
                    is_active=(acc.status == "ACTIVE"),
                )
            )
            inserted += 1
        else:
            # Refresh denormalized fields, but leave is_active untouched so the
            # user's saved CoA selection survives this unattended sync.
            eax.name = acc.name
            eax.type = acc.type
            if xero_org_id:
                eax.xero_org_id = xero_org_id
            eax.xero_account_id = acc.xero_account_id
            refreshed += 1

    if inserted or refreshed:
        db.session.commit()
        logger.info(
            "sync_xero_coa_pettycash: entity={} inserted={} refreshed={} "
            "(eligible={})",
            entity_id,
            inserted,
            refreshed,
            len(eligible_accounts),
        )
    else:
        logger.info(
            "sync_xero_coa_pettycash: entity={} no eligible accounts", entity_id
        )

    return inserted, refreshed


def sync_xero_coa_bill(entity_id, user_id=""):
    """Ensure every bill-eligible account_info row has an
    entity_bill_account_xero row for this entity.

    Module 2 (bills) counterpart of sync_xero_coa_pettycash. Reads the
    already-synced account_info table (no Xero API call) and inserts a matching
    pettycashv3.entity_bill_account_xero row for any eligible account that does
    not have one yet. Eligible == account type in BILL_COA_INCLUDED_TYPES
    (the bill CoA allowlist, which also includes FIXED).

    Insert/refresh preserves is_active / is_deleted on existing rows. Newly
    inserted rows default is_active from the account's status (ACTIVE -> true),
    is_deleted=false. After insert/refresh, bill rows orphaned from
    account_info (no matching account_info row for this entity by
    xero_account_id) are HARD DELETED — an application-level cascade to mirror
    entity_account_xero's FK CASCADE, since this table has no FK. Guarded by a
    non-empty account_info so a transient empty state can't wipe the table.

    Matched by xero_account_id (this table has no account_info FK). Designed to
    run together with sync_xero_accounts_to_db on the settings page GET.
    Returns (inserted, refreshed).
    """
    _TBL = f"{SCHEMA}.entity_bill_account_xero"

    eligible_accounts = AccountInfo.query.filter(
        AccountInfo.entity_id == entity_id,
        AccountInfo.type.in_(list(BILL_COA_INCLUDED_TYPES)),
        AccountInfo.xero_account_id.isnot(None),
    ).all()

    existing_rows = db.session.execute(
        text(f"SELECT xero_account_id FROM {_TBL} WHERE entity_id = :eid"),
        {"eid": entity_id},
    ).fetchall()
    ids_in_db = {row[0] for row in existing_rows}

    inserted = 0
    refreshed = 0

    for acc in eligible_accounts:
        xero_id = acc.xero_account_id
        if not xero_id:
            continue
        code = _norm_account_code(acc.xero_code)
        name = acc.name or ""
        acc_type = acc.type or ""

        if xero_id in ids_in_db:
            # Refresh denormalized fields only; leave is_active / is_deleted as
            # the user left them.
            db.session.execute(
                text(
                    f"UPDATE {_TBL} "
                    "SET account_code = :code, account_name = :name, "
                    "    account_type = :type, updated_at = NOW() "
                    "WHERE entity_id = :eid AND xero_account_id = :xero_id"
                ),
                {"eid": entity_id, "code": code, "name": name,
                 "type": acc_type, "xero_id": xero_id},
            )
            refreshed += 1
        else:
            db.session.execute(
                text(
                    f"INSERT INTO {_TBL} "
                    "(id, entity_id, account_code, account_name, account_type, "
                    " is_default, is_active, is_deleted, xero_account_id, "
                    " sort_order, created_by, created_at, updated_at) "
                    "VALUES (:id, :eid, :code, :name, :type, "
                    "        false, :active, false, :xero_id, 0, :uid, "
                    "        NOW(), NOW())"
                ),
                # created_by is a uuid column: the unattended sync has no person
                {"id": str(uuid4()), "eid": entity_id, "code": code,
                 "name": name, "type": acc_type, "xero_id": xero_id,
                 "uid": (str(user_id) or None), "active": (acc.status == "ACTIVE")},
            )
            ids_in_db.add(xero_id)
            inserted += 1

    # Hard-delete bill rows orphaned from account_info — application-level
    # cascade for a table that has no FK to account_info. Guarded by a non-empty
    # account_info so a transient empty state can't wipe the table.
    deleted = 0
    acct_count = AccountInfo.query.filter_by(entity_id=entity_id).count()
    if acct_count:
        del_result = db.session.execute(
            text(
                f"DELETE FROM {_TBL} b "
                "WHERE b.entity_id = :eid "
                "AND NOT EXISTS ("
                f"  SELECT 1 FROM {SCHEMA}.account_info a "
                "  WHERE a.entity_id = :eid "
                "    AND a.xero_account_id = b.xero_account_id"
                ")"
            ),
            {"eid": entity_id},
        )
        deleted = getattr(del_result, "rowcount", 0) or 0

    if inserted or refreshed or deleted:
        db.session.commit()
        logger.info(
            "sync_xero_coa_bill: entity=%s inserted=%s refreshed=%s deleted=%s "
            "(eligible=%s)",
            entity_id,
            inserted,
            refreshed,
            deleted,
            len(eligible_accounts),
        )
    else:
        logger.info(
            "sync_xero_coa_bill: entity=%s no changes", entity_id
        )

    return inserted, refreshed


def sync_xero_accounts_to_db_background(
    entity_id, access_token, xero_org_id, flask_app=None
):
    """Fire-and-forget version — runs sync_xero_accounts_to_db in a daemon thread.

    Safe to call on every Xero settings page GET: if Xero is unreachable the
    thread exits silently and the page still renders from cached DB data.
    """
    _run_in_background(
        "sync_xero_accounts_to_db_background",
        sync_xero_accounts_to_db,
        entity_id, access_token, xero_org_id,
        entity_id=entity_id,
        flask_app=flask_app,
        thread_name=f"XeroAccountsSync-{entity_id}",
    )


def sync_chart_of_accounts_if_changed(entity_id, access_token, xero_org_id, user_id=""):
    """Compare Xero live accounts against both DB tables; sync only when different.

    Checks for differences in account codes, names, types, and active status
    between Xero and the local DB. If any difference is found, syncs both:
      - Module 1: account_info (EXPENSE/DIRECTCOSTS)
      - Module 2: entity_bill_account_xero
    Returns dict with keys: changed (bool), module1_synced, module2_synced.
    """
    from blueprints.xero.services.integration import get_accounts_from_xero

    result = {"changed": False, "module1_synced": False, "module2_synced": False}

    if not access_token or not xero_org_id:
        logger.warning(
            "sync_chart_of_accounts_if_changed: skipped (no token/org) entity=%s",
            entity_id,
        )
        return result

    try:
        xero_accounts = get_accounts_from_xero(
            access_token,
            xero_org_id,
            where='Status=="ACTIVE"',
            token_validated=True,
        )
    except Exception as exc:
        logger.warning(
            "sync_chart_of_accounts_if_changed: Xero fetch failed entity=%s: %s",
            entity_id, exc,
        )
        return result

    if not xero_accounts:
        return result

    # --- Build Xero snapshot keyed by AccountID ---
    xero_by_id = {}
    for acc in xero_accounts:
        aid = acc.get("AccountID")
        if aid:
            xero_by_id[aid] = {
                "code": str(acc.get("Code", "")).strip(),
                "name": acc.get("Name", ""),
                "type": acc.get("Type", ""),
                "system_account": acc.get("SystemAccount") or "",
            }

    # --- Compare Module 1: account_info (EXPENSE/DIRECTCOSTS) ---
    m1_changed = _check_account_info_diff(entity_id, xero_by_id)

    # --- Compare Module 2: entity_bill_account_xero ---
    m2_changed = _check_bill_account_diff(entity_id, xero_by_id)

    if not m1_changed and not m2_changed:
        logger.info(
            "sync_chart_of_accounts_if_changed: no changes detected entity=%s",
            entity_id,
        )
        return result

    result["changed"] = True
    logger.info(
        "sync_chart_of_accounts_if_changed: changes detected entity=%s m1=%s m2=%s",
        entity_id, m1_changed, m2_changed,
    )

    # --- Sync Module 1 ---
    if m1_changed:
        try:
            reconcile_account_info_status(entity_id, access_token, xero_org_id)

            # Refresh only: the petty cash ticks live on entity_account_xero.is_active,
            # which this never touches.
            sync_expense_account_info_from_xero(entity_id, access_token, xero_org_id)
            db.session.commit()
            result["module1_synced"] = True
            logger.info(
                "sync_chart_of_accounts_if_changed: Module 1 synced entity=%s",
                entity_id,
            )
        except Exception:
            db.session.rollback()
            logger.exception(
                f"sync_chart_of_accounts_if_changed: Module 1 sync failed entity={entity_id}"
            )

    # --- Sync Module 2 ---
    if m2_changed:
        try:
            # account_info was refreshed by Module 1 above (bill types are a
            # subset of the account_info-eligible types), so backfill the bill
            # CoA table from it. Insert-only: no soft-delete/reconcile here.
            sync_xero_coa_bill(entity_id, user_id=user_id)
            result["module2_synced"] = True
            logger.info(
                "sync_chart_of_accounts_if_changed: Module 2 synced entity=%s",
                entity_id,
            )
        except Exception:
            db.session.rollback()
            logger.exception(
                f"sync_chart_of_accounts_if_changed: Module 2 sync failed entity={entity_id}"
            )

    return result


def _check_account_info_diff(entity_id, xero_by_id):
    """Compare Module 1 account_info chart of accounts rows against Xero snapshot.

    No account-type filtering — every type is compared (no allowlist, no
    denylist).
    """
    db_accounts = AccountInfo.query.filter(
        AccountInfo.entity_id == entity_id,
    ).all()

    db_by_xero_id = {}
    for acc in db_accounts:
        if acc.xero_account_id:
            db_by_xero_id[acc.xero_account_id] = {
                "code": (acc.xero_code or "").strip(),
                "name": acc.name or "",
                "type": acc.type or "",
                "status": acc.status or "",
            }

    # No type filtering — compare against the full Xero snapshot.
    xero_eligible = dict(xero_by_id)

    # Check for new accounts in Xero not in DB
    for aid in xero_eligible:
        if aid not in db_by_xero_id:
            return True

    # Check for accounts in DB that are no longer ACTIVE in Xero.
    # Skip INACTIVE rows — those are user-deselected and intentionally absent
    # from the active set; they are not a Xero-driven diff.
    # ARCHIVED rows always signal a diff so reconcile can sweep them.
    for aid, db_info in db_by_xero_id.items():
        if db_info["status"] == "ARCHIVED":
            return True
        if db_info["status"] == "INACTIVE":
            continue
        if aid not in xero_eligible:
            return True

    # Check for changed metadata
    for aid, xero_info in xero_eligible.items():
        if aid in db_by_xero_id:
            db_info = db_by_xero_id[aid]
            if (db_info["code"] != xero_info["code"]
                    or db_info["name"] != xero_info["name"]
                    or db_info["type"] != xero_info["type"]):
                return True

    return False


def _check_bill_account_diff(entity_id, xero_by_id):
    """Compare Module 2 entity_bill_account_xero rows against Xero snapshot."""
    _TBL = f"{SCHEMA}.entity_bill_account_xero"

    rows = db.session.execute(
        text(
            f"SELECT xero_account_id, TRIM(account_code) as account_code, "
            f"       account_name, account_type, is_deleted "
            f"FROM {_TBL} WHERE entity_id = :eid"
        ),
        {"eid": entity_id},
    ).fetchall()

    db_by_xero_id = {}
    for r in rows:
        if r[0]:
            db_by_xero_id[r[0]] = {
                "code": (r[1] or "").strip(),
                "name": r[2] or "",
                "type": r[3] or "",
                "is_deleted": r[4],
            }

    # Filter Xero snapshot to accounts eligible for Module 2 (bill CoA).
    # Mirrors BILL_COA_INCLUDED_TYPES so the diff check never signals a change
    # for accounts that the bill CoA backfill would exclude anyway.
    xero_bill = {
        aid: info for aid, info in xero_by_id.items()
        if info.get("type") in BILL_COA_INCLUDED_TYPES
    }

    # Check for new accounts in Xero not in DB
    for aid in xero_bill:
        if aid not in db_by_xero_id:
            return True

    # Check for accounts in DB that should be soft-deleted
    for aid, db_info in db_by_xero_id.items():
        if db_info["is_deleted"]:
            continue
        if aid not in xero_bill:
            return True

    # Check for changed metadata
    for aid, xero_info in xero_bill.items():
        if aid in db_by_xero_id:
            db_info = db_by_xero_id[aid]
            if (db_info["code"] != xero_info["code"]
                    or db_info["name"] != xero_info["name"]
                    or db_info["type"] != xero_info["type"]):
                return True
            # Xero account is active but DB has it soft-deleted → needs restore
            if db_info["is_deleted"]:
                return True

    return False


def sync_chart_of_accounts_if_changed_background(
    entity_id, access_token, xero_org_id, user_id="", flask_app=None,
):
    """Fire-and-forget version — runs sync_chart_of_accounts_if_changed in a daemon thread."""
    _run_in_background(
        "sync_chart_of_accounts_if_changed_background",
        sync_chart_of_accounts_if_changed,
        entity_id, access_token, xero_org_id, user_id,
        entity_id=entity_id,
        flask_app=flask_app,
    )


def sync_contacts_if_changed_background(
    entity_id, access_token, xero_org_id, flask_app=None,
):
    """Fire-and-forget version — runs sync_contacts_if_changed in a daemon thread."""
    _run_in_background(
        "sync_contacts_if_changed_background",
        sync_contacts_if_changed,
        entity_id, access_token, xero_org_id,
        entity_id=entity_id,
        flask_app=flask_app,
    )


_EXPENSE_COA_TYPES = ("EXPENSE", "DIRECTCOSTS", "INVENTORY")
# Account types never shown in the Module 1 Chart of Accounts selector.
COA_EXCLUDED_TYPES = frozenset({
    "BANK", "EQUITY", "OTHERINCOME", "SALES", "REVENUE",
})
# Allowlist used by the Petty Cash CoA Settings UI: only these Xero account
# types are offered for the petty cash chart of accounts selector.
COA_INCLUDED_TYPES = frozenset({
    "DIRECTCOSTS", "EXPENSE", "OVERHEADS", "PREPAYMENT",
})
# Allowlist for the Module 2 Bill Chart of Accounts. Sync only writes these
# Xero account types into pettycashv3.entity_bill_account_xero.
BILL_COA_INCLUDED_TYPES = frozenset({
    "DIRECTCOSTS", "EXPENSE", "FIXED", "OVERHEADS", "PREPAYMENT",
})


def saveable_account_codes(entity_id, *, listed_only=True) -> set[str]:
    """The petty cash account codes a save can tick, for the at-least-one-code rule.

    ``account_info`` rows of the petty cash types that HAVE a code (the saves key on the
    code, so a row without one can never be ticked back on). ``listed_only`` keeps the rows
    Petty Cash Settings lists (those with an ``entity_account_xero`` row); onboarding's step
    5 runs before those rows exist, so it asks with ``listed_only=False``.
    """
    q = db.session.query(AccountInfo.xero_code).filter(
        AccountInfo.entity_id == entity_id,
        AccountInfo.type.in_(list(COA_INCLUDED_TYPES)),
    )
    if listed_only:
        q = q.join(EntityAccountXero, EntityAccountXero.account_id == AccountInfo.id)
    return {str(code).strip() for (code,) in q.all() if code and str(code).strip()}


def sync_entity_account_xero_active(entity_id, xero_org_id, selected_codes):
    """Save petty cash's code ticks onto ``entity_account_xero.is_active``.

    The tick lives ONLY here (``account_info.status`` is Xero's own "still active",
    never the tick - 2026-10-01). Rows of a CoA-included type whose code is in
    ``selected_codes`` are set ``is_active=true``, every other one ``false``. Rows
    for newly-eligible accounts are inserted on demand; nothing is deleted.
    Denormalized name/type/xero ids are refreshed so the table can answer
    questions without joining account_info. Commits.

    Used by the onboarding Step 5 save.
    """
    wanted = {str(c).strip() for c in (selected_codes or []) if c and str(c).strip()}
    eligible_accounts = AccountInfo.query.filter(
        AccountInfo.entity_id == entity_id,
        AccountInfo.type.in_(list(COA_INCLUDED_TYPES)),
    ).all()
    selected_ids = {
        acc.id for acc in eligible_accounts
        if acc.xero_code and acc.xero_code.strip() in wanted
    }

    existing_eax = (
        db.session.query(EntityAccountXero)
        .join(AccountInfo, EntityAccountXero.account_id == AccountInfo.id)
        .filter(AccountInfo.entity_id == entity_id)
        .all()
    )
    existing_by_account_id = {eax.account_id: eax for eax in existing_eax}

    for eax in existing_eax:
        eax.is_active = eax.account_id in selected_ids
        info = next(
            (a for a in eligible_accounts if a.id == eax.account_id), None
        )
        if info is not None:
            eax.name = info.name
            eax.type = info.type
            eax.xero_org_id = xero_org_id
            eax.xero_account_id = info.xero_account_id

    for acc in eligible_accounts:
        if acc.id in existing_by_account_id:
            continue
        db.session.add(
            EntityAccountXero(
                id=str(uuid4()),
                account_id=acc.id,
                name=acc.name,
                type=acc.type,
                xero_org_id=xero_org_id,
                xero_account_id=acc.xero_account_id,
                is_active=(acc.id in selected_ids),
            )
        )

    db.session.commit()
    logger.info(
        "sync_entity_account_xero_active: entity=%s active=%s total=%s",
        entity_id, len(selected_ids), len(eligible_accounts),
    )


def sync_expense_account_info_from_xero(entity_id, access_token, xero_org_id):
    """Upsert the chart of accounts rows in account_info from Xero.

    Syncs all account types except those in COA_EXCLUDED_TYPES (BANK, EQUITY,
    OTHERINCOME, SALES, REVENUE): every account Xero reports ACTIVE is upserted
    with ``status="ACTIVE"`` and its name/type/code refreshed.

    ``account_info.status`` means "still active in Xero" and nothing else. Petty
    cash's code ticks live on ``entity_account_xero.is_active``. Until 2026-10-01
    this function also wrote the ticks here: every row outside the excluded types
    went INACTIVE and only the ticked codes came back, so liability accounts (the
    Director mapping) and unticked codes (a Discrepancy account) vanished from the
    mapping dropdowns whenever the background re-sync could not run (disconnected,
    token expired) and the save was refused.

    The caller is responsible for calling db.session.commit() after this returns.
    """
    from blueprints.xero.services.integration import get_accounts_from_xero

    if not access_token or not xero_org_id:
        logger.warning(
            "sync_expense_account_info_from_xero skipped: missing token or tenant entity=%s",
            entity_id,
        )
        return

    try:
        xero_accounts = get_accounts_from_xero(
            access_token,
            xero_org_id,
            where='Status=="ACTIVE"',
            order="Code",
            token_validated=True,
        )
    except Exception as exc:
        logger.warning(
            "sync_expense_account_info_from_xero: Xero fetch failed entity=%s: %s",
            entity_id,
            exc,
        )
        return

    if not xero_accounts:
        logger.info(
            "sync_expense_account_info_from_xero: no accounts returned entity=%s",
            entity_id,
        )
        return

    # Build a dict of eligible accounts keyed by code.
    by_code = {}
    for xero_acc in xero_accounts:
        acc_type = xero_acc.get("Type")
        # Use exclusion list to match Module 2 behavior
        if acc_type in COA_EXCLUDED_TYPES:
            continue
        if xero_acc.get("Status", "ACTIVE") != "ACTIVE":
            continue
        raw_code = xero_acc.get("Code")
        if not raw_code or str(raw_code).strip() == "":
            continue
        code_str = str(raw_code).strip()
        by_code[code_str] = xero_acc

    for code_str, xero_acc in by_code.items():
        xero_account_id = xero_acc.get("AccountID", "")
        # Match on xero_account_id — the unique-constraint key. Matching on
        # xero_code here used to leave the AccountID free to collide: a row
        # created earlier (e.g. by _resolve_account_id for a mapping) could
        # already hold this AccountID, and the by-code UPDATE would then try to
        # stamp a duplicate xero_account_id → IntegrityError on revisit.
        existing_acc = None
        if xero_account_id:
            existing_acc = AccountInfo.query.filter(
                AccountInfo.entity_id == entity_id,
                AccountInfo.xero_account_id == xero_account_id,
            ).first()
        if existing_acc:
            existing_acc.status = "ACTIVE"
            existing_acc.type = xero_acc.get("Type", existing_acc.type)
            existing_acc.name = xero_acc.get("Name", existing_acc.name)
            existing_acc.xero_code = code_str
        else:
            # No row for this AccountID yet. _upsert_account_info goes through
            # ON CONFLICT (entity_id, xero_account_id), so if one nonetheless
            # exists it is updated in place rather than duplicated.
            _upsert_account_info({
                "id": str(uuid4()),
                "entity_id": entity_id,
                "type": xero_acc.get("Type", "EXPENSE"),
                "name": xero_acc.get("Name", ""),
                "xero_account_id": xero_account_id,
                "xero_code": code_str,
                "status": "ACTIVE",
            })

    logger.info(
        "sync_expense_account_info_from_xero: entity=%s refreshed=%s",
        entity_id,
        len(by_code),
    )


def _trunc(value, max_len):
    """Truncate a string value to max_len characters safely."""
    if not value:
        return value
    s = str(value)
    return s[:max_len] if len(s) > max_len else s


def sync_contacts_if_changed(entity_id, access_token, xero_org_id):
    """Compare Xero live contacts against xero_contact_sync; upsert if different.

    Insert/update only — this never removes a local contact. A contact absent
    from the Xero response is left untouched, because absence is not reliably a
    deletion: it also happens when a contact is archived in Xero, or when the
    fetch returns a partial result. Losing contact information is worse than
    showing a stale one, and rows here are referenced by
    ``entity_pettycash_settings`` (the onboarding step 6 contact mappings).

    Returns dict with keys: changed (bool), inserted (int), updated (int),
    aborted (bool). ``aborted`` is True when the Xero fetch failed and the
    reconcile was skipped, which callers must not treat as "no changes".
    """
    from blueprints.xero.services.integration import get_contacts_from_xero

    result = {
        "changed": False,
        "inserted": 0,
        "updated": 0,
        "aborted": False,
    }

    if not access_token or not xero_org_id:
        logger.warning(
            "sync_contacts_if_changed: skipped (no token/org) entity=%s",
            entity_id,
        )
        result["aborted"] = True
        return result

    try:
        xero_contacts = get_contacts_from_xero(
            access_token, xero_org_id, order="Name ASC", token_validated=True,
        )
    except Exception as exc:
        logger.warning(
            "sync_contacts_if_changed: Xero fetch failed entity=%s: %s",
            entity_id, exc,
        )
        result["aborted"] = True
        return result

    if xero_contacts is None:
        # Logged at ERROR, not WARNING: a persistently failing token makes this
        # abort every night, and a quiet no-op looks identical to a healthy
        # no-change run while the local contact list silently goes stale.
        logger.error(
            "sync_contacts_if_changed: Xero fetch failed (returned None) — "
            "aborting reconcile to protect local contacts entity=%s",
            entity_id,
        )
        result["aborted"] = True
        return result

    # Build Xero snapshot keyed by ContactID
    xero_by_id = {}
    for c in xero_contacts:
        cid = c.get("ContactID")
        if cid:
            xero_by_id[cid] = {
                "name": _trunc(c.get("Name", ""), 150),
            }

    # Build DB snapshot
    db_contacts = XeroContactSync.query.filter_by(entity_id=entity_id).all()
    db_by_xero_id = {
        c.xero_contact_id: c for c in db_contacts if c.xero_contact_id
    }

    # --- Check for differences ---
    has_diff = False

    # New contacts in Xero not in DB
    new_ids = set(xero_by_id.keys()) - set(db_by_xero_id.keys())
    if new_ids:
        has_diff = True

    # Contacts present locally but absent from Xero are deliberately ignored:
    # this sync never removes anything. Absence is ambiguous (archived in Xero,
    # a partial fetch, a Xero-side mistake) and acting on it is what previously
    # destroyed contact data.
    stale_ids = set(db_by_xero_id.keys()) - set(xero_by_id.keys())

    # Name changes on existing contacts
    changed_ids = []
    for cid, xero_info in xero_by_id.items():
        if cid in db_by_xero_id:
            db_contact = db_by_xero_id[cid]
            if (db_contact.name or "") != (xero_info["name"] or ""):
                changed_ids.append(cid)
                has_diff = True

    if not has_diff:
        logger.info(
            "sync_contacts_if_changed: no changes detected entity=%s "
            "(xero=%s db=%s)",
            entity_id, len(xero_by_id), len(db_by_xero_id),
        )
        return result

    result["changed"] = True
    logger.info(
        "sync_contacts_if_changed: changes detected entity=%s "
        "new=%s updated=%s kept_absent=%s",
        entity_id, len(new_ids), len(changed_ids), len(stale_ids),
    )

    # --- Apply sync ---
    # Insert new contacts
    for cid in new_ids:
        xero_info = xero_by_id[cid]
        db.session.add(XeroContactSync(
            id=str(uuid4()),
            entity_id=entity_id,
            xero_contact_id=cid,
            xero_org_id=str(xero_org_id),
            name=xero_info["name"],
            category=None,
        ))
        result["inserted"] += 1

    # Update changed names
    for cid in changed_ids:
        db_contact = db_by_xero_id[cid]
        db_contact.name = xero_by_id[cid]["name"]
        result["updated"] += 1

    # No removal step, by design — see the docstring.

    try:
        db.session.commit()
    except Exception:
        # Runs in a daemon thread — an uncommitted, unrolled-back transaction
        # would otherwise leak into whatever reuses this session.
        db.session.rollback()
        logger.exception(
            "sync_contacts_if_changed: commit failed entity=%s", entity_id,
        )
        raise

    logger.info(
        "sync_contacts_if_changed: synced entity=%s inserted=%s updated=%s",
        entity_id, result["inserted"], result["updated"],
    )

    return result


def sync_all_entities_contacts_and_accounts(flask_app=None):
    """Scheduled job: sync contacts and chart of accounts for ALL connected entities.

    Iterates every entity with a xero_org_id, resolves a valid Xero token,
    and runs sync_contacts_if_changed + sync_chart_of_accounts_if_changed.
    Designed to be called from a Flask CLI command at 3:30 AM Asia/Hong_Kong.
    """
    if flask_app is None:
        flask_app = current_app._get_current_object()

    with flask_app.app_context():
        entities = Entity.query.filter(
            Entity.xero_org_id.isnot(None),
            Entity.xero_org_id != "",
            Entity.status == "connected",
        ).all()

        logger.info(
            "sync_all_entities_contacts_and_accounts: found %s connected entities",
            len(entities),
        )

        for entity in entities:
            entity_id = str(entity.id)
            xero_org_id = str(entity.xero_org_id)

            try:
                from services.auth.token_service import (
                    ensure_valid_token, get_xero_token_user_for_entity)

                token_user = get_xero_token_user_for_entity(entity_id)
                if not token_user or not getattr(token_user, "access_token", None):
                    logger.warning(
                        "sync_all_entities: no token user for entity=%s, skipping",
                        entity_id,
                    )
                    continue

                if not ensure_valid_token(token_user):
                    logger.warning(
                        "sync_all_entities: token invalid for entity=%s, skipping",
                        entity_id,
                    )
                    continue

                access_token = token_user.access_token

                # Sync contacts
                try:
                    contact_result = sync_contacts_if_changed(
                        entity_id, access_token, xero_org_id,
                    )
                    logger.info(
                        "sync_all_entities: contacts entity=%s result=%s",
                        entity_id, contact_result,
                    )
                except Exception as exc:
                    db.session.rollback()
                    logger.error(
                        "sync_all_entities: contact sync failed entity=%s: %s",
                        entity_id, exc,
                    )

                # Sync chart of accounts (both modules)
                try:
                    coa_result = sync_chart_of_accounts_if_changed(
                        entity_id, access_token, xero_org_id,
                        user_id=str(token_user.id),
                    )
                    logger.info(
                        "sync_all_entities: chart of accounts entity=%s result=%s",
                        entity_id, coa_result,
                    )
                except Exception as exc:
                    db.session.rollback()
                    logger.error(
                        "sync_all_entities: chart sync failed entity=%s: %s",
                        entity_id, exc,
                    )

            except Exception as exc:
                logger.error(
                    "sync_all_entities: unexpected error entity=%s: %s",
                    entity_id, exc,
                )


def sync_all_accounts_and_contacts_background(
    entity_id, access_token, xero_org_id, _user_id, flask_app=None
):
    """Sync contacts and all accounts from Xero in a background thread.

    Each section (contacts, general accounts, expense account_info) runs in its own
    transaction so a failure in one does not block the others.
    """
    from blueprints.xero.services.integration import (get_accounts_from_xero,
                                                      get_contacts_from_xero)

    if flask_app is None:
        flask_app = current_app._get_current_object()

    with flask_app.app_context():
        logger.info(
            f"Starting background sync for entity {entity_id}, xero_org_id={xero_org_id}"
        )

        # --- Sync contacts ---
        try:
            contacts = get_contacts_from_xero(
                access_token, xero_org_id, order="Name ASC", token_validated=True
            )
            contacts = contacts or []
            logger.info(f"Fetched {len(contacts)} contacts from Xero for entity {entity_id}")

            existing_contact_ids = {
                c.xero_contact_id
                for c in XeroContactSync.query.filter_by(entity_id=entity_id).all()
            }
            new_contacts = 0
            for contact in contacts:
                contact_id = contact.get("ContactID")
                if not contact_id or contact_id in existing_contact_ids:
                    continue
                db.session.add(XeroContactSync(
                    id=str(uuid4()),
                    entity_id=entity_id,
                    xero_contact_id=contact_id,
                    xero_org_id=str(xero_org_id),
                    name=_trunc(contact.get("Name", ""), 150),
                    category=None,
                ))
                new_contacts += 1

            db.session.commit()
            logger.info(
                f"Contact sync entity {entity_id}: {new_contacts} new contacts saved"
            )
        except Exception as e:
            db.session.rollback()
            logger.error(f"Contact sync failed for entity {entity_id}: {str(e)}")

        # --- Sync ACTIVE accounts (upsert: update metadata for existing, insert new) ---
        try:
            accounts = get_accounts_from_xero(
                access_token, xero_org_id, where='Status=="ACTIVE"', token_validated=True
            )
            logger.info(f"Fetched {len(accounts)} accounts from Xero for entity {entity_id}")

            existing_by_id = {
                a.xero_account_id: a
                for a in AccountInfo.query.filter_by(entity_id=entity_id).all()
                if a.xero_account_id
            }
            new_accounts = 0
            updated_accounts = 0
            for account in accounts:
                account_id = account.get("AccountID")
                if not account_id:
                    continue
                if account_id in existing_by_id:
                    rec = existing_by_id[account_id]
                    rec.name = _trunc(account.get("Name", rec.name), 80)
                    rec.type = _trunc(account.get("Type", rec.type), 50)
                    rec.xero_code = _trunc(account.get("Code", rec.xero_code), 50)
                    rec.class_type = _trunc(account.get("Class", rec.class_type), 50)
                    rec.bank_account_number = _trunc(account.get("BankAccountNumber", rec.bank_account_number), 50)
                    rec.bank_account_type = _trunc(account.get("BankAccountType", rec.bank_account_type), 50)
                    rec.description = _trunc(account.get("Description", rec.description), 255)
                    rec.status = _trunc(account.get("Status", "ACTIVE"), 50)
                    updated_accounts += 1
                else:
                    _upsert_account_info({
                        "id": str(uuid4()),
                        "entity_id": entity_id,
                        "xero_account_id": account_id,
                        "name": _trunc(account.get("Name", ""), 80),
                        "type": _trunc(account.get("Type", ""), 50),
                        "xero_code": _trunc(account.get("Code", ""), 50),
                        "status": _trunc(account.get("Status", "ACTIVE"), 50),
                        "class_type": _trunc(account.get("Class", ""), 50),
                        "bank_account_number": _trunc(account.get("BankAccountNumber", ""), 50),
                        "bank_account_type": _trunc(account.get("BankAccountType", ""), 50),
                        "description": _trunc(account.get("Description", ""), 255),
                    })
                    new_accounts += 1

            db.session.commit()
            logger.info(
                f"Account sync entity {entity_id}: {new_accounts} inserted, {updated_accounts} updated"
            )
        except Exception as e:
            db.session.rollback()
            logger.error(f"Account sync failed for entity {entity_id}: {str(e)}")

        # --- Sync expense/direct-costs into account_info (own transaction) ---
        try:
            sync_expense_account_info_from_xero(entity_id, access_token, xero_org_id)
            db.session.commit()
            logger.info(
                "Background sync: expense account_info synced for entity %s", entity_id
            )
        except Exception as exc:
            db.session.rollback()
            logger.error(
                "Background sync: expense account_info sync failed for entity %s: %s",
                entity_id, exc,
            )

        # Mirror account_info into the petty cash + bill CoA tables so the
        # Expense dropdown (entity_account_xero) and Bill modal dropdown
        # (entity_bill_account_xero) are populated on connect/reconnect — not
        # only when the user later opens the settings page.
        try:
            sync_xero_coa_pettycash(entity_id, xero_org_id)
        except Exception as exc:
            db.session.rollback()
            logger.error(
                "Background sync: entity_account_xero sync failed entity=%s: %s",
                entity_id, exc,
            )
        try:
            sync_xero_coa_bill(entity_id, user_id=str(_user_id) if _user_id else "")
        except Exception as exc:
            db.session.rollback()
            logger.error(
                "Background sync: entity_bill_account_xero sync failed entity=%s: %s",
                entity_id, exc,
            )

        logger.info(f"Background sync completed for entity {entity_id}")

def debug_xero_settings(entity_id):
    """Debug route to check Xero settings status"""
    try:
        entity = Entity.query.get_or_404(entity_id)
        settings_count = (
            db.session.query(EntityAccountXero)
            .join(AccountInfo, EntityAccountXero.account_id == AccountInfo.id)
            .filter(AccountInfo.entity_id == entity_id)
            .count()
        )
        contact_count = (
            db.session.query(XeroContactSync).filter_by(
                entity_id=entity_id).count())
        is_complete = check_entity_xero_settings_complete(entity_id)

        # Get detailed account types
        account_types = (
            db.session.query(EntityAccountXero.type)
            .join(AccountInfo, EntityAccountXero.account_id == AccountInfo.id)
            .filter(AccountInfo.entity_id == entity_id)
            .all()
        )
        contact_categories = (
            db.session.query(XeroContactSync.category)
            .filter_by(entity_id=entity_id)
            .all()
        )

        return jsonify(
            {
                "entity_id": entity_id,
                "entity_name": entity.name,
                "xero_org_id": entity.xero_org_id,
                "settings_count": settings_count,
                "contact_count": contact_count,
                "is_complete": is_complete,
                "required_accounts": 6,
                "required_contacts": 3,
                "account_types": [t[0] for t in account_types],
                "contact_categories": [c[0] for c in contact_categories],
            }
        )
    except Exception:
        logger.exception(f"Entity settings debug failed for entity {entity_id}")
        return (
            jsonify({"error": "I couldn't save those settings. Mind trying again?"}),
            500,
        )


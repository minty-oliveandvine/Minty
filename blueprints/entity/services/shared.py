# Entity shared helpers: check_user_has_entities,
# get_settings_redirect_url, create_default_entity_settings,
# display_deposit_balance, get_main_bank_account.
from datetime import datetime

from flask import url_for
from loguru import logger

from blueprints.xero.services.settings import \
    check_entity_xero_settings_complete
from models.db import (AccountInfo, EntityPettycashSettings,
                       EntitySaleSetting, SaleInfo, UserEntity, db, tz)


def check_user_has_entities(user_id):
    """Return True if the user has access to at least one entity.

    Superusers always return True: they have global (read-only when no
    user_entity row exists) access, so this entity-creation gate must not
    redirect them away from views they're allowed to see.
    """
    from models.db import User
    from services.permission_policy import is_superuser

    user = User.query.get(user_id)
    if user and is_superuser(user):
        return True

    count = UserEntity.query.filter(UserEntity.user_id == user_id).count()
    return count > 0


def create_entity_for_user(user_id, entity_name, country_code, currency_id, *,
                           status="onboarding"):
    """Create an entity owned (admin) by ``user_id`` plus its default settings.

    ``status`` is the ``entity_status`` the row starts in: ``onboarding`` (the wizard,
    the default and the database's) or ``disconnected`` for the legacy create form, whose
    company is live at once and has no Xero organisation yet.

    ``country_code`` is the ISO alpha-2 country_info PK and ``currency_id``
    a currency_info uuid (the entities columns are FKs to those registries —
    callers resolve names to them first, e.g. via ``_resolve_country_code``).

    Shared by the entity-create form route and the onboarding API endpoint so
    both go through identical creation logic. Returns ``(entity, error)`` where
    ``error`` is None on success, or a user-facing message on failure.
    """
    import uuid as _uuid

    from models.db import Entity

    name = (entity_name or "").strip()
    if len(name) < 1:
        return None, "Entity name is required."

    # Idempotency for onboarding resume: a stale or racing frontend (cold
    # resume with no localStorage) can re-POST basic information for an entity
    # this user already created and left mid-onboarding. Return that existing
    # row instead of creating a duplicate, so the wizard binds it and continues.
    existing = (
        Entity.query.join(UserEntity, UserEntity.entity_id == Entity.id)
        .filter(
            UserEntity.user_id == user_id,
            Entity.name == name,
            Entity.status == "onboarding",
        )
        .first()
    )
    if existing:
        return existing, None

    if Entity.query.filter_by(name=name).first():
        return None, "Entity name already exist"

    try:
        entity = Entity(
            id=str(_uuid.uuid4()),
            name=name,
            status=status,
            country_code=country_code or None,
            currency_id=currency_id or None,
        )
        db.session.add(entity)
        db.session.commit()
        # The creator becomes the entity admin by policy.
        db.session.add(UserEntity(user_id=user_id, entity_id=entity.id, role="admin"))
        create_default_entity_settings(entity.id)
        db.session.commit()

        # Seed module entitlements so entity_function_map is always populated
        # at creation (Petty Cash enabled, Bill disabled). Onboarding Step 2
        # may later override this; the write is idempotent. Lazy import keeps
        # blueprint load order independent of the modules service.
        from blueprints.entity.services.modules import apply_default_modules

        _data, _status = apply_default_modules(entity.id, user_id=str(user_id))
        if _status != 200:
            logger.error(
                f"Default modules not seeded for entity {entity.id}: {_data}"
            )

        return entity, None
    except Exception as e:  # noqa: BLE001 - surface as a clean message
        db.session.rollback()
        logger.error(f"Error creating entity: {str(e)}")
        return None, "An error occurred while creating the entity. Please try again."


def get_settings_redirect_url(entity_id):
    """Determine the correct settings redirect URL based on setup status."""
    try:
        if not check_entity_xero_settings_complete(entity_id):
            return url_for("entity_settings", entity_id=entity_id)
        return url_for("entity_settings_users", org_id=entity_id)
    except Exception as e:
        logger.error(f"Error determining settings redirect: {str(e)}")
        return url_for("entity_settings_users", org_id=entity_id)


def create_default_entity_settings(entity_id):
    """Create default payment methods and delivery sales types for a new entity."""
    try:
        # Cash leads the list — it is the most-used method. Its type is 'Cash',
        # not 'Electronic': get_cash_sales_from_detail keys on that to find the
        # figure that feeds the closing balance.
        cash_methods = [
            {
                "sale_name": "Cash",
                "value_name": "cash_sales",
                "type": "Cash",
                "display_order": 0,
            },
        ]
        electronic_methods = [
            {
                "sale_name": "Visa",
                "value_name": "visa_sales",
                "type": "Electronic",
                "display_order": 1,
            },
            {
                "sale_name": "Alipay",
                "value_name": "alipay_sales",
                "type": "Electronic",
                "display_order": 2,
            },
            {
                "sale_name": "WeChat Pay",
                "value_name": "wechat_sales",
                "type": "Electronic",
                "display_order": 3,
            },
            {
                "sale_name": "Mastercard",
                "value_name": "master_sales",
                "type": "Electronic",
                "display_order": 4,
            },
            {
                "sale_name": "UnionPay",
                "value_name": "unionpay_sales",
                "type": "Electronic",
                "display_order": 5,
            },
            {
                "sale_name": "Amex",
                "value_name": "amex_sales",
                "type": "Electronic",
                "display_order": 6,
            },
            {
                "sale_name": "Octopus",
                "value_name": "octopus_sales",
                "type": "Electronic",
                "display_order": 7,
            },
        ]
        delivery_methods = [
            {
                "sale_name": "Food Panda",
                "value_name": "foodpanda_sales",
                "type": "Delivery",
                "display_order": 1,
            },
            {
                "sale_name": "Keeta",
                "value_name": "keeta_sales",
                "type": "Delivery",
                "display_order": 2,
            },
            {
                "sale_name": "OpenRice",
                "value_name": "openrice_sales",
                "type": "Delivery",
                "display_order": 3,
            },
        ]
        # Seed from the SaleInfo catalog when it is populated, so a method
        # added to the catalog reaches new entities without touching this list.
        # The hardcoded lists above remain the fallback for a database where
        # the catalog has not been seeded yet (and as the source of the
        # per-method display_order).
        catalog = (
            SaleInfo.query.filter(
                SaleInfo.entity_id.is_(None),
                SaleInfo.is_active.is_(True),
            )
            .order_by(SaleInfo.type.asc(), SaleInfo.display_order.asc())
            .all()
        )

        if catalog:
            for method in catalog:
                db.session.add(
                    EntitySaleSetting(
                        entity_id=entity_id,
                        sale_name=method.name,
                        # value_name stays the legacy key until every read has
                        # moved to sale_info_id.
                        value_name=method.legacy_column,
                        type=method.type,
                        sale_info_id=method.id,
                        display_order=method.display_order,
                        enabled=True,
                        create_date=datetime.now(tz),
                        updated_at=datetime.now(tz),
                    )
                )
        else:
            for method in cash_methods + electronic_methods + delivery_methods:
                db.session.add(
                    EntitySaleSetting(
                        entity_id=entity_id,
                        sale_name=method["sale_name"],
                        value_name=method["value_name"],
                        type=method["type"],
                        display_order=method["display_order"],
                        enabled=True,
                        create_date=datetime.now(tz),
                        updated_at=datetime.now(tz),
                    )
                )
        logger.info(f"Created default settings for entity {entity_id}")
    except Exception as e:
        logger.error(
            f"Error creating default settings for entity {entity_id}: {str(e)}"
        )
        raise


def get_main_bank_account(entity_id):
    settings_row = EntityPettycashSettings.query.filter_by(
        entity_id=entity_id
    ).first()
    if settings_row is None or not settings_row.pettycash_account_id:
        return None
    return AccountInfo.query.get(settings_row.pettycash_account_id)

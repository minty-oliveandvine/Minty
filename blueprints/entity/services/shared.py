# Entity shared helpers: check_user_has_entities,
# get_settings_redirect_url, create_default_entity_settings,
# display_deposit_balance, get_main_bank_account.

from flask import url_for
from loguru import logger

from blueprints.xero.services.settings import \
    check_entity_xero_settings_complete
from blueprints.shared.enums import SaleType
from models.db import (AccountInfo, EntityPettycashSettings,
                       EntitySaleSetting, SaleInfo, UserEntity, db)


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
    """Link a new company to the default sales methods.

    The catalogue (``sale_info``) is global; this only decides which of its rows a brand-new
    company starts with - Cash, the common cards and wallets, the three delivery platforms -
    and in what order. A default that is not in the catalogue yet is added to it (a fresh
    database), everything else is found by name. Cash is ``type=other`` with
    ``value_name=cash_sales``: the report's cash section keys on that value_name.
    """
    defaults = [
        # (name, value_name, type, order)
        ("Cash", "cash_sales", SaleType.OTHER, 0),
        ("Visa", "visa_sales", SaleType.ELECTRONIC, 1),
        ("Alipay", "alipay_sales", SaleType.ELECTRONIC, 2),
        ("WeChat Pay", "wechat_sales", SaleType.ELECTRONIC, 3),
        ("Mastercard", "master_sales", SaleType.ELECTRONIC, 4),
        ("UnionPay", "unionpay_sales", SaleType.ELECTRONIC, 5),
        ("Amex", "amex_sales", SaleType.ELECTRONIC, 6),
        ("Octopus", "octopus_sales", SaleType.ELECTRONIC, 7),
        ("Food Panda", "foodpanda_sales", SaleType.DELIVERY, 1),
        ("Keeta", "keeta_sales", SaleType.DELIVERY, 2),
        ("OpenRice", "openrice_sales", SaleType.DELIVERY, 3),
    ]
    try:
        existing = {
            link.sale_id for link in EntitySaleSetting.query.filter_by(entity_id=entity_id).all()
        }
        for name, value_name, sale_type, order in defaults:
            row = SaleInfo.by_value_name(value_name) or SaleInfo.ensure(
                name, sale_type, value_name=value_name, display_order=order
            )
            if row.id in existing:
                continue
            db.session.add(
                EntitySaleSetting(entity_id=entity_id, sale_id=row.id, is_active=True, display_order=order)
            )
            existing.add(row.id)
        logger.info(f"Created default settings for entity {entity_id}")
    except Exception as e:
        logger.error(f"Error creating default settings for entity {entity_id}: {str(e)}")
        raise


def get_main_bank_account(entity_id):
    settings_row = EntityPettycashSettings.query.filter_by(
        entity_id=entity_id
    ).first()
    if settings_row is None or not settings_row.pettycash_account_id:
        return None
    return AccountInfo.query.get(settings_row.pettycash_account_id)

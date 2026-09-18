"""Payment method service helpers for entity payment method APIs.

Since C3 (docs/modernisation/modernisation_plan.md) a company's methods are links (``EntitySaleSetting``:
entity, catalogue row, on/off, order) into one global catalogue (``SaleInfo``: name, type,
form-field name). Adding a method a company invents adds a catalogue row for everyone; the
company's own state is only the link. Types are the ``sale_type`` enum -
``electronic`` / ``delivery`` / ``other``; the capitalised words older clients send are
accepted on input (``SaleType.normalize``) and the enum's words are what comes back.
"""

from __future__ import annotations

from loguru import logger

from blueprints.shared.enums import SaleType
from models.db import EntitySaleSetting, SaleInfo, UserEntity, db
from services.permission_policy import Permission, has_permission_by_user_id

# What the settings page and the wizard may add or list. Cash is a method (it is on every
# company's list) but is managed on the report's own cash section, not here.
LISTABLE_TYPES = (SaleType.ELECTRONIC, SaleType.DELIVERY)


def _build_method_payload(method: EntitySaleSetting):
    info = method.sale_info
    return {
        "id": method.sale_id,
        "entity_id": method.entity_id,
        "name": info.sale_name if info else None,
        "type": info.type.value if info and info.type is not None else None,
        "value_name": info.value_name if info else None,
        "enabled": method.is_active,
        "display_order": method.display_order,
    }


def _ensure_access(user_id, entity_id):
    return UserEntity.query.filter_by(user_id=user_id, entity_id=entity_id).first()


def _links(entity_id, *, enabled_only=False, types=None):
    """The company's links joined to their catalogue rows, in list order."""
    q = (
        EntitySaleSetting.query.join(SaleInfo, SaleInfo.id == EntitySaleSetting.sale_id)
        .filter(EntitySaleSetting.entity_id == entity_id)
    )
    if enabled_only:
        q = q.filter(EntitySaleSetting.is_active.is_(True))
    if types is not None:
        q = q.filter(SaleInfo.type.in_(list(types)))
    return q.order_by(EntitySaleSetting.display_order.asc(), SaleInfo.sale_name.asc()).all()


def _link_for(entity_id, sale_id):
    return EntitySaleSetting.query.filter_by(entity_id=entity_id, sale_id=sale_id).first()


def _next_order(entity_id) -> int:
    current = (
        db.session.query(db.func.max(EntitySaleSetting.display_order))
        .filter_by(entity_id=entity_id)
        .scalar()
    )
    return int(current or 0) + 1


def list_payment_methods(user_id, entity_id):
    """List the company's enabled methods, ordered as the Settings page shows them."""
    if not has_permission_by_user_id(user_id, Permission.SALES_METHOD_VIEW, entity_id):
        return {"error": "Access denied"}, 403

    methods = _links(entity_id, enabled_only=True)
    logger.info(f"list_payment_methods: entity={entity_id}, found {len(methods)} payment methods")
    return {"payment_methods": [_build_method_payload(m) for m in methods]}, 200


def add_payment_method(user_id, entity_id, data):
    """Add a method to the company, or switch an existing link back on.

    The catalogue row is found by the caller's ``sale_info_id``, else by ``value_name``, else
    by ``name``; a name nobody has used before becomes a new catalogue row.
    """
    if not has_permission_by_user_id(user_id, Permission.SALES_METHOD_CREATE, entity_id):
        return {"error": "Access denied"}, 403
    if not data:
        return {"error": "No data provided"}, 400

    for field in ("name", "type"):
        if field not in data:
            return {"error": f"Missing required field: {field}"}, 400

    method_type = SaleType.normalize(data.get("type"))
    if method_type is None:
        return {"error": "Invalid type. Must be electronic, delivery or other"}, 400

    name = str(data.get("name") or "").strip()
    logger.info(
        f"add_payment_method: entity={entity_id}, value_name={data.get('value_name')}, "
        f"name={name}, type={method_type.value}"
    )

    catalog_row = None
    if data.get("sale_info_id"):
        catalog_row = SaleInfo.query.filter_by(id=data["sale_info_id"]).first()
    if catalog_row is None and data.get("value_name"):
        catalog_row = SaleInfo.by_value_name(data["value_name"])
    if catalog_row is None:
        catalog_row = SaleInfo.by_name(name)
    if catalog_row is None:
        catalog_row = SaleInfo.ensure(name, method_type, value_name=data.get("value_name") or None)

    link = _link_for(entity_id, catalog_row.id)
    if link is not None:
        was_enabled = link.is_active
        link.is_active = bool(data.get("enabled", True))
        if data.get("display_order") is not None:
            link.display_order = data["display_order"]
        db.session.commit()
        message = "Payment method updated successfully" if was_enabled else "Payment method re-enabled successfully"
        logger.info(f"add_payment_method: existing link for sale_id={link.sale_id} ({message})")
        return {"message": message, "payment_method": _build_method_payload(link)}, 200

    link = EntitySaleSetting(
        entity_id=entity_id,
        sale_id=catalog_row.id,
        is_active=bool(data.get("enabled", True)),
        display_order=data.get("display_order", _next_order(entity_id)),
    )
    db.session.add(link)
    db.session.commit()
    logger.info(f"add_payment_method: linked sale_id={link.sale_id} to entity={entity_id}")
    return {"message": "Payment method added successfully", "payment_method": _build_method_payload(link)}, 201


def update_payment_method(user_id, entity_id, method_id, data):
    """Change a method's on/off or order for this company.

    ``name`` and ``type`` describe the catalogue row every company shares; a rename here
    renames it for everyone, so only a name nobody else uses may be edited in place - otherwise
    the request is refused rather than silently changing other companies' lists.
    """
    if not has_permission_by_user_id(user_id, Permission.SALES_METHOD_UPDATE, entity_id):
        return {"error": "Access denied"}, 403
    if not data:
        return {"error": "No data provided"}, 400

    link = _link_for(entity_id, method_id)
    if not link:
        return {"error": "Payment method not found"}, 404
    info = link.sale_info

    if "type" in data and SaleType.normalize(data["type"]) is None:
        return {"error": "Invalid type. Must be electronic, delivery or other"}, 400

    touches_catalogue = ("name" in data and (data["name"] or "").strip() != info.sale_name) or (
        "type" in data and SaleType.normalize(data["type"]) != info.type
    )
    if touches_catalogue:
        others = EntitySaleSetting.query.filter(
            EntitySaleSetting.sale_id == info.id, EntitySaleSetting.entity_id != entity_id
        ).count()
        if others:
            return {
                "error": "This method is shared with other companies; add a new method instead of renaming it."
            }, 409
        if "name" in data:
            clash = SaleInfo.by_name(data["name"])
            if clash is not None and clash.id != info.id:
                return {"error": "A method with that name already exists."}, 409
            info.sale_name = (data["name"] or "").strip()
        if "type" in data:
            info.type = SaleType.normalize(data["type"])

    if "enabled" in data:
        link.is_active = bool(data["enabled"])
    if "display_order" in data:
        link.display_order = data["display_order"]

    db.session.commit()
    return {"message": "Payment method updated successfully", "payment_method": _build_method_payload(link)}, 200


def delete_payment_method(user_id, entity_id, method_id):
    """Switch a method off for this company (the link stays; old reports keep their rows)."""
    if not has_permission_by_user_id(user_id, Permission.SALES_METHOD_DELETE, entity_id):
        return {"error": "Access denied"}, 403

    link = _link_for(entity_id, method_id)
    if not link:
        logger.warning(f"delete_payment_method: Method not found (method_id={method_id}, entity={entity_id})")
        return {"error": "Payment method not found"}, 404

    logger.info(f"delete_payment_method: Disabling method (sale_id={method_id}, value_name={link.value_name})")
    link.is_active = False
    db.session.commit()
    return {"message": "Payment method disabled successfully"}, 200


def list_sales_methods_grouped(user_id, entity_id):
    """Enabled electronic / delivery method names grouped by type, in list order.

    Used by the onboarding Sales Setting step (Step 4), which works with plain
    display-name lists rather than the full method payloads the Settings page uses.
    """
    if not has_permission_by_user_id(user_id, Permission.SALES_METHOD_VIEW, entity_id):
        return {"error": "Access denied"}, 403

    methods = _links(entity_id, enabled_only=True, types=LISTABLE_TYPES)
    return {
        "electronic": [m.sale_name for m in methods if m.type == SaleType.ELECTRONIC],
        "delivery": [m.sale_name for m in methods if m.type == SaleType.DELIVERY],
    }, 200


def replace_sales_methods(user_id, entity_id, electronic, delivery):
    """Reconcile the company's electronic / delivery methods to the given name lists.

    Names in the lists are linked (catalogue row found by name, created if nobody has it),
    switched on and ordered 1..n within their type; previously-enabled methods absent from
    the lists are switched off (never deleted - old reports reference them).
    """
    if not has_permission_by_user_id(user_id, Permission.SALES_METHOD_CREATE, entity_id):
        return {"error": "Access denied"}, 403
    if not isinstance(electronic, list) or not isinstance(delivery, list):
        return {"error": "electronic and delivery must be arrays"}, 400

    def _clean(names):
        out, seen = [], set()
        for n in names:
            s = str(n or "").strip()
            key = s.lower()
            if s and key not in seen:
                seen.add(key)
                out.append(s)
        return out

    desired = {SaleType.ELECTRONIC: _clean(electronic), SaleType.DELIVERY: _clean(delivery)}

    existing = _links(entity_id, types=LISTABLE_TYPES)
    by_sale_id = {m.sale_id: m for m in existing}

    wanted_ids = set()
    for mtype, names in desired.items():
        for i, name in enumerate(names):
            row = SaleInfo.ensure(name, mtype)
            wanted_ids.add(row.id)
            link = by_sale_id.get(row.id)
            if link is None:
                link = EntitySaleSetting(entity_id=entity_id, sale_id=row.id)
                db.session.add(link)
                by_sale_id[row.id] = link
            link.is_active = True
            link.display_order = i + 1

    for sale_id, link in by_sale_id.items():
        if sale_id not in wanted_ids and link.is_active:
            link.is_active = False

    db.session.commit()
    logger.info(
        "replace_sales_methods: entity=%s electronic=%s delivery=%s",
        entity_id, len(desired[SaleType.ELECTRONIC]), len(desired[SaleType.DELIVERY]),
    )
    return {"electronic": desired[SaleType.ELECTRONIC], "delivery": desired[SaleType.DELIVERY]}, 200


def reorder_payment_methods(user_id, entity_id, method_ids):
    if not has_permission_by_user_id(user_id, Permission.SALES_METHOD_REORDER, entity_id):
        return {"error": "Access denied"}, 403
    if not method_ids or not isinstance(method_ids, list):
        return {"error": "method_ids array is required"}, 400

    for index, method_id in enumerate(method_ids):
        link = _link_for(entity_id, method_id)
        if link:
            link.display_order = index + 1

    db.session.commit()
    return {"message": "Payment methods reordered successfully"}, 200


def list_available_methods(user_id, entity_id):
    """Catalogue methods this company has NOT switched on, grouped by type.

    Backs the "add a payment method" dropdowns in Entity Settings, so a user picks "VISA"
    rather than typing "Viza" and minting a second catalogue row. Offered rows are the
    enabled catalogue entries minus whatever the company already has on; a method the
    company switched off is offered again, and re-adding it re-enables the same link.

    Each item carries the catalogue id and name; ``id`` is what the caller passes back as
    ``sale_info_id`` so the new link points at the right row.
    """
    if not has_permission_by_user_id(user_id, Permission.SALES_METHOD_VIEW, entity_id):
        return {"error": "Access denied"}, 403

    taken = {m.sale_id for m in _links(entity_id, enabled_only=True)}

    catalog = (
        SaleInfo.query.filter(SaleInfo.enabled.is_(True), SaleInfo.type.in_(list(LISTABLE_TYPES)))
        .order_by(SaleInfo.display_order.asc().nulls_last(), SaleInfo.sale_name.asc())
        .all()
    )

    grouped = {"electronic": [], "delivery": []}
    for row in catalog:
        if row.id in taken:
            continue
        grouped[row.type.value].append(
            {"id": row.id, "name": row.sale_name, "type": row.type.value, "value_name": row.value_name}
        )

    logger.info(
        "list_available_methods: entity=%s electronic=%s delivery=%s",
        entity_id, len(grouped["electronic"]), len(grouped["delivery"]),
    )
    return grouped, 200

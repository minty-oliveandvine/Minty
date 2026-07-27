"""Payment method service helpers for entity payment method APIs."""

from __future__ import annotations

from datetime import datetime

from loguru import logger

from models.db import SaleInfo, SalesMethod, UserEntity, db
from services.permission_policy import Permission, has_permission_by_user_id


def _build_method_payload(method):
    return {
        "id": method.sale_id,
        "entity_id": method.entity_id,
        "name": method.sale_name,
        "type": method.type,
        "enabled": method.enabled,
        "display_order": method.display_order,
        "created_at": method.create_date.isoformat() if method.create_date else None,
        "updated_at": method.updated_at.isoformat() if method.updated_at else None,
    }


def _ensure_access(user_id, entity_id):
    return UserEntity.query.filter_by(user_id=user_id, entity_id=entity_id).first()


def list_payment_methods(user_id, entity_id):
    """
    List all enabled payment methods for an entity.
    Returns unique methods (no duplicates) ordered by display_order, matching Settings page.
    """
    if not has_permission_by_user_id(user_id, Permission.SALES_METHOD_VIEW, entity_id):
        return {"error": "Access denied"}, 403

    # Get unique payment methods by value_name (prevents duplicates)
    # Keep the most recently created one if duplicates exist
    payment_methods_subquery = (
        db.session.query(
            SaleInfo.value_name,
            db.func.max(SaleInfo.sale_id).label('max_sale_id')
        )
        .filter(
            SaleInfo.entity_id == entity_id,
            SaleInfo.value_name != "deliveroo_sales",
            SaleInfo.enabled == True
        )
        .group_by(SaleInfo.value_name)
        .subquery()
    )
    
    payment_methods = (
        db.session.query(SaleInfo)
        .join(
            payment_methods_subquery,
            SaleInfo.sale_id == payment_methods_subquery.c.max_sale_id
        )
        .order_by(SaleInfo.display_order.asc(), SaleInfo.create_date.asc())
        .all()
    )

    logger.info(
        f"list_payment_methods: entity={entity_id}, "
        f"found {len(payment_methods)} unique payment methods"
    )

    methods_data = [_build_method_payload(method) for method in payment_methods]
    return {"payment_methods": methods_data}, 200


def add_payment_method(user_id, entity_id, data):
    """
    Add a new payment method or re-enable an existing one.
    Prevents duplicates by checking for existing enabled methods.
    """
    if not has_permission_by_user_id(user_id, Permission.SALES_METHOD_CREATE, entity_id):
        return {"error": "Access denied"}, 403
    if not data:
        return {"error": "No data provided"}, 400

    required_fields = ["name", "type", "value_name"]
    for field in required_fields:
        if field not in data:
            return {"error": f"Missing required field: {field}"}, 400

    method_type = data.get("type")
    if method_type not in ["Cash", "Electronic", "Delivery"]:
        return {"error": "Invalid type. Must be Cash, Electronic, or Delivery"}, 400

    logger.info(
        f"add_payment_method: entity={entity_id}, "
        f"value_name={data['value_name']}, name={data['name']}, type={method_type}"
    )

    # Check if there's already an enabled payment method with same value_name
    existing_enabled = SaleInfo.query.filter_by(
        entity_id=entity_id,
        value_name=data["value_name"],
        enabled=True
    ).first()
    
    if existing_enabled:
        # Update existing instead of creating duplicate
        logger.info(
            f"add_payment_method: Found existing enabled method, updating "
            f"(sale_id={existing_enabled.sale_id})"
        )
        existing_enabled.sale_name = data["name"]
        existing_enabled.type = method_type
        existing_enabled.display_order = data.get("display_order", existing_enabled.display_order)
        existing_enabled.updated_at = datetime.now()
        db.session.commit()
        
        return {
            "message": "Payment method updated successfully",
            "payment_method": _build_method_payload(existing_enabled),
        }, 200

    # Check for disabled record to re-enable
    existing_disabled = SaleInfo.query.filter_by(
        entity_id=entity_id,
        value_name=data["value_name"],
        enabled=False
    ).first()

    if existing_disabled:
        logger.info(
            f"add_payment_method: Found existing disabled method, re-enabling "
            f"(sale_id={existing_disabled.sale_id})"
        )
        existing_disabled.enabled = True
        existing_disabled.sale_name = data["name"]
        existing_disabled.type = method_type
        existing_disabled.display_order = data.get("display_order", existing_disabled.display_order)
        existing_disabled.updated_at = datetime.now()
        db.session.commit()

        return {
            "message": "Payment method re-enabled successfully",
            "payment_method": _build_method_payload(existing_disabled),
        }, 200

    # Create new method only if no existing record found
    current_max_order = (
        db.session.query(db.func.max(SaleInfo.display_order))
        .filter_by(entity_id=entity_id)
        .scalar()
    )

    max_order = int(current_max_order or 0)
    
    # Resolve the catalog row: by the caller's explicit sales_method_id, else
    # by the legacy value_name, else mint a per-entity row for a user-invented
    # method. Without this the new row would carry a NULL catalog link.
    catalog_row = None
    if data.get("sales_method_id"):
        catalog_row = SalesMethod.query.filter_by(id=data["sales_method_id"]).first()
    if catalog_row is None:
        catalog_row = SalesMethod.resolve(
            entity_id, legacy_column=data["value_name"]
        )
    if catalog_row is None:
        catalog_row = SalesMethod.ensure_custom(
            entity_id, data["name"], method_type
        )

    new_method = SaleInfo(
        entity_id=entity_id,
        sale_name=data["name"],
        value_name=data["value_name"],
        type=method_type,
        sale_info_id=catalog_row.id if catalog_row else None,
        enabled=data.get("enabled", True),
        display_order=data.get("display_order", max_order + 1),
        create_date=datetime.now(),
        updated_at=datetime.now(),
    )

    db.session.add(new_method)
    db.session.commit()

    logger.info(
        f"add_payment_method: Created new method (sale_id={new_method.sale_id})"
    )

    return {
        "message": "Payment method added successfully",
        "payment_method": _build_method_payload(new_method),
    }, 201


def update_payment_method(user_id, entity_id, method_id, data):
    if not has_permission_by_user_id(user_id, Permission.SALES_METHOD_UPDATE, entity_id):
        return {"error": "Access denied"}, 403
    if not data:
        return {"error": "No data provided"}, 400

    payment_method = SaleInfo.query.filter_by(
        sale_id=method_id, entity_id=entity_id
    ).first()
    if not payment_method:
        return {"error": "Payment method not found"}, 404

    if "name" in data:
        payment_method.sale_name = data["name"]
    if "type" in data:
        if data["type"] not in ["Cash", "Electronic", "Delivery"]:
            return {
                "error": "Invalid type. Must be Cash, Electronic, or Delivery"
            }, 400
        payment_method.type = data["type"]
    if "enabled" in data:
        payment_method.enabled = data["enabled"]
    if "display_order" in data:
        payment_method.display_order = data["display_order"]

    payment_method.updated_at = datetime.now()
    db.session.commit()

    return {
        "message": "Payment method updated successfully",
        "payment_method": _build_method_payload(payment_method),
    }, 200


def delete_payment_method(user_id, entity_id, method_id):
    """Disable a payment method (soft delete)."""
    if not has_permission_by_user_id(user_id, Permission.SALES_METHOD_DELETE, entity_id):
        return {"error": "Access denied"}, 403

    payment_method = SaleInfo.query.filter_by(
        sale_id=method_id, entity_id=entity_id
    ).first()
    if not payment_method:
        logger.warning(
            f"delete_payment_method: Method not found "
            f"(method_id={method_id}, entity={entity_id})"
        )
        return {"error": "Payment method not found"}, 404

    logger.info(
        f"delete_payment_method: Disabling method "
        f"(sale_id={method_id}, value_name={payment_method.value_name})"
    )
    
    payment_method.enabled = False
    payment_method.updated_at = datetime.now()
    db.session.commit()

    return {"message": "Payment method disabled successfully"}, 200


def list_sales_methods_grouped(user_id, entity_id):
    """Return enabled Electronic/Delivery method names grouped by type.

    Used by the onboarding Sales Setting step (Step 4), which works with plain
    display-name lists rather than the full method payloads the Settings page uses.
    """
    if not has_permission_by_user_id(user_id, Permission.SALES_METHOD_VIEW, entity_id):
        return {"error": "Access denied"}, 403

    methods = (
        SaleInfo.query.filter(
            SaleInfo.entity_id == entity_id,
            SaleInfo.enabled.is_(True),
            SaleInfo.type.in_(["Electronic", "Delivery"]),
        )
        .order_by(SaleInfo.display_order.asc(), SaleInfo.create_date.asc())
        .all()
    )

    return {
        "electronic": [m.sale_name for m in methods if m.type == "Electronic"],
        "delivery": [m.sale_name for m in methods if m.type == "Delivery"],
    }, 200


def replace_sales_methods(user_id, entity_id, electronic, delivery):
    """Reconcile an entity's Electronic/Delivery methods to the given name lists.

    Matches existing rows by (type, sale_name) so renames keep their value_name
    and report-column mapping. Names present in the list are enabled and ordered
    1..n within their type; previously-enabled methods absent from the list are
    soft-disabled (enabled=False), mirroring the Settings page behaviour. New
    names are inserted with a derived value_name.
    """
    if not has_permission_by_user_id(
        user_id, Permission.SALES_METHOD_CREATE, entity_id
    ):
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

    desired = {"Electronic": _clean(electronic), "Delivery": _clean(delivery)}

    existing = SaleInfo.query.filter(
        SaleInfo.entity_id == entity_id,
        SaleInfo.type.in_(["Electronic", "Delivery"]),
    ).all()
    by_type_name = {
        (m.type, (m.sale_name or "").strip().lower()): m for m in existing
    }

    now = datetime.now()
    desired_keys = set()
    for mtype, names in desired.items():
        for i, name in enumerate(names):
            key = (mtype, name.lower())
            desired_keys.add(key)
            method = by_type_name.get(key)
            if method:
                method.enabled = True
                method.sale_name = name
                method.display_order = i + 1
                method.updated_at = now
            else:
                # Resolve the catalog row by display name, falling back to a
                # per-entity custom row. Note the derived value_name below
                # points at a column that does NOT exist for custom methods
                # (e.g. "Tap & Go" -> 'tap_&_go_sales') — the catalog link is
                # what makes such a method storable at all, via
                # report_sale_detail rather than a physical column.
                catalog_row = SalesMethod.resolve(entity_id, name=name)
                if catalog_row is None:
                    catalog_row = SalesMethod.ensure_custom(entity_id, name, mtype)

                db.session.add(
                    SaleInfo(
                        entity_id=entity_id,
                        sale_name=name,
                        value_name=(
                            catalog_row.legacy_column
                            if catalog_row is not None and catalog_row.legacy_column
                            else name.lower().replace(" ", "_") + "_sales"
                        ),
                        type=mtype,
                        sale_info_id=catalog_row.id if catalog_row else None,
                        enabled=True,
                        display_order=i + 1,
                        create_date=now,
                        updated_at=now,
                    )
                )

    for key, method in by_type_name.items():
        if key not in desired_keys and method.enabled:
            method.enabled = False
            method.updated_at = now

    db.session.commit()
    logger.info(
        "replace_sales_methods: entity=%s electronic=%s delivery=%s",
        entity_id, len(desired["Electronic"]), len(desired["Delivery"]),
    )
    return desired, 200


def reorder_payment_methods(user_id, entity_id, method_ids):
    if not has_permission_by_user_id(user_id, Permission.SALES_METHOD_REORDER, entity_id):
        return {"error": "Access denied"}, 403
    if not method_ids or not isinstance(method_ids, list):
        return {"error": "method_ids array is required"}, 400

    for index, method_id in enumerate(method_ids):
        payment_method = SaleInfo.query.filter_by(
            sale_id=method_id, entity_id=entity_id
        ).first()
        if payment_method:
            payment_method.display_order = index + 1
            payment_method.updated_at = datetime.now()

    db.session.commit()
    return {"message": "Payment methods reordered successfully"}, 200

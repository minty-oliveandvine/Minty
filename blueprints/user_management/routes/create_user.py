from datetime import datetime

from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from blueprints.user_management import user_management_bp
from blueprints.user_management.services.create_user import \
    bcrypt_hash_password
from models.db import User, UserEntity, db
from services.authz import require_permission
from services.permission_policy import (
    Permission,
    can_manage_role_assignment_for_entity,
)


@user_management_bp.route("/minty/api/users/create", methods=["POST"])
@login_required
@require_permission(
    Permission.USER_INVITE,
    entity_keys=("company_uuid", "entity_id"),
    message="You do not have permission to invite users to this entity.",
)
def create_user():
    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "Invalid JSON"}), 400
    required_fields = [
        "email",
        "first_name",
        "last_name",
        "password",
        "company_uuid",
        "role",
    ]
    missing = [f for f in required_fields if f not in data or data[f]
               is None or data[f] == ""]
    if missing:
        return (
            jsonify(
                {"status": "error", "message": f"Missing fields: {', '.join(missing)}"}
            ),
            400,
        )
    email = data["email"]
    password = data["password"]
    first_name = data["first_name"]
    last_name = data["last_name"]
    username = email
    company_uuid = data["company_uuid"]
    role = str(data["role"]).strip().lower()
    xero_entity_id = data.get("xero_entity_id")

    if not can_manage_role_assignment_for_entity(current_user, role, company_uuid):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "I can't let you give someone a role above your own.",
                }
            ),
            403,
        )
    existing = User.query.filter_by(email=email).first()
    if existing is not None:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "User with this email is already created.",
                }
            ),
            409,
        )
    try:
        new_user = User(
            email=email,
            username=username,
            first_name=first_name,
            last_name=last_name,
            password=bcrypt_hash_password(password),
            xero_entity_id=xero_entity_id,
            system_role=User.SYSTEM_ROLE_DEFAULT,
        )
        db.session.add(new_user)
        db.session.commit()
        new_user_entity = UserEntity(
            user_id=new_user.id,
            entity_id=company_uuid,
            role=role,
            approved=True,
            joined_at=datetime.now(),
            create_at=datetime.now(),
        )
        db.session.add(new_user_entity)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "User with this email is already created.",
                }
            ),
            409,
        )
    except Exception:
        db.session.rollback()
        raise
    return (
        jsonify(
            {
                "status": "success",
                "user": {
                    "email": email,
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                    "company_uuid": company_uuid,
                    "role": role,
                    "xero_entity_id": xero_entity_id,
                },
                "message": "User created successfully.",
            }
        ),
        201,
    )



from flask import render_template
from flask_login import current_user, login_required

from blueprints.user_management import user_management_bp
from blueprints.user_management.forms import FindUserForm
from models.db import User, UserEntity
from services.permission_policy import Permission, has_permission


@user_management_bp.route("/find_user", methods=["GET", "POST"])
@login_required
def find_user():
    form = FindUserForm()
    memberships = UserEntity.query.filter_by(user_id=current_user.id, approved=True).all()
    allowed_entities = []
    for membership in memberships:
        if has_permission(current_user, Permission.USER_VIEW_ALL, membership.entity_id):
            allowed_entities.append(membership.entity_id)

    form.entity_id.choices = [
        (entity_id, entity_id) for entity_id in sorted(set(allowed_entities))
    ]
    if not allowed_entities:
        return render_template("find_user.html", form=form, userid=None), 403
    first_name = form.first_name.data
    last_name = form.last_name.data
    entity_id = form.entity_id.data
    if not entity_id and form.entity_id.choices:
        entity_id = form.entity_id.choices[0][0]
    if entity_id and entity_id not in allowed_entities:
        return render_template("find_user.html", form=form, userid=None), 403
    user = (
        User.query.with_entities(User.username)
        .join(UserEntity, UserEntity.user_id == User.id)
        .filter(
            User.first_name == first_name,
            User.last_name == last_name,
            UserEntity.entity_id == entity_id,
            UserEntity.approved.is_(True),
        )
        .first()
    )
    return render_template("find_user.html", form=form, userid=user)

# Entity list and report dashboard routes.

from flask import flash, get_flashed_messages, redirect, url_for
from flask_login import current_user, login_required

from blueprints.entity import entity_bp
from blueprints.entity.routes.modules import petty_cash_web_handoff_url
from blueprints.entity.services.entity_list import sign_notices
from blueprints.entity.services.shared import check_user_has_entities
from models.db import Entity, UserEntity
from services.authz import (permission_denied, require_module)
from services.permission_policy import (Permission, has_permission, is_superuser)


@entity_bp.route("/entity")
@login_required
def entity_list():
    """The entity list is minty-web's ``/entities`` (the ``MINTY_WEB_HUB`` switch went in phase
    2, 2026-10-05, with Flask's Jinja list) - Terms owed or not: minty-web draws the acceptance
    panel itself, over every page (its TermsGate, over legal/routes/hub.py), so the gate's
    redirect to here carries on to it."""
    return _to_minty_web_list()


def _to_minty_web_list():
    """On to minty-web's list, carrying what the redirect that brought the person here
    flashed. Seventy-odd routes flash a message ("couldn't find that one", "no permission to
    look there") and redirect to /entity; minty-web cannot read this session, so the
    messages are drained here and signed into the URL, and minty-web's list shows them."""
    from blueprints.entity.routes.modules import minty_web_entity_list_url

    notices = sign_notices(get_flashed_messages(with_categories=True))
    return redirect(minty_web_entity_list_url(current_user.id, notices=notices))


@entity_bp.route("/entity/<entity:id>/petty-cash")
@login_required
@require_module(
    "PETTY_CASH",
    entity_arg="id",
    message="Petty Cash is not activated for this entity.",
)
def report_dashboard(id):
    id = (id or "").strip()
    if not check_user_has_entities(current_user.id):
        flash(
            "You'll need to create an entity before I can show you the report dashboard.",
            "info",
        )
        return redirect(url_for("entity.entity_list"))
    # entities.id is a uuid: no trim() on the column (Postgres has no btrim(uuid)); the
    # URL value is stripped before the compare instead.
    org = Entity.query.filter(Entity.id == id.strip()).first()
    if not org:
        flash("Hmm, I looked everywhere but couldn't find that one.", "danger")
        return redirect(url_for("entity.entity_list"))

    user_entity = UserEntity.query.filter(
        UserEntity.user_id == current_user.id, UserEntity.entity_id == id
    ).first()
    # Superusers can enter any entity even without a user_entity row.
    # has_permission will gate writes via the readonly path.
    if not user_entity and not is_superuser(current_user):
        return permission_denied("You don't have access to this entity", entity_id=id)
    if not has_permission(current_user, Permission.ENTITY_VIEW, id):
        return permission_denied(
            "You do not have permission to view this entity.", entity_id=id
        )

    # Petty Cash is minty-petty-cash-web's (Flask draws no page since 2026-10-20): the older front
    # ends, the emails and Xero's callback still land here (through /enter), so this hands over.
    # The hand-off sends a company mid-onboarding back to the wizard on its own.
    return redirect(petty_cash_web_handoff_url(id))


# Entity list and report dashboard. Logic moved from app.

"""The gate for every route in the capture blueprint.

Three checks, in this order, as one ``before_request`` rather than a decorator
on each route — a single auditable gate that cannot be forgotten when someone
adds a route next month.

  1. THE KILL SWITCH. Off means 404, not 403. When the feature is off it does
     not exist, and a 403 would tell an unauthenticated prober that there is
     something here worth having.

  2. THE MODULE GATE. PETTY_CASH **or** BILL opens it.

     This is the whole reason the capture hub is not in the report blueprint.
     That blueprint's guard requires PETTY_CASH for every one of its ~30
     routes, so a customer who bought Payment Submission and not Petty Cash
     would be locked out of their own capture hub. Read
     ``blueprints/report/routes/module_guard.py`` beside this file.

     Remember that BILL means PAYMENT. The database constant was never renamed
     because renaming it would be a risky migration with no user benefit; every
     word a user can see says "Payment".

  3. FAIL CLOSED. The report guard deliberately fails OPEN when it cannot
     resolve an entity, because many of its routes (generic file downloads,
     legacy public links) genuinely carry no entity context. Every route here
     carries one. If we cannot resolve an entity, that is a bug or an attack,
     and the answer is 403.

The per-user permission check is NOT here. This gate answers "does this company
have the feature"; each route answers "is this person allowed to use it", with
``has_permission``. Two different questions, two different failure messages.
"""

from __future__ import annotations

from flask import abort, request
from loguru import logger

from blueprints.capture import capture_bp
from blueprints.capture.services import capture_ai


def _from_request(keys):
    """First non-empty value for any of ``keys`` across URL args, query string,
    form, and JSON body."""
    view_args = request.view_args or {}
    for key in keys:
        if view_args.get(key):
            return str(view_args[key])
    for key in keys:
        value = request.args.get(key) or request.form.get(key)
        if value:
            return str(value)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        for key in keys:
            if body.get(key):
                return str(body[key])
    return None


def resolve_entity_id():
    """Best-effort entity id for the current capture request, or None.

    Order matters: a value carried directly on the request is checked first,
    then a draft or upload id is resolved to its OWNING row's entity. Note that
    the second path is what makes a forged entity_id useless — the row's own
    entity is what every authorisation check compares against, never the value
    the client sent.
    """
    entity_id = _from_request(("entity_id", "org_id"))
    if entity_id:
        return entity_id

    # Imported lazily. Importing models at module load creates a circular
    # import with the models package (this routes package is imported while
    # models.db is still initialising), which would silently disable the guard
    # — the exact failure ``blueprint_loader`` warns about.
    from blueprints.capture.models.capture_draft import CaptureDraft
    from blueprints.capture.models.capture_upload import CaptureUpload

    draft_id = _from_request(("draft_id",))
    if draft_id:
        draft = CaptureDraft.query.get(draft_id)
        if draft:
            return draft.entity_id

    upload_id = _from_request(("upload_id",))
    if upload_id:
        upload = CaptureUpload.query.get(upload_id)
        if upload:
            return upload.entity_id

    return None


def entity_has_capture(entity_id: str) -> bool:
    """True when either module that can receive a draft is switched on."""
    from blueprints.entity.routes.modules import _is_module_enabled

    return bool(
        _is_module_enabled(entity_id, "PETTY_CASH")
        or _is_module_enabled(entity_id, "BILL")
    )


@capture_bp.before_request
def _enforce_capture_gate():
    if request.method == "OPTIONS":
        return None

    # 1. The kill switch, before anything else — no database work, no context
    #    assembly, no cost, on a feature nobody has turned on.
    if not capture_ai.is_enabled():
        abort(404)

    entity_id = resolve_entity_id()
    if not entity_id:
        logger.info(
            "capture: no entity could be resolved for {} — denying", request.path
        )
        from services.authz import permission_denied

        return permission_denied("No company was identified for this request.")

    try:
        allowed = entity_has_capture(entity_id)
    except Exception as exc:
        # Fail CLOSED. A transient database error here must not become a way
        # in. The cost of being wrong in this direction is a user seeing an
        # error for a few seconds; in the other direction it is a customer
        # using a module they have not bought.
        logger.error("capture: module gate error entity={}: {}", entity_id, exc)
        allowed = False

    if allowed:
        return None

    from services.authz import DENIAL_MODULE_INACTIVE, permission_denied

    return permission_denied(
        "The AI Hub needs either Petty Cash or Payment Submission "
        "switched on for this company.",
        entity_id=entity_id,
        reason=DENIAL_MODULE_INACTIVE,
    )

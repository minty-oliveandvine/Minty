"""A person's own profile: what minty-web's My Profile shows and saves (``routes/me_api.py``),
and the one place the name-and-email rules live - the session route
``PATCH /minty/api/users/me`` (``routes/roles.py``) saves through ``update_profile`` too.

The email rules are billing-backend's ``bills/services/profile_service.update_user_profile``,
ported: that copy keeps serving billing-frontend's old profile page until the Part 2 step 5
cut deletes the page. One rule of that copy is deliberately NOT ported - its
``check_not_system_superuser`` refusal. That guard is about a superuser writing inside a
company they are not a member of; a person editing their own name writes into no company,
and Flask's own session route never refused it.
"""

from __future__ import annotations

import uuid

from loguru import logger
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from blueprints.shared.email_rules import EMAIL_ASCII_MESSAGE, is_ascii_email
from blueprints.shared.enums import entity_role_label
from models.db import Entity, User, UserEntity, db
from services.permission_policy import has_entity_access, is_superuser

#: The fields ``update_profile`` accepts; every other key is ignored by its callers.
EDITABLE_FIELDS = ("first_name", "last_name", "email", "user_phone")


class ProfileError(ValueError):
    """A refusal worded for the person - shown as it stands."""


def _normalized(value: str | None) -> str:
    return (value or "").strip()


def display_name(user) -> str:
    """"First Last", or the email when the account carries no name."""
    name = f"{_normalized(user.first_name)} {_normalized(user.last_name)}".strip()
    return name or _normalized(user.email) or _normalized(user.username)


def initials(user) -> str:
    """The avatar's letters - the first of each name, upper-cased; "?" with neither. The same
    rule the Jinja headers spell inline as ``user_abbrev``, computed here once for minty-web."""
    letters = (_normalized(user.first_name)[:1] + _normalized(user.last_name)[:1]).upper()
    return letters or "?"


def entity_context(user, entity_id: str) -> dict | None:
    """The company the profile was opened from - its name, the person's role there and the
    modules it has on - or None when there is no such company or the person may not see it
    (the same test ``/handoff/minty-web`` applies). A superuser without a membership sees
    the company with no role."""
    try:
        uuid.UUID(str(entity_id))
    except ValueError:
        return None  # not an id at all: Postgres would refuse the comparison outright
    org = Entity.query.filter(Entity.id == entity_id).first()
    if org is None or not (is_superuser(user) or has_entity_access(user, entity_id)):
        return None

    from blueprints.entity.services.modules import get_enabled_modules_for_entities

    membership = UserEntity.query.filter_by(user_id=user.id, entity_id=org.id).first()
    role = str(membership.role) if membership is not None and membership.role else None
    return {
        "id": str(org.id),
        "name": org.name,
        "role": role,
        "role_label": entity_role_label(role),
        "modules": sorted(get_enabled_modules_for_entities([org.id]).get(org.id, set())),
    }


def profile_payload(user, entity: dict | None = None) -> dict:
    """What My Profile reads: the person, and the company it was opened from when it was."""
    return {
        "user": {
            "id": str(user.id),
            "first_name": _normalized(user.first_name),
            "last_name": _normalized(user.last_name),
            "name": display_name(user),
            "initials": initials(user),
            "email": _normalized(user.email),
        },
        "entity": entity,
    }


def _address_taken(column, address: str, user_id) -> bool:
    return (
        db.session.query(User.id)
        .filter(func.lower(column) == address.casefold(), User.id != user_id)
        .first()
        is not None
    )


def update_profile(user, **fields) -> None:
    """Save the fields given (a subset of ``EDITABLE_FIELDS``) on ``user`` and commit.

    Names are trimmed. The email is the awkward one, because it is half of how the account is
    identified and the two halves live in different columns: sign-in and the email-code check
    read ``user.username`` (which sign-up fills FROM the email), password reset reads
    ``user.email``. So when ``username`` currently holds the old email it moves with it; when
    it holds something else it is a handle chosen separately and is left alone. Both columns
    are UNIQUE: a collision is checked up front and re-caught around the commit (another
    request can take the address in between), and either way it is a ``ProfileError``.
    """
    if "email" in fields:
        email = _normalized(fields["email"])
        if not email:
            raise ProfileError("I'll need an email address here.")
        # Not a full RFC check - the point is to refuse input that could never receive a
        # password-reset mail, since an unreachable address here locks the account out.
        if " " in email or email.count("@") != 1 or not all(email.split("@")):
            raise ProfileError("That doesn't look like an email address.")
        if not is_ascii_email(email):
            raise ProfileError(EMAIL_ASCII_MESSAGE)

        previous = _normalized(user.email)
        if email.casefold() != previous.casefold():
            logger.info(f"Profile email change user_id={user.id} from={previous} to={email}")
            if _address_taken(User.email, email, user.id):
                raise ProfileError("That email address is already in use.")
            if _normalized(user.username).casefold() == previous.casefold():
                if _address_taken(User.username, email, user.id):
                    raise ProfileError("That email address is already in use.")
                user.username = email
            user.email = email

    for name in ("first_name", "last_name"):
        if name in fields:
            setattr(user, name, _normalized(fields[name]))
    if "user_phone" in fields:
        user.user_phone = fields["user_phone"]

    try:
        db.session.commit()
    except IntegrityError:
        # Lost the race for the address between the check above and the write.
        db.session.rollback()
        logger.warning(f"Profile update hit a unique conflict user_id={user.id}")
        raise ProfileError("That email address is already in use.")
    logger.info(f"Profile updated user_id={user.id} fields={sorted(fields)}")

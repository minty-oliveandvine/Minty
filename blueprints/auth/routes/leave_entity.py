from flask import redirect, session, url_for
from flask_login import current_user, login_required

from blueprints.auth import auth_bp


@auth_bp.route("/leave-entity")
@login_required
def leave_entity():
    """Log out of the COMPANY you are in, back to the entity list.

    "Log out" means two different things depending on where it is pressed, and this
    is the inside-a-company one: you are done with this company, not with Minty. The
    Flask session deliberately survives, so picking another company costs nothing.
    Pressing Log out again from the entity list — where there is no company to leave
    — goes to ``auth.logout`` and really does end the session.

    Presence IS dropped, even though the session lives on. Settings > Users answers
    "who is here right now", and someone who has just walked out of the company is
    not. ``mark_signed_out`` clears ``signed_in_at`` and stamps ``last_seen_at``
    together, which is what stops the entity list they are about to land on from
    reading the blank as never-stamped and adopting them straight back (see
    ``refresh_presence`` in services/user_presence.py). Re-entering a company calls
    ``resume_presence`` and puts them back.

    The billing module's Log out does the same thing from its side: drop presence,
    keep the session, land on the entity list.
    """
    # Imported HERE, not at module scope. The auth blueprint is imported early, and a
    # module-level import binds services.user_presence — and the ``User`` class its
    # criteria are built from — at that moment. Anything that re-imports the project
    # afterwards then has two mapped classes for one table, which SQLAlchemy resolves
    # as a self-join: "ambiguous column name: user.id". The same reason
    # ``check_not_subscription_payer_or_error`` defers its own import.
    from services.user_presence import mark_signed_out

    # The handoff token for the company being left. Held in the session for module
    # re-entry, and meaningless once you are out of it.
    session["token"] = None
    mark_signed_out(current_user)
    return redirect(url_for("entity.entity_list"))

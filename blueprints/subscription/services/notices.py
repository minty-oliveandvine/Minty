"""The dashboard subscription notice: which one popup an entity gets, and once.

Moved out of ``entity.services.modules``. Deciding that a company is past due or is
winding down is subscription reasoning -- it reads phases and paid periods -- and it was
sitting in the entity blueprint only because the module card it derives from does.

NO TRIAL NOTICE (the user, 2026-10-01): a trial about to end, a trial that will not convert
(no card / no consent), a lapsed trial and a cancelled trial running out all say nothing
here. The trial-ending EMAIL (``notify.TRIAL_ENDING``) still warns a trial that will not
convert; the Module page in minty-web shows every trial's state.

WHAT STAYS BEHIND: ``entity.services.modules`` re-exports both names, so every importer
keeps working -- and there are several import styles among them (``routes/list.py`` binds
at module level, ``routes/modules.py`` imports inside the request). Everything this module
reads back off the entity side -- ``get_module_cards``, ``_NOTICE_ORDER``,
``NOTICE_SEEN_SESSION_KEY`` -- goes through the MODULE OBJECT and is resolved at call time,
never bound at import.

That is not stylistic. ``test_subscription_notice.py`` patches
``blueprints.entity.services.modules.get_module_cards`` and
``...build_subscription_notices`` by dotted path; a ``from ... import`` here would capture
the real values at import and the patches would be silently ignored (docs/code_cleanse/CODE_CLEANSE_NOTES.md,
"dependency injection is required in this repo").
"""
from __future__ import annotations

from blueprints.entity.services import modules as entity_modules


def build_subscription_notices(entity_id: str, user_id) -> dict:
    """Everything worth interrupting someone with when they enter an entity.

    ENTITY-WIDE, not per-module: billing is per payer and the anchor is shared, so a
    declined card affects every module the entity holds. Both landing pages (Petty
    Cash here, Payment in the billing frontend) show the same list, each item naming
    the module it is about.

    Deliberately reuses ``get_module_cards`` rather than re-deriving state. Every
    condition below is already a field on those cards, computed against the
    subscription rows that the billing engine itself reads — so the modal, the
    settings page and the invoice cannot disagree about what is wrong.

    Returns ``items: []`` when there is nothing to say; callers treat that as
    "render nothing" rather than rendering an empty modal.
    """
    from blueprints.subscription.services import store as sub_store
    from models.db import User
    from services.permission_policy import Permission, has_permission_by_user_id

    cards = entity_modules.get_module_cards(entity_id)
    items: list[dict] = []

    for card in cards:
        name = card.get("name") or card.get("code")
        code = card.get("code")

        # 1. Money already failed. The most urgent thing that can be true: access
        #    ends on a date the payer can still act before.
        if card.get("subscription_status") == "past_due":
            items.append(
                {
                    "kind": "past_due",
                    "severity": "critical",
                    "module": name,
                    "module_code": code,
                    "title": f"{name} payment failed",
                    "detail": (
                        f"Pay by {card['access_end_long']} to keep access."
                        if card.get("access_end_long")
                        else "Update your payment method to keep access."
                    ),
                    "deadline": card.get("access_end_long"),
                }
            )
            continue

        # 2. Winding down — a PAID module cancelled but still inside the paid period.
        #    A cancelled free trial sets ``pending_cancel`` too (cards.py: it is still a
        #    trial, running out its free days); it is a trial notice, and every trial
        #    notice was removed on 2026-10-01 by the user's decision - so it says nothing.
        if (
            card.get("pending_cancel")
            and card.get("access_end_long")
            and not card.get("trial_cancelled")
        ):
            items.append(
                {
                    "kind": "pending_cancel",
                    "severity": "warning",
                    "module": name,
                    "module_code": code,
                    "title": f"{name} is ending",
                    "detail": (
                        f"Access until {card['access_end_long']}. It won't be billed again."
                    ),
                    "deadline": card.get("access_end_long"),
                }
            )

    items.sort(key=lambda i: entity_modules._NOTICE_ORDER.index(i["kind"]))

    # Who may actually act. Permission says who administers the entity; the payer is
    # whose card the buttons spend — @require_subscription_payer refuses anyone else
    # server-side, so offering them an action would produce a button that fails.
    can_manage = bool(
        user_id
        and has_permission_by_user_id(
            str(user_id), Permission.MODULE_MANAGE, entity_id
        )
        and sub_store.may_manage_subscription(entity_id, user_id)
    )

    payer = None
    payer_id = sub_store.payer_for_entity(entity_id)
    if payer_id and str(payer_id) != str(user_id):
        payer_user = User.query.get(str(payer_id))
        if payer_user:
            payer = {
                "name": " ".join(
                    p for p in (payer_user.first_name, payer_user.last_name) if p
                ).strip(),
                "email": payer_user.email or "",
            }

    return {
        "items": items,
        "can_manage": can_manage,
        "payer": payer,
        "severity": items[0]["severity"] if items else None,
    }


def claim_subscription_notice(session, entity_id: str) -> bool:
    """Whether to show the notice now — and if so, mark it shown for this session.

    "Always appear when first logged in to the entity": once per entity per login,
    not once per page view and not once forever. A user who fixes the problem and
    comes back tomorrow should be told if it is still broken.

    Consumes rather than merely reads, because that is what makes the cost bearable:
    ``build_subscription_notices`` is only ever called when this returns True, so the
    subscription queries run once per entity per session instead of on every dashboard
    load. A previous per-page-view billing read was removed for exactly that reason
    (see the comment in ``routes.modules.module_selection``).

    Takes the session as a parameter rather than importing ``flask.session`` so it is
    testable with a plain dict, and so the JSON endpoint — which is stateless and
    always returns the notice — can simply not call it.
    """
    if not entity_id:
        return False
    seen = session.get(entity_modules.NOTICE_SEEN_SESSION_KEY) or []
    if str(entity_id) in seen:
        return False
    # Reassign rather than mutate in place: Flask's session only marks itself dirty
    # on __setitem__, so appending to the existing list would not persist.
    session[entity_modules.NOTICE_SEEN_SESSION_KEY] = [*seen, str(entity_id)]
    return True

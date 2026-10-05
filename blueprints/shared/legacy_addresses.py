"""Old page addresses, kept working: each one 308-redirects to its new address (2026-10-05).

Company pages moved to ``/entity/<shortid>/<name>/...`` (``entity_ref.py``) and their paths to
one scheme. A bookmark, an email already sent, or a page loaded before the deploy may still use
an old address, so every old rule here answers with a permanent redirect - 308, which keeps the
method and body, so a form posted to an old address still lands - with the query kept.

Old rules take ``<uuid:...>``, never a free string, so they can never be confused with a
``<shortid>/<name>`` address.

An old address whose path was only ``/entity/<uuid>[/...]`` with an unchanged tail needs no entry:
the ``<entity:...>`` converter accepts a full uuid and redirects to the readable form itself.
"""

from __future__ import annotations

from flask import Blueprint, redirect, request, url_for

legacy_bp = Blueprint("legacy", __name__)

ALL_METHODS = ["GET", "POST"]

#: (old rule, endpoint name of the redirect, target endpoint, {old arg: target arg}, methods)
LEGACY_ADDRESSES: list[tuple[str, str, str, dict[str, str], list[str]]] = [
    ("/entity/<uuid:entity_id>/bills", "bills", "entity.go_to_bills", {"entity_id": "entity_id"}, ["GET"]),
    ("/entity/<uuid:entity_id>/settings/xero", "settings_xero", "entity.entity_settings",
     {"entity_id": "entity_id"}, ALL_METHODS),
    ("/entity/settings/users/<uuid:org_id>", "settings_users", "entity.entity_settings_users",
     {"org_id": "org_id"}, ["GET"]),
    ("/entity/settings/entity/<uuid:org_id>", "settings_entity", "entity.entity_settings_entity",
     {"org_id": "org_id"}, ALL_METHODS),
    ("/entity/settings/module/<uuid:org_id>", "settings_module", "entity.entity_settings_module",
     {"org_id": "org_id"}, ["GET"]),
    ("/entity/settings/payments/<uuid:org_id>", "settings_payments", "entity.entity_settings_payments",
     {"org_id": "org_id"}, ["GET"]),
    ("/invitation/xero-not-connected/<uuid:entity_id>", "xero_not_connected",
     "invitation.xero_not_connected", {"entity_id": "entity_id"}, ["GET"]),
    ("/entity/<uuid:entity_id>/report/opening", "report_opening", "report.report_opening",
     {"entity_id": "entity_id"}, ALL_METHODS),
    ("/entity/<uuid:entity_id>/ending/<string:report_id>", "ending_with_report",
     "report.entity_ending_with_report", {"entity_id": "entity_id", "report_id": "report_id"}, ["GET"]),
    ("/entity/<uuid:entity_id>/ending", "ending", "report.entity_ending", {"entity_id": "entity_id"}, ["GET"]),
]


def _redirect_view(target: str, arg_map: dict[str, str]):
    def view(**old_args):
        location = url_for(target, **{new: str(old_args[old]) for old, new in arg_map.items()})
        if request.query_string:
            location += "?" + request.query_string.decode("latin-1")
        return redirect(location, code=308)

    return view


for _rule, _name, _target, _args, _methods in LEGACY_ADDRESSES:
    legacy_bp.add_url_rule(_rule, endpoint=_name, view_func=_redirect_view(_target, _args), methods=_methods)

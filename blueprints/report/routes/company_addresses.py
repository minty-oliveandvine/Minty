"""The report wizard's addresses live under the company (2026-10-05):
``/entity/<shortid>/<name>/reports/<report id>/<step>`` and ``.../reports/new/<step>``.

Two rules for the whole report blueprint, kept here once rather than in each wizard view:

* **Old addresses move.** A signed-in GET of an old ``/report/...`` wizard address (a bookmark,
  a link drawn before the deploy) is 308-redirected to the company address, with ``entity_id``
  dropped from the query - it is in the path now. The company comes from ``?entity_id=`` or the
  report itself. A POST to an old address is served where it is (its form was drawn by an older
  page), and a signed-out GET is left to the login redirect, so an address never tells a
  stranger which company a report id belongs to.
* **The company in the address must own the report.** A report id under another company's
  address is a 404, logged - the guards check the company in the address, so a mismatch would
  otherwise show one company's report under another's permissions.
"""

from __future__ import annotations

from flask import abort, redirect, request, url_for
from flask_login import current_user
from loguru import logger

from blueprints.report import report_bp

#: The wizard (and resume) endpoints that have a company address.
WIZARD_ENDPOINTS = frozenset({
    "report.report_opening",
    "report.report_sale",
    "report.report_expense",
    "report.report_deposit",
    "report.report_cash_count",
    "report.report_ending",
    "report.report_submitted",
    "report.resume_report",
})


@report_bp.before_request
def _company_addresses():
    if request.endpoint not in WIZARD_ENDPOINTS or request.url_rule is None:
        return None
    view_args = request.view_args or {}
    report_id = view_args.get("id")
    from blueprints.report.services.shared import resolve_report_entity_id

    if request.url_rule.rule.startswith("/entity/"):
        if report_id:
            owner = resolve_report_entity_id(report_id)
            if owner is not None and owner != str(view_args.get("entity_id")):
                logger.warning(
                    f"report {report_id} asked for under company {view_args.get('entity_id')}, "
                    f"but it belongs to {owner}"
                )
                abort(404)
        return None

    # An old /report/... address.
    if request.method != "GET" or not getattr(current_user, "is_authenticated", False):
        return None
    entity_id = request.args.get("entity_id") or resolve_report_entity_id(report_id)
    if not entity_id:
        return None
    target = url_for(request.endpoint, entity_id=entity_id, **view_args)
    query = request.args.copy()
    query.pop("entity_id", None)
    if query:
        from urllib.parse import urlencode

        target += "?" + urlencode(list(query.items(multi=True)))
    return redirect(target, code=308)

# Report ending route wrappers.
from flask import request
from flask_login import login_required

from blueprints.report import report_bp


@report_bp.route("/report/<string:id>/ending", methods=["GET"])
@report_bp.route("/report/ending", methods=["GET", "POST"])
@login_required
def report_ending(id=None, entity_id=None, skip_auth=False):
    from ..services.ending import report_ending as _impl

    if entity_id is None:
        entity_id = request.args.get("entity_id")
    return _impl(id=id, entity_id=entity_id, skip_auth=skip_auth)


@report_bp.route("/entity/<string:entity_id>/ending/<string:report_id>", methods=["GET"])
@login_required
def entity_ending_with_report(entity_id, report_id):
    from ..services.ending import entity_ending_with_report as _impl

    return _impl(entity_id, report_id)


@report_bp.route("/report/<string:report_id>/convert-to-draft", methods=["POST"])
@login_required
def convert_report_to_draft(report_id):
    from ..services.ending import convert_report_to_draft as _impl

    return _impl(report_id)


@report_bp.route("/entity/<string:entity_id>/ending", methods=["GET"])
def entity_ending(entity_id):
    from ..services.ending import entity_ending as _impl

    return _impl(entity_id)

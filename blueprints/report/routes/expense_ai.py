"""POST /report/expense/extract — read a receipt beside the expense form.

Stage 1 §7.2. This endpoint sits *beside* the Add New Expense card and never
inside Add: if it is slow, rate limited, or down, the card behaves exactly as
it does today and the user types the four fields. Expense entry can never be
blocked by an AI outage.

Every outcome is HTTP 200. A failure is `{"suggestions": null, "reason": ...}`
and the page shows nothing — unavailable means invisible (§7.4, §9.3). A
non-200 would only invite the browser to treat this as an error worth
surfacing, which is precisely what §9 rules out.

``read_receipt`` - everything after the checks - is shared with the Petty Cash API's
``POST /reports/expenses/extract`` and with ``POST /api/internal/petty-cash/expense-extract``
(below), through which minty-petty-cash-api, holding no model code, reads a receipt
(``petty_cash_api/routes/expenses.py::extract_answer``).
"""

from flask import jsonify, request
from flask_login import current_user, login_required
from services.app_runtime.log import logger

from blueprints.report import report_bp
from blueprints.report.services import expense_ai
from blueprints.report.services.shared import resolve_report_entity_id
from models.db import Report
from services.permission_policy import Permission, has_permission


def _no_suggestion(reason):
    return jsonify({"suggestions": None, "reason": reason}), 200


@report_bp.route("/report/expense/extract", methods=["POST"])
@login_required
def report_expense_extract():
    # The kill switch first: off means no context assembly, no model call, no
    # charge (§11.1).
    if not expense_ai.is_enabled():
        return _no_suggestion(expense_ai.REASON_DISABLED)

    # entity_id is resolved and re-validated server-side. A client-supplied
    # value is never trusted (§8.2).
    entity_id = request.form.get("entity_id") or request.args.get("entity_id")
    report_id = request.form.get("report_id") or None
    if not entity_id:
        entity_id = resolve_report_entity_id(report_id)
    if not entity_id:
        return _no_suggestion(expense_ai.REASON_NO_CONTEXT)

    if not has_permission(current_user, Permission.REPORT_EDIT_OWN, entity_id):
        # Deliberately the same shape as any other "no suggestion": the page
        # has nothing useful to do with the distinction, and saying which
        # entities exist is not something an unauthorised caller should learn.
        logger.warning(
            "expense_ai: extract denied user={} entity={}",
            getattr(current_user, "id", None), entity_id,
        )
        return _no_suggestion(expense_ai.REASON_NO_CONTEXT)

    # A report id is recorded for measurement only, and only when it really
    # belongs to this entity.
    if report_id:
        report = Report.query.filter_by(id=report_id).first()
        if not report or str(report.company) != str(entity_id):
            report_id = None

    if not expense_ai.check_rate_limit(getattr(current_user, "id", ""), entity_id):
        logger.info("expense_ai: rate limited entity={}", entity_id)
        return _no_suggestion(expense_ai.REASON_RATE_LIMITED)

    uploaded = request.files.get("file")
    if not uploaded:
        return _no_suggestion(expense_ai.REASON_UNSUPPORTED_FILE)

    # Read under this route's own cap. The global MAX_CONTENT_LENGTH is far too
    # permissive for a model call (§7.2), and the bytes are held in memory for
    # the request only — never written to disk, a log, or the audit table.
    cap = expense_ai.max_file_bytes()
    data = uploaded.read(cap + 1)
    if not data:
        return _no_suggestion(expense_ai.REASON_UNSUPPORTED_FILE)
    if len(data) > cap:
        return _no_suggestion(expense_ai.REASON_FILE_TOO_LARGE)

    # Sniffed content, not the file extension (§7.2). An unsupported or corrupt
    # file returns here: no model call, no charge.
    mime = expense_ai.sniff_mime(data)
    if mime is None:
        return _no_suggestion(expense_ai.REASON_UNSUPPORTED_FILE)

    return jsonify(read_receipt(entity_id, getattr(current_user, "id", None), data, mime)), 200


def read_receipt(entity_id, user_id, data: bytes, mime: str) -> dict:
    """The model's reading of a receipt already checked by the caller (who may ask, the rate
    limit, the bytes and their sniffed ``mime``): the entity's lists, the call, the ONE log line,
    and the answer ``{suggestions, reason}`` - ``suggestions`` null on every failure. Shared by
    this page's route, the Petty Cash API's ``POST /reports/expenses/extract`` and the internal
    route minty-petty-cash-api forwards to (``petty_cash_api/routes/expenses.py::extract_answer``)."""
    context = expense_ai.build_entity_context(entity_id)
    if context is None:
        logger.info("expense_ai: no accounts or contacts for entity={}", entity_id)
        return {"suggestions": None, "reason": expense_ai.REASON_NO_CONTEXT}

    document, mime = expense_ai.prepare_document(data, mime)
    result = expense_ai.extract(document, mime, context)

    status = "ok" if result.suggestions and not result.reason else "no_suggestion"
    # This is the ONLY record of an attempt — there is no audit table, by
    # decision. Anything not written here is not recoverable later.
    #
    # It carries the numbers and NOT the values: confidence scores, token
    # counts and timings, but never the amount, supplier or description read
    # off the receipt. Those are a client's financial details and logs are the
    # wrong place for them.
    confidences = {
        name: field.get("confidence")
        for name, field in (result.suggestions or {}).items()
        if isinstance(field, dict)
    }
    logger.info(
        "expense_ai: extract entity={} user={} model={} location={} "
        "latency_ms={} tokens_in={} tokens_out={} thought={} cached={} "
        "cost={} status={} reason={} confidence={}",
        entity_id, user_id,
        result.audit.get("model_id"), result.audit.get("location"),
        result.audit.get("latency_ms"), result.audit.get("input_tokens"),
        result.audit.get("output_tokens"), result.audit.get("thought_tokens"),
        result.audit.get("cached_tokens"), result.audit.get("estimated_cost"),
        status, result.reason, confidences,
    )

    if not result.suggestions:
        return {"suggestions": None, "reason": result.reason or expense_ai.REASON_NO_USABLE_FIELD}
    return {"suggestions": result.suggestions, "reason": result.reason}


#: minty-petty-cash-api's scope for ``internal_expense_extract``.
_EXPENSE_EXTRACT_SCOPE = "petty-cash-expense-extract"


@report_bp.route("/api/internal/petty-cash/expense-extract", methods=["POST"])
def internal_expense_extract():
    """The receipt reader for minty-petty-cash-api, which holds no model code: this module and
    ``services/expense_ai.py`` stay the only place that talks to the model. Multipart ``receipt``
    -> the Petty Cash API's own answer (``petty_cash_api/routes/expenses.py::extract_answer``),
    handed on unchanged.

    The caller presents a 60-second HS256 assertion (the shared SECRET_KEY, checked by the Xero
    internal routes' ``_authenticate_internal_caller``) whose claims name the company
    (``entity_id``) and the person (``user_id``); neither is read from the body. The person is
    checked again here (approved; ``REPORT_EDIT_OWN`` on the company) and so is the file.

    SECURITY: like ``/api/internal/xero/token``, not meant to be reachable from the internet.
    """
    from blueprints.petty_cash_api.routes.expenses import extract_answer
    from blueprints.xero.routes.routes import _authenticate_internal_caller
    from models.db import User, db

    claims, error = _authenticate_internal_caller(_EXPENSE_EXTRACT_SCOPE, ("user_id",))
    if error:
        logger.warning(f"internal expense extract: rejected caller ({error})")
        return jsonify({"error": "unauthorized"}), 401
    person = db.session.get(User, str(claims["user_id"]))
    if person is None or not person.approved:
        logger.warning(f"internal expense extract: unknown or unapproved user {claims['user_id']}")
        return jsonify({"error": "unauthorized"}), 401
    answer, status = extract_answer(str(claims["entity_id"]), person, request.files.getlist("receipt"))
    logger.info(f"internal expense extract: entity {claims['entity_id']} by {person.id} -> {status}")
    return jsonify(answer), status

"""Reading a receipt with the model - for the Petty Cash API, never a page.

``read_receipt`` is shared by the Petty Cash API's ``POST /reports/expenses/extract`` and by
``POST /api/internal/petty-cash/expense-extract`` (below), through which minty-petty-cash-api,
holding no model code, reads a receipt (``petty_cash_api/routes/expenses.py::extract_answer``).
The Jinja expense page's ``POST /report/expense/extract`` went with Flask's pages on 2026-10-20.

Every outcome is HTTP 200: a failure is ``{"suggestions": null, "reason": ...}`` and the app
shows nothing - unavailable means invisible (Stage 1 §7.4, §9.3).
"""

from flask import jsonify, request
from loguru import logger

from blueprints.report import report_bp
from blueprints.report.services import expense_ai


def read_receipt(entity_id, user_id, data: bytes, mime: str) -> dict:
    """The model's reading of a receipt already checked by the caller (who may ask, the rate
    limit, the bytes and their sniffed ``mime``): the entity's lists, the call, the ONE log line,
    and the answer ``{suggestions, reason}`` - ``suggestions`` null on every failure. Shared by
    the Petty Cash API's ``POST /reports/expenses/extract`` and the internal route
    minty-petty-cash-api forwards to (``petty_cash_api/routes/expenses.py::extract_answer``)."""
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

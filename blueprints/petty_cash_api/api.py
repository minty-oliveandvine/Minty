"""How the Petty Cash API answers: JSON, CORS on everything, never a cached answer, and a
refusal is ``{"error": <sentence>}`` - a sentence the app shows as it stands, except
``unauthorized``, which it answers by going back through ``/handoff/petty-cash-web`` for a
fresh token.

CORS is stamped in ``after_request`` rather than per view, so a refusal from the guard, an
``abort`` and an unexpected 500 all carry it: a bare 401 reads to the browser as a CORS
failure, and the app only re-authenticates on a 401 it can see.
"""
from __future__ import annotations

from flask import g, jsonify, make_response
from loguru import logger
from werkzeug.exceptions import HTTPException

from blueprints.petty_cash_api import petty_cash_api_bp
from blueprints.shared import bearer_api, preview_origin

#: Everything the routes answer between them; a preflight for anything else is refused by the
#: browser before a route is reached.
METHODS = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
#: What a 500 says. The detail goes to the log, never to the caller.
FAILED = "Something went wrong on our side. Please try again."


def respond(payload, status: int = 200):
    return make_response(jsonify(payload), status)


def refuse(error: str, status: int):
    return respond({"error": error}, status)


def user():
    """The person the guard let in."""
    return g.petty_cash_user


def company() -> dict:
    """The company the guard let them into: ``profile.entity_context``'s dict."""
    return g.petty_cash_company


@petty_cash_api_bp.after_request
def _stamp(resp):
    origin = preview_origin.cors_origin((bearer_api.petty_cash_web_origin(),), ("pettycash",))
    bearer_api.cors(resp, origin, methods=METHODS)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@petty_cash_api_bp.errorhandler(HTTPException)
def _http_error(exc: HTTPException):
    return refuse(exc.description or exc.name, exc.code or 500)


@petty_cash_api_bp.errorhandler(Exception)
def _failure(exc: Exception):
    """Anything a guard or a view did not expect: logged in full, answered generically, and the
    transaction rolled back so nothing half-written is committed by a later request."""
    from models.db import db

    db.session.rollback()
    logger.exception(f"Petty Cash API failure on company {g.get('petty_cash_entity_id')!r}: {exc!r}")
    return refuse(FAILED, 500)

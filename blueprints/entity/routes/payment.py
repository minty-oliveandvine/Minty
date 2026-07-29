"""Payment method routes for entities."""

from flask import jsonify, request
from flask_login import current_user, login_required

from blueprints.entity import entity_bp
from blueprints.entity.services.payment_methods import \
    add_payment_method as add_payment_method_service
from blueprints.entity.services.payment_methods import \
    delete_payment_method as delete_payment_method_service
from blueprints.entity.services.payment_methods import (list_available_methods,
                                                        list_payment_methods)
from blueprints.entity.services.payment_methods import \
    reorder_payment_methods as reorder_payment_methods_service
from blueprints.entity.services.payment_methods import \
    update_payment_method as update_payment_method_service


@entity_bp.route("/api/entities/<string:entity_id>/payment-methods", methods=["GET"])
@login_required
def get_payment_methods(entity_id):
    response, status = list_payment_methods(current_user.id, entity_id)
    return jsonify(response), status


@entity_bp.route(
    "/api/entities/<string:entity_id>/payment-methods/available", methods=["GET"]
)
@login_required
def get_available_payment_methods(entity_id):
    """Catalog methods this entity has not added yet, grouped by type.

    Feeds the Electronic and Delivery dropdowns in Entity Settings so a user
    picks an existing method instead of retyping its name (and accidentally
    minting a near-duplicate catalog row).
    """
    response, status = list_available_methods(current_user.id, entity_id)
    return jsonify(response), status


@entity_bp.route("/api/entities/<string:entity_id>/payment-methods", methods=["POST"])
@login_required
def add_payment_method(entity_id):
    data = request.get_json()
    response, status = add_payment_method_service(current_user.id, entity_id, data)
    return jsonify(response), status


@entity_bp.route(
    "/api/entities/<string:entity_id>/payment-methods/<string:method_id>",
    methods=["PUT"],
)
@login_required
def update_payment_method(entity_id, method_id):
    data = request.get_json()
    response, status = update_payment_method_service(
        current_user.id, entity_id, method_id, data
    )
    return jsonify(response), status


@entity_bp.route(
    "/api/entities/<string:entity_id>/payment-methods/<string:method_id>",
    methods=["DELETE"],
)
@login_required
def delete_payment_method(entity_id, method_id):
    response, status = delete_payment_method_service(current_user.id, entity_id, method_id)
    return jsonify(response), status


@entity_bp.route("/api/entities/<string:entity_id>/payment-methods/reorder", methods=["PUT"])
@login_required
def reorder_payment_methods(entity_id):
    data = request.get_json()
    method_ids = (data or {}).get("method_ids")
    response, status = reorder_payment_methods_service(current_user.id, entity_id, method_ids)
    return jsonify(response), status

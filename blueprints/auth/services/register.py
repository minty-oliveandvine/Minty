from flask import jsonify

from blueprints.auth.forms import RegistrationForm


def validate_register_all():
    form = RegistrationForm()
    form.validate()
    return jsonify({"errors": dict(form.errors.items())})

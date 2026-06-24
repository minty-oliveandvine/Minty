import uuid

from flask import (flash, get_flashed_messages, jsonify, redirect,
                   render_template, request, url_for)
from werkzeug.security import generate_password_hash

from blueprints.auth import auth_bp
from blueprints.auth.forms import RegistrationForm
from models.db import User, db


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            password = form.password.data
            if not password:
                flash("Password is required.", "danger")
                return redirect(url_for("auth.register"))
            hashed_password = generate_password_hash(
                password, method="pbkdf2:sha256")
            user = User.query.with_entities(User.username).filter_by(
                username=form.username.data
            ).first()
            if user:
                flash(
                    "Account with this username is already taken. Please contact administrator or use different username",
                    "danger",
                )
                return redirect(url_for("auth.register"))
            else:
                new_user = User(
                    id=str(uuid.uuid4()),
                    first_name=form.first_name.data,
                    last_name=form.last_name.data,
                    username=form.username.data,
                    password=hashed_password,
                    email=form.email.data,
                    system_role=User.SYSTEM_ROLE_DEFAULT,
                    approved=True,
                )
                db.session.add(new_user)
                db.session.commit()
                flash("Your account has been created! You can now log in.", "success")
                return redirect(url_for("auth.login"))
        except Exception as e:
            db.session.rollback()
            print(f"Error during registration: {e}")
            flash(
                "There was an error during registration. Please try again later.",
                "danger",
            )
            return redirect(url_for("auth.register"))
    get_flashed_messages()
    return render_template(
        "register.html",
        form=form,
        first_name=form.first_name.data,
        last_name=form.last_name.data,
        username=form.username.data,
        password=form.password.data,
        confirm_password=form.confirm_password.data,
        email=form.email.data,
    )


@auth_bp.route("/validate_register", methods=["POST", "GET"])
def validate_register():
    form = RegistrationForm()
    errors = {}
    form.validate()
    for key, error in form.errors.items():
        if (
            isinstance(error, list)
            and len(error) > 0
            and error[0] != "This field is required."
        ):
            errors[key] = error
    error_count = len(dict(form.errors.items()))
    return jsonify({"errors": errors, "errorCount": error_count})


@auth_bp.route("/validate_username", methods=["POST"])
def validate_username():
    data = request.get_json()
    username = data.get("username")
    user = User.query.filter_by(username=username).first()
    return jsonify({"exists": user is not None})



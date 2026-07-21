from flask import flash, get_flashed_messages, redirect, render_template, url_for
from flask_login import current_user, login_user
from werkzeug.security import check_password_hash

from blueprints.auth import auth_bp
from blueprints.auth.forms import LoginForm
from models.db import User


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.index"))
    form: LoginForm = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user:
            if user.approved:
                password_data: str = str(form.password.data)
                if check_password_hash(user.password, password_data):
                    login_user(user)
                    # Drain any flashes left queued in the session from a
                    # pre-login request (e.g. a stale deep link that flashed
                    # "Entity not found" then redirected). Flashes survive
                    # redirects until a page renders the `danger` category, so
                    # without this the old error pops up next to the
                    # login-success toast. Same defensive pattern used in the
                    # Xero callback, logout.py and register.py.
                    get_flashed_messages()
                    flash("Login Successful!", "success")
                    if user.system_role == User.SYSTEM_ROLE_SUPERUSER:
                        return redirect(url_for("user_management.admin"))
                    else:
                        return redirect(url_for("auth.index"))
                else:
                    flash("Incorrect password.", "danger")
            else:
                flash("Your account is not approved yet.", "warning")
        else:
            flash(
                "Login unsuccessful. Please check your username and password.", "danger"
            )
    return render_template("login.html", form=form)


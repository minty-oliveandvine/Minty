from flask import flash, redirect, render_template, url_for
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


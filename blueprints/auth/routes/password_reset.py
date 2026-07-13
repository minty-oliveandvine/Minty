from datetime import datetime, timedelta

from flask import current_app, flash, redirect, render_template, url_for
from flask_login import current_user
from flask_mail import Message
from loguru import logger
from werkzeug.security import generate_password_hash

from blueprints.auth import auth_bp
from blueprints.auth.forms import RequestResetForm, ResetPasswordForm
from models.db import User, db


@auth_bp.route("/reset_password", methods=["GET", "POST"])
def reset_request():
    if current_user.is_authenticated:
        return redirect(url_for("auth.home"))
    form = RequestResetForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            reset_token = str(__import__("uuid").uuid4())
            user.reset_token = reset_token
            user.reset_token_expiry = datetime.now() + timedelta(hours=1)
            try:
                db.session.commit()
                url_link = url_for(
                    "auth.reset_token", token=reset_token, _external=True
                )
                mail = current_app.extensions.get("mail")
                if mail is not None and user.email == form.email.data:
                    msg = Message(
                        subject="Reset Link: Pettycash-dev",
                        body=f"To reset your password you can click the reset link you will be redirected to a new browser tab to reset your password: <br> <a href={url_link} target='_blank'>Reset link</a>",
                        sender=current_app.config["BREVO_EMAIL"],
                        recipients=[
                            user.email],
                    )
                    mail.send(msg)
                    logger.info(
                        f"Password reset link is sent to {form.email.data}")
                    flash(
                        f"Password reset link has been sent to {form.email.data}. It might take 1-3 minutes for you to receive the reset link.",
                        "info",
                    )
                else:
                    flash(
                        "No email found or different email used, please contact administrator to request an email.",
                        "danger",
                    )
                return redirect(url_for("auth.login"))
            except Exception as e:
                db.session.rollback()
                print(f"Error during password reset request: {e}")
                flash(
                    "We couldn't send your password reset link right now. Please "
                    "try again in a few minutes, or contact your administrator if "
                    "this keeps happening.",
                    "danger",
                )
        else:
            flash("No account found with that username.", "danger")
    return redirect(url_for("auth.login"))


@auth_bp.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_token(token):
    if current_user.is_authenticated:
        return redirect(url_for("auth.home"))
    user = User.query.filter_by(reset_token=token).first()
    if user is None:
        flash("That is an invalid or expired reset token", "warning")
        return redirect(url_for("auth.reset_request"))
    if user.reset_token_expiry and user.reset_token_expiry < datetime.now():
        flash("That reset token has expired", "warning")
        return redirect(url_for("auth.reset_request"))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        try:
            if form.password.data is None:
                flash("Password cannot be empty.", "danger")
                return render_template(
                    "reset_token.html", form=form, token=token)
            hashed_password = generate_password_hash(
                form.password.data, method="pbkdf2:sha256"
            )
            user.password = hashed_password
            user.reset_token = None
            user.reset_token_expiry = None
            db.session.commit()
            flash("Your password has been updated! You can now log in.", "success")
            return redirect(url_for("auth.login"))
        except Exception as e:
            db.session.rollback()
            print(f"Error during password reset: {e}")
            flash(
                "We couldn't update your password. Please try again.",
                "danger",
            )
    return render_template("reset_token.html", form=form, token=token)

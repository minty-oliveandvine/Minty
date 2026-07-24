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
                        recipients=[user.email],
                    )
                    mail.send(msg)
                    logger.info(f"Password reset link is sent to {form.email.data}")
                    flash(
                        f"I've sent a reset link to {form.email.data} — it can take 1-3 minutes to arrive.",
                        "info",
                    )
                else:
                    flash(
                        "We couldn't send a reset email — our mail service isn't reachable right now. Please let your administrator know.",
                        "danger",
                    )
                return redirect(url_for("auth.login"))
            except Exception as e:
                db.session.rollback()
                print(f"Error during password reset request: {e}")
                flash(
                    "I couldn't get your reset link sent just now. Please try "
                    "again in a few minutes, or tell your administrator if it "
                    "keeps happening.",
                    "danger",
                )
        else:
            flash("Hmm, that username doesn't look familiar.", "danger")
    return redirect(url_for("auth.login"))


@auth_bp.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_token(token):
    if current_user.is_authenticated:
        return redirect(url_for("auth.home"))
    user = User.query.filter_by(reset_token=token).first()
    if user is None:
        flash(
            "This reset link doesn't work anymore. Want me to send a fresh one?",
            "warning",
        )
        return redirect(url_for("auth.reset_request"))
    if user.reset_token_expiry and user.reset_token_expiry < datetime.now():
        flash("This reset link has expired. Want me to send a fresh one?", "warning")
        return redirect(url_for("auth.reset_request"))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        try:
            if form.password.data is None:
                flash("I can't let you in without a password.", "danger")
                return render_template("reset_token.html", form=form, token=token)
            hashed_password = generate_password_hash(
                form.password.data, method="pbkdf2:sha256"
            )
            user.password = hashed_password
            user.reset_token = None
            user.reset_token_expiry = None
            db.session.commit()
            flash("Your password is all set — you can log in now.", "success")
            return redirect(url_for("auth.login"))
        except Exception as e:
            db.session.rollback()
            print(f"Error during password reset: {e}")
            flash(
                "I couldn't save your new password. Mind trying again?",
                "danger",
            )
    return render_template("reset_token.html", form=form, token=token)

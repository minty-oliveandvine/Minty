from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, EqualTo, Length


class LoginForm(FlaskForm):
    username: StringField = StringField(
        "Username", validators=[DataRequired(), Length(min=4, max=150)]
    )
    password: PasswordField = PasswordField("Password", validators=[DataRequired()])
    submit: SubmitField = SubmitField("Login")


class RequestResetForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Length(min=4, max=150)])
    submit = SubmitField("Request Password Reset")


class ResetPasswordForm(FlaskForm):
    password = PasswordField("New Password", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        "Confirm Password", validators=[DataRequired(), EqualTo("password")]
    )
    submit = SubmitField("Reset Password")

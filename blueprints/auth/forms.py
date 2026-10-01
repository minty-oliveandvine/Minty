from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length

from blueprints.shared.email_rules import ascii_email_validator

# Shared so every "this field is empty" error on the form reads identically.
_REQUIRED = "Please fill in this field"


class RegistrationForm(FlaskForm):
    first_name = StringField(
        "First Name",
        validators=[
            DataRequired(message=_REQUIRED),
            Length(max=150, message="Please use 150 characters or fewer"),
        ],
    )
    last_name = StringField(
        "Last Name",
        validators=[
            DataRequired(message=_REQUIRED),
            Length(max=150, message="Please use 150 characters or fewer"),
        ],
    )
    # Password collection temporarily disabled — restore these fields (and the
    # password handling in routes/register.py + the template inputs) to bring
    # password sign-up back.
    # password = PasswordField(
    #     "Password",
    #     validators=[
    #         DataRequired(message=_REQUIRED),
    #         Length(min=6, message="Please use at least 6 characters"),
    #     ],
    # )
    # confirm_password = PasswordField(
    #     "Confirm Password",
    #     validators=[
    #         DataRequired(message=_REQUIRED),
    #         EqualTo("password", message="Passwords do not match"),
    #     ],
    # )
    email = StringField(
        "Email",
        validators=[
            DataRequired(message=_REQUIRED),
            Email(message="Please enter a valid email address"),
            ascii_email_validator,
            Length(max=150, message="Please use 150 characters or fewer"),
        ],
    )
    submit = SubmitField("Sign Up")


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

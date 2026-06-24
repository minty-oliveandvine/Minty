from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, EqualTo, Length


class RegistrationForm(FlaskForm):
    first_name = StringField(
        "First Name", validators=[DataRequired(), Length(min=1, max=150)]
    )
    last_name = StringField(
        "Last Name", validators=[DataRequired(), Length(min=1, max=150)]
    )
    username = StringField(
        "Username", validators=[DataRequired(), Length(min=4, max=150)]
    )
    password = PasswordField("Password", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        "Confirm Password", validators=[DataRequired(), EqualTo("password")]
    )
    email = StringField("Email", validators=[DataRequired(), Length(min=4, max=150)])
    submit = SubmitField("Sign Up")


class LoginForm(FlaskForm):
    username:StringField = StringField(
        "Username", validators=[DataRequired(), Length(min=4, max=150)]
    )
    password:PasswordField = PasswordField("Password", validators=[DataRequired()])
    submit:SubmitField = SubmitField("Login")


class RequestResetForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Length(min=4, max=150)])
    submit = SubmitField("Request Password Reset")


class ResetPasswordForm(FlaskForm):
    password = PasswordField("New Password", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        "Confirm Password", validators=[DataRequired(), EqualTo("password")]
    )
    submit = SubmitField("Reset Password")

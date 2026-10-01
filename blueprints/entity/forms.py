"""Entity-related forms."""

from flask_wtf import FlaskForm
from wtforms import EmailField, StringField
from wtforms.validators import DataRequired, Email, Length

from blueprints.shared.email_rules import ascii_email_validator


class CreateEntityForm(FlaskForm):
    entity_name = StringField(
        "Entity Name", default="", validators=[DataRequired(), Length(min=1, max=100)]
    )
    country_code = StringField(
        "Country Code", default="HK", validators=[Length(min=2, max=3), DataRequired()]
    )
    currency_code = StringField(
        "Currency Code",
        default="HKD",
        validators=[Length(min=3, max=10), DataRequired()],
    )
    contact_phone = StringField(
        "Contact Phone", default="", validators=[Length(min=8, max=11), DataRequired()]
    )
    business_email = EmailField(
        "Business Email", default="", validators=[
            DataRequired(),
            # The shape check type="email" used to do in the browser: without it, a malformed
            # address passed here and entity_create saved it as NULL without a word.
            Email(message="Please enter a valid business email."),
            ascii_email_validator,
        ]
    )


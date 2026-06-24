"""Entity-related forms."""

from flask_wtf import FlaskForm
from wtforms import EmailField, StringField
from wtforms.validators import DataRequired, Length


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
        "Business Email", default="", validators=[DataRequired()]
    )


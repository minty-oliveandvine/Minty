from flask_wtf import FlaskForm
from wtforms import SelectField, StringField
from wtforms.validators import DataRequired, Length


class FindUserForm(FlaskForm):
    first_name = StringField(
        "First Name", validators=[DataRequired(), Length(min=1, max=150)]
    )
    last_name = StringField(
        "Last Name", validators=[DataRequired(), Length(min=1, max=150)]
    )
    entity_id = SelectField("Entity", coerce=str, validators=[DataRequired()])
